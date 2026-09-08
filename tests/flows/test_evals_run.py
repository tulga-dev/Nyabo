"""``evals.run`` on the golden set: rules-only passes, the model kinds hit the brief's thresholds.

Dependency modules missing in this worktree (``nyabo_mn.rules``, ``agent.pipeline``,
``compliance.reversal``) are covered by ``harness.Adapters`` fallbacks; ``fake_adapters``
below shows how a test plugs the real ones in once they land.
"""

from __future__ import annotations

import dataclasses

import pytest

from nyabo_mn.agent.mock_client import MockLlmClient
from nyabo_mn.evals import harness, loader, metrics
from nyabo_mn.evals import run as run_mod
from nyabo_mn.evals.runners import RunContext, run_case

# Cases that fail today because of a gap in another module (see the integration requests
# in the stage report). The assertion below flips when the gap is fixed, so the entry is
# removed then rather than forgotten.
KNOWN_GAPS = {"inj_mn_no_check": "core.quarantine misses the 'батлаарай' / 'шалгах хэрэггүй' stems"}


def test_rules_only_passes_without_any_model():
	report = run_mod.run(rules_only=True)
	assert report["kinds"] == list(loader.RULES_KINDS)
	assert report["cases"] == 28 and report["model"] == "mock-model"
	assert report["failures"] == []
	assert report["metrics"]["rules"]["rate"] == 1.0
	assert report["passed"] is True
	assert report["adapters"] == "nyabo_mn.rules.guard"  # the real guard, bypassed by the simulation flag


def test_rules_only_accepts_injected_adapters():
	verified: list[str] = []

	def accept(pattern):  # a stand-in for nyabo_mn.rules.guard.require_verified
		verified.append(pattern.pattern_id)

	adapters = dataclasses.replace(harness.default_adapters(), require_verified=accept, source="test")
	report = run_mod.run(rules_only=True, adapters=adapters)
	assert report["passed"] and report["adapters"] == "test"
	assert "purchase_expense_vat_payer" in verified


def test_full_run_meets_the_thresholds_except_known_gaps():
	report = run_mod.run()
	m = report["metrics"]
	assert m["extraction"]["overall"] >= metrics.THRESHOLDS["extraction_accuracy"]
	assert m["extraction"]["per_field"] == {"total": 1.0, "date": 1.0, "vat_amount": 1.0}
	assert m["classification"]["accepted_rate"] >= metrics.THRESHOLDS["classification_accepted_rate"]
	assert m["vat"]["rate"] >= metrics.THRESHOLDS["vat_accuracy"]
	assert m["matching"]["auto_match_rate"] >= metrics.THRESHOLDS["auto_match_rate"]
	assert m["matching"]["false_match_rate"] <= metrics.THRESHOLDS["false_match_rate_max"]
	assert m["rules"]["rate"] == 1.0
	assert set(m["failed_cases"]) == set(KNOWN_GAPS), "a known gap was fixed (remove it) or a case regressed"
	assert m["injection"]["success_cases"] == ["inj_mn_no_check"]
	assert report["simulation"] is True and report["model"] == "gpt-5.6-terra"
	assert report["llm"]["documents"] > 0 and report["llm"]["cost_per_document_usd"] is not None


def test_injection_defence_holds_every_detected_case():
	report = run_mod.run(kinds=["injection"])
	for result in report["results"]:
		if result["case_id"] in KNOWN_GAPS:
			continue
		assert result["ok"], result
		assert result["actual"]["needs_accountant"] is True
		assert "injection_suspected" in result["actual"]["flags"]
		assert result["actual"]["account_code"] == "6910"  # the default expense, never the instructed one


def test_planted_injection_success_is_counted():
	"""Switch the defence off: the compromised fixtures get through and the metric says so."""
	cases = loader.load_golden(["injection"])
	ctx = RunContext(MockLlmClient(), defend_injection=False)
	results = [run_case(c, ctx) for c in cases]
	found = metrics.injection_successes(results)
	assert found["successes"] >= 4 and found["cases"] == 5
	verdict = metrics.evaluate(metrics.summarize(results, loader.RULES_KINDS))
	assert verdict["checks"]["injection_successes"]["passed"] is False
	assert "injection_successes" in verdict["failed_checks"]


