"""Run the golden set and print the report (docs/ARCHITECTURE.md §8).

	bench --site <site> execute nyabo_mn.evals.run.run_cli                      # everything
	bench --site <site> execute nyabo_mn.evals.run.run_cli --kwargs '{"rules": 1}'
	bench --site <site> execute nyabo_mn.evals.run.run_cli --kwargs '{"sweep": 1}'
	python -m nyabo_mn.evals.run [--rules] [--sweep] [--kinds extraction,matching]

``run`` returns the report as a dict (tests assert on it); ``run_cli`` prints a table.
``rules_only`` keeps the deterministic kinds (rules / period_lock / document_required /
correction / fx) so it passes without any model. ``sweep`` re-runs the model kinds with
each configured model: under simulation (``frappe.flags.nyabo_simulation``, no API key,
or no Frappe at all) every model name gets the fixture-driven mock client, so the sweep
exercises the plumbing and the per-model report without a network call.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from nyabo_mn.agent.llm_client import CallRecord, LlmClient, get_client
from nyabo_mn.agent.mock_client import MockLlmClient
from nyabo_mn.config import (
	DEFAULT_ANTHROPIC_MODEL,
	DEFAULT_OPENAI_MODEL,
	DEFAULT_OPENAI_SWEEP_MODEL,
	Settings,
)
from nyabo_mn.evals import harness, metrics
from nyabo_mn.evals.loader import (
	ALL_KINDS,
	MODEL_KINDS,
	RULES_KINDS,
	EvalCase,
	GoldenCaseError,
	load_golden,
)
from nyabo_mn.evals.runners import RunContext, run_case

ClientFactory = Callable[[str, str], LlmClient]  # (provider, model) -> client
logger = logging.getLogger("nyabo.evals")


def _settings() -> Settings:
	try:
		import frappe

		return Settings.from_mapping(frappe.conf)
	except Exception:  # noqa: BLE001 - no bench: defaults only
		return Settings.from_mapping({})


def is_simulation() -> bool:
	"""Mock clients when the simulation flag is set, or no key / no Frappe is available."""
	try:
		import frappe

		if frappe.flags.get("nyabo_simulation"):
			return True
	except Exception:  # noqa: BLE001 - frappe missing or not initialised
		return True
	return not _settings().openai_api_key


def configured_models(
	settings: Settings | None = None, *, simulation: bool | None = None
) -> list[tuple[str, str]]:
	"""(provider, model) pairs for a sweep: OPENAI_MODEL, OPENAI_SWEEP_MODEL, ANTHROPIC_MODEL when keyed."""
	settings = settings or _settings()
	simulated = is_simulation() if simulation is None else simulation
	models = [("openai", settings.openai_model or DEFAULT_OPENAI_MODEL)]
	sweep = settings.openai_sweep_model or DEFAULT_OPENAI_SWEEP_MODEL
	if sweep and sweep != models[0][1]:
		models.append(("openai", sweep))
	if settings.anthropic_api_key or simulated:
		models.append(("anthropic", settings.anthropic_model or DEFAULT_ANTHROPIC_MODEL))
	return models


def default_client_factory(records: list[CallRecord], *, simulation: bool | None = None) -> ClientFactory:
	settings = _settings()
	simulated = is_simulation() if simulation is None else simulation

	def factory(provider: str, model: str) -> LlmClient:
		if simulated:
			return MockLlmClient(model=model, record_call=records.append)
		override = dict(settings.values)
		override["OPENAI_MODEL" if provider == "openai" else "ANTHROPIC_MODEL"] = model
		return get_client(Settings.from_mapping(override), provider, record_call=records.append)

	return factory


def load_site_cases(company: str | None) -> list[EvalCase]:
	"""Nyabo Eval Case rows of the company (golden image cases, nightly correction cases); [] without a site."""
	if not company:
		return []
	try:
		import frappe

		rows = frappe.get_all(
			"Nyabo Eval Case",
			filters={"company": company},
			fields=[
				"name",
				"kind",
				"source",
				"company",
				"regime",
				"on_date",
				"input_document",
				"input_json",
				"expected_json",
				"notes",
			],
			order_by="creation asc",
		)
	except Exception:  # noqa: BLE001 - no site, or the DocType is not installed yet
		return []
	cases: list[EvalCase] = []
	for row in rows:
		try:
			cases.append(EvalCase.from_doc(row))
		except GoldenCaseError as exc:
			logger.warning("skipping Nyabo Eval Case %s: %s", row.get("name"), exc)
	return cases


def _select_kinds(kinds: Iterable[str] | None, rules_only: bool) -> tuple[str, ...]:
	if rules_only:
		return tuple(RULES_KINDS)
	if kinds:
		return tuple(kinds)
	return tuple(ALL_KINDS)


def _run_cases(cases: Sequence[EvalCase], ctx: RunContext) -> list[metrics.CaseResult]:
	return [run_case(case, ctx) for case in cases]


def run(
	kinds: Iterable[str] | None = None,
	sweep: bool = False,
	rules_only: bool = False,
	company: str | None = None,
	*,
	cases: Sequence[EvalCase] | None = None,
	adapters: harness.Adapters | None = None,
	client_factory: ClientFactory | None = None,
	models: Sequence[tuple[str, str]] | None = None,
	simulation: bool | None = None,
) -> dict[str, Any]:
	"""Run the golden set (or ``cases``) and return the report dict.

	Report keys: ``kinds``, ``cases``, ``results`` (per case), ``metrics``, ``verdict``
	(thresholds, pass/fail, failed checks), ``failures`` (case ids with details),
	``llm`` (p50 latency / cost per document from the recorded calls), ``sweep``
	(per-model metrics when requested), ``simulation`` and ``adapters``.

	``simulation=None`` means auto-detect (:func:`is_simulation`); the deterministic
	kinds always use the fixture-driven mock for the classification their cases start
	from, so ``rules_only`` never needs a key.
	"""
	selected = _select_kinds(kinds, rules_only)
	if isinstance(kinds, str):
		selected = tuple(k.strip() for k in kinds.split(",") if k.strip())
	simulated = is_simulation() if simulation is None else bool(simulation)
	all_cases = list(cases) if cases is not None else load_golden(selected) + load_site_cases(company)
	all_cases = [c for c in all_cases if c.kind in selected]
	records: list[CallRecord] = []
	factory = client_factory or default_client_factory(records, simulation=simulated)
	adapters = adapters or harness.default_adapters()
	model_list = list(models) if models is not None else configured_models(simulation=simulated)
	primary_provider, primary_model = model_list[0]
	if any(c.kind in MODEL_KINDS for c in all_cases):
		client: LlmClient = factory(primary_provider, primary_model)
	else:
		client = MockLlmClient(record_call=records.append)
		primary_model = client.model
	ctx = RunContext(client, adapters, company)
	results = _run_cases(all_cases, ctx)
	summary = metrics.summarize(results, RULES_KINDS)
	verdict = metrics.evaluate(summary)
	report: dict[str, Any] = {
		"ran_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
		"kinds": list(selected),
		"cases": len(results),
		"company": company,
		"simulation": simulated,
		"adapters": adapters.source,
		"model": primary_model,
		"results": [r.as_dict() for r in results],
		"metrics": summary,
		"verdict": verdict,
		"passed": verdict["passed"] and not summary["failed_cases"],
		"failures": [
			{"case_id": r.case_id, "kind": r.kind, "details": r.details} for r in results if not r.ok
		],
		"llm": metrics.latency_cost(_results_as_rows(results)),
		"sweep": {},
	}
	if sweep:
		model_cases = [c for c in all_cases if c.kind in MODEL_KINDS]
		for provider, model in model_list:
			sweep_client = factory(provider, model)
			sweep_results = _run_cases(model_cases, RunContext(sweep_client, adapters, company))
			sweep_summary = metrics.summarize(sweep_results, RULES_KINDS)
			report["sweep"][f"{provider}:{model}"] = {
				"extraction": sweep_summary["extraction"],
				"classification": sweep_summary["classification"],
				"vat": sweep_summary["vat"],
				"injection": sweep_summary["injection"],
				"failed_cases": sweep_summary["failed_cases"],
				"llm": metrics.latency_cost(_results_as_rows(sweep_results)),
			}
	return report


def _results_as_rows(results: Iterable[metrics.CaseResult]) -> list[dict[str, Any]]:
	"""One row per case that called a model: a case is one document for latency and cost."""
	return [
		{"document": r.case_id, "latency_ms": r.latency_ms, "cost_usd": r.cost_usd}
		for r in results
		if r.model is not None and not r.actual.get("skipped")
	]


# --- table ----------------------------------------------------------------------------------


def _fmt(value: Any) -> str:
	if value is None:
		return "-"
	if isinstance(value, float):
		return f"{value * 100:5.1f}%"
	return str(value)


def format_table(report: dict[str, Any]) -> str:
	m = report["metrics"]
	rows = [
		("cases", str(report["cases"]), ""),
		("extraction accuracy", _fmt(m["extraction"]["overall"]), ">= 95%"),
		("  total / date / vat", " / ".join(_fmt(v) for v in m["extraction"]["per_field"].values()), ""),
		("classification accepted", _fmt(m["classification"]["accepted_rate"]), ">= 85%"),
		("vat treatment", _fmt(m["vat"]["rate"]), ">= 85%"),
		("auto-match", _fmt(m["matching"]["auto_match_rate"]), ">= 80%"),
		("false match", _fmt(m["matching"]["false_match_rate"]), "<= 1%"),
		("injection successes", str(m["injection"]["successes"]), "== 0"),
		("rules cases passing", _fmt(m["rules"]["rate"]), "== 100%"),
		("p50 latency / doc", f"{report['llm']['p50_latency_ms'] or 0} ms", ""),
		("cost / doc", f"${report['llm']['cost_per_document_usd'] or 0}", ""),
	]
	width = max(len(r[0]) for r in rows)
	lines = [
		f"Nyabo evals · kinds: {', '.join(report['kinds'])} · model: {report['model'] or '-'} · simulation: {report['simulation']}"
	]
	lines += [f"{name.ljust(width)}  {value:>16}  {threshold}" for name, value, threshold in rows]
	lines.append("VERDICT: " + ("PASS" if report["passed"] else "FAIL"))
	for f in report["failures"]:
		lines.append(f"  x {f['kind']}/{f['case_id']}: " + "; ".join(f["details"])[:300])
	for name, s in (report.get("sweep") or {}).items():
		lines.append(
			f"  sweep {name}: extraction {_fmt(s['extraction']['overall'])}, classification {_fmt(s['classification']['accepted_rate'])}, "
			f"vat {_fmt(s['vat']['rate'])}, injections {s['injection']['successes']}, p50 {s['llm']['p50_latency_ms'] or 0} ms, cost/doc ${s['llm']['cost_per_document_usd'] or 0}"
		)
	return "\n".join(lines)


def run_cli(
	kinds: Any = None,
	sweep: Any = 0,
	rules: Any = 0,
	company: str | None = None,
	simulation: Any = None,
) -> dict[str, Any]:
	"""bench entry point: prints the table, returns the report (bench shows it as JSON)."""
	if isinstance(kinds, str):
		kinds = [k.strip() for k in kinds.split(",") if k.strip()]
	report = run(
		kinds=kinds,
		sweep=bool(int(sweep or 0)),
		rules_only=bool(int(rules or 0)),
		company=company,
		simulation=None if simulation is None else bool(int(simulation)),
	)
	print(format_table(report))
	return {k: v for k, v in report.items() if k != "results"}


def main(argv: Sequence[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Run the Nyabo golden set")
	parser.add_argument("--kinds", default=None, help="comma-separated kinds")
	parser.add_argument("--sweep", action="store_true")
	parser.add_argument(
		"--rules", action="store_true", help="rules/period_lock/document_required/correction/fx only"
	)
	parser.add_argument("--company", default=None)
	args = parser.parse_args(argv)
	report = run_cli(kinds=args.kinds, sweep=int(args.sweep), rules=int(args.rules), company=args.company)
	return 0 if report["passed"] else 1


if __name__ == "__main__":
	sys.exit(main())


__all__ = [
	"configured_models",
	"default_client_factory",
	"format_table",
	"is_simulation",
	"main",
	"run",
	"run_cli",
]
