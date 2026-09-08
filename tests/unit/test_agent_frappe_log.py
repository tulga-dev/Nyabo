from __future__ import annotations

import sys
import types
from decimal import Decimal

from nyabo_mn.agent import frappe_log
from nyabo_mn.agent.llm_client import CallRecord


def _record(**overrides) -> CallRecord:
	base = dict(
		purpose="extract",
		provider="openai",
		model="gpt-5.6-terra",
		prompt_version="receipt_extract.v1",
		tokens_in=1000,
		tokens_out=100,
		latency_ms=812,
		ok=True,
	)
	base.update(overrides)
	return CallRecord(**base)


def test_as_doc_matches_doctype_fields_and_estimates_cost():
	doc = frappe_log.as_doc(_record(), company="Тест ХХК", proposal="NYP-00001")
	assert doc["doctype"] == "Nyabo LLM Call" and doc["ok"] == 1 and doc["company"] == "Тест ХХК"
	assert doc["cost_usd"] == float(Decimal("0.003200"))
	assert set(doc) == {
		"doctype",
		"purpose",
		"provider",
		"model",
		"prompt_version",
		"ok",
		"error_class",
		"tokens_in",
		"tokens_out",
		"latency_ms",
		"cost_usd",
		"company",
		"proposal",
	}
	assert frappe_log.as_doc(_record(purpose="weird"))["purpose"] == "other"
	assert frappe_log.as_doc(_record(ok=False, error_class="LlmTimeout"))["ok"] == 0


def test_record_inserts_through_a_fake_frappe(monkeypatch):
	inserted = []

	class Doc:
		def __init__(self, data):
			self.data = data
			self.name = "NYL-000001"

		def insert(self, ignore_permissions=False):
			assert ignore_permissions
			inserted.append(self.data)

	fake = types.ModuleType("frappe")
	fake.get_doc = lambda data: Doc(data)
	monkeypatch.setitem(sys.modules, "frappe", fake)
	assert frappe_log.recorder(company="C")(_record()) is None
	assert inserted[0]["company"] == "C" and inserted[0]["tokens_in"] == 1000


def test_record_swallows_insert_failures(monkeypatch):
	fake = types.ModuleType("frappe")

	def boom(data):
		raise RuntimeError("no table")

	fake.get_doc = boom
	fake.get_traceback = lambda: "tb"
	fake.log_error = lambda **kw: None
	fake.local = types.SimpleNamespace(site="s")
	fake.logger = lambda *a, **k: types.SimpleNamespace(error=lambda m: None)
	monkeypatch.setitem(sys.modules, "frappe", fake)
	assert frappe_log.record(_record()) is None


def test_record_without_frappe_is_a_noop(monkeypatch):
	monkeypatch.setitem(sys.modules, "frappe", None)  # makes `import frappe` raise ImportError
	assert frappe_log.record(_record()) is None