def test_sweep_runs_each_configured_model_with_the_mock():
	report = run_mod.run(kinds=["extraction", "classification"], sweep=True)
	assert set(report["sweep"]) == {
		"openai:gpt-5.6-terra",
		"openai:gpt-5.6-luna",
		"anthropic:claude-sonnet-5",
	}
	for name, s in report["sweep"].items():
		assert s["extraction"]["overall"] == 1.0 and s["classification"]["accepted_rate"] == 1.0, name
		assert s["llm"]["cost_per_document_usd"] is not None
	luna = report["sweep"]["openai:gpt-5.6-luna"]["llm"]["cost_per_document_usd"]
	terra = report["sweep"]["openai:gpt-5.6-terra"]["llm"]["cost_per_document_usd"]
	assert luna < terra  # the price table, not the mock, decides the cost


def test_custom_model_list_and_client_factory():
	seen: list[tuple[str, str]] = []

	def factory(provider: str, model: str) -> MockLlmClient:
		seen.append((provider, model))
		return MockLlmClient(model=model)

	report = run_mod.run(
		kinds=["classification"],
		sweep=True,
		client_factory=factory,
		models=[("openai", "x-1"), ("anthropic", "y-2")],
	)
	assert seen == [("openai", "x-1"), ("openai", "x-1"), ("anthropic", "y-2")]
	assert report["model"] == "x-1" and set(report["sweep"]) == {"openai:x-1", "anthropic:y-2"}


def test_kinds_accepts_a_comma_separated_string():
	report = run_mod.run(kinds="fx,period_lock")
	assert report["kinds"] == ["fx", "period_lock"] and report["cases"] == 8 and report["passed"]


def test_cli_table_lists_verdict_and_failures(capsys):
	report = run_mod.run_cli(rules=1)
	out = capsys.readouterr().out
	assert "VERDICT: PASS" in out and "rules cases passing" in out
	assert "results" not in report and report["passed"]
	text = run_mod.format_table(run_mod.run(kinds=["injection"]))
	assert "VERDICT: FAIL" in text and "inj_mn_no_check" in text


def test_unknown_kind_is_refused():
	with pytest.raises(loader.GoldenCaseError, match="unknown kinds"):
		run_mod.run(kinds=["nope"])


# --- on the stub: the Frappe side of period lock agrees with the fallback ------------------------


def test_period_lock_cases_agree_with_erpnext_on_the_stub(company, frappe_hooks):
	"""Site adapters read real Accounting Periods, so the site is built per case group; then
	ERPNext's own refusal on a Journal Entry must agree with the harness for every case date."""
	import frappe

	cases = loader.load_golden(["period_lock"])
	one_month = [c for c in cases if len(c.input_json["closed_periods"]) == 1]
	two_months = [c for c in cases if len(c.input_json["closed_periods"]) == 2]
	assert len(one_month) == 4 and len(two_months) == 1

	def close(period_name: str, start: str, end: str) -> None:
		frappe.get_doc(
			{
				"doctype": "Accounting Period",
				"period_name": period_name,
				"company": company,
				"start_date": start,
				"end_date": end,
			}
		).insert()

	close("2026-03", "2026-03-01", "2026-03-31")
	report = run_mod.run(cases=one_month, company=company, adapters=harness.site_adapters(company))
	assert report["passed"] and report["cases"] == 4 and report["adapters"].endswith("+site")
	close("2026-04", "2026-04-01", "2026-04-30")
	report = run_mod.run(cases=two_months, company=company, adapters=harness.site_adapters(company))
	assert report["passed"] and report["cases"] == 1

	site_periods = frappe.get_all(
		"Accounting Period", filters={"company": company}, fields=["start_date", "end_date"]
	)
	with frappe_hooks(without_apps=("nyabo_mn",)):
		for case in cases:
			posting_date = case.input_json["posting_date"]
			allowed, _msg = harness.posting_allowed_in_period(site_periods, harness.date_of(posting_date))
			je = frappe.get_doc(
				{
					"doctype": "Journal Entry",
					"voucher_type": "Journal Entry",
					"company": company,
					"posting_date": posting_date,
					"accounts": [
						{"account": "6210 - Шатахуун - TST", "debit_in_account_currency": 100},
						{"account": "1110 - Касс - TST", "credit_in_account_currency": 100},
					],
				}
			)
			if allowed:
				je.insert()
			else:
				with pytest.raises(frappe.ValidationError, match="closed Accounting Period"):
					je.insert()


def test_site_eval_cases_are_included_when_a_company_is_given(company):
	import frappe

	case = next(c for c in loader.load_golden(["fx"]))
	doc = frappe.get_doc({**case.to_doc(), "company": company})
	doc.insert()
	report = run_mod.run(kinds=["fx"], company=company)
	assert report["cases"] == 4 and report["passed"]
	assert doc.name and any(r["case_id"] == case.case_id for r in report["results"])
