"""frappe.db and frappe.get_all: the filter operator matrix and the query shapes the app uses."""

from __future__ import annotations

import datetime

import pytest

import frappe


DT = "Nyabo LLM Call"


@pytest.fixture
def calls(site):
	rows = [
		("extract", "gpt-5.6-terra", "Тест ХХК", None, "2026-03-01"),
		("classify", "gpt-5.6-terra", "Тест ХХК", "SchemaError", "2026-03-02"),
		("question", "claude-x", "Хоёр ХХК", None, "2026-03-31"),
		("eval", "gpt-5.6-luna", "Тест ХХК", "Timeout", "2026-04-15"),
	]
	out = []
	for purpose, model, company, error_class, when in rows:
		doc = frappe.get_doc(
			{"doctype": DT, "purpose": purpose, "model": model, "company": company, "error_class": error_class, "tokens_in": 10}
		)
		doc.flags.ignore_links = True
		doc.insert()
		frappe.db.set_value(DT, doc.name, "creation", datetime.datetime.fromisoformat(when))
		out.append(doc.name)
	return out


def _names(**kwargs):
	return frappe.get_all(DT, pluck="name", order_by="name asc", **kwargs)


def test_operator_matrix(calls):
	e1, e2, e3, e4 = calls
	assert _names(filters={"purpose": "question"}) == [e3]
	assert _names(filters={"purpose": ["!=", "question"]}) == [e1, e2, e4]
	assert _names(filters={"purpose": ["in", ["extract", "classify"]]}) == [e1, e2]
	assert _names(filters={"purpose": ["not in", ["extract", "classify"]]}) == [e3, e4]
	assert _names(filters={"creation": [">", "2026-03-02"]}) == [e3, e4]
	assert _names(filters={"creation": [">=", "2026-03-02"]}) == [e2, e3, e4]
	assert _names(filters={"creation": ["<", "2026-03-02"]}) == [e1]
	assert _names(filters={"creation": ["<=", "2026-03-02"]}) == [e1, e2]
	assert _names(filters={"model": ["like", "gpt-%"]}) == [e1, e2, e4]
	assert _names(filters={"model": ["not like", "gpt-%"]}) == [e3]
	assert _names(filters={"creation": ["between", ["2026-03-02", "2026-03-31"]]}) == [e2, e3]
	assert _names(filters={"error_class": ["is", "set"]}) == [e2, e4]
	assert _names(filters={"error_class": ["is", "not set"]}) == [e1, e3]
	assert _names(filters={"tokens_in": [">=", 10]}) == [e1, e2, e3, e4]
	# list-of-lists form, with and without the doctype
	assert _names(filters=[["purpose", "=", "question"]]) == [e3]
	assert _names(filters=[[DT, "company", "=", "Хоёр ХХК"]]) == [e3]


def test_fields_star_pluck_order_and_limits(calls):
	rows = frappe.get_all(DT, fields=["*"], order_by="creation desc")
	assert rows[0].purpose == "eval"
	assert "cost_usd" in rows[0]
	assert frappe.get_all(DT, pluck="purpose", order_by="creation asc", limit=2) == ["extract", "classify"]
	assert frappe.get_all(DT, pluck="purpose", order_by="creation asc", limit_start=1, limit_page_length=2) == [
		"classify",
		"question",
	]
	assert frappe.get_all(DT, fields=["name", "purpose as kind"], limit=1)[0].kind
	assert frappe.db.count(DT, {"company": "Тест ХХК"}) == 3


def test_aggregates_and_sql_are_refused(calls):
	with pytest.raises(NotImplementedError):
		frappe.get_all(DT, fields=["count(name) as c"])
	with pytest.raises(NotImplementedError):
		frappe.db.sql("select 1")
	with pytest.raises(frappe.ValidationError):
		frappe.get_all(DT, filters={"no_such_field": 1})


def test_get_value_shapes(calls):
	e1 = calls[0]
	assert frappe.db.get_value(DT, e1, "purpose") == "extract"
	assert frappe.db.get_value(DT, {"purpose": "question"}, "company") == "Хоёр ХХК"
	assert frappe.db.get_value(DT, e1, ["purpose", "company"]) == ("extract", "Тест ХХК")
	row = frappe.db.get_value(DT, e1, ["purpose", "company"], as_dict=True)
	assert row.company == "Тест ХХК"
	assert frappe.db.get_value(DT, "NYL-999999", "purpose") is None
	assert frappe.db.exists(DT, e1) == e1
	assert frappe.db.exists(DT, {"purpose": "nope"}) is None
	assert frappe.db.exists({"doctype": DT, "purpose": "question"}) == calls[2]


def test_set_value_field_and_dict(calls):
	e1 = calls[0]
	frappe.db.set_value(DT, e1, "provider", "openai")
	frappe.db.set_value(DT, e1, {"company": "Гурав ХХК", "provider": "anthropic"})
	row = frappe.db.get_value(DT, e1, ["company", "provider", "modified_by"], as_dict=True)
	assert (row.company, row.provider, row.modified_by) == ("Гурав ХХК", "anthropic", "Administrator")
	with pytest.raises(frappe.ValidationError):
		frappe.db.set_value(DT, e1, "provder", "typo")


def test_singles_commit_rollback(site):
	frappe.db.set_single_value("Accounts Settings", "allow_stale", 0)
	assert frappe.db.get_single_value("Accounts Settings", "allow_stale") == 0
	assert frappe.get_single_value("Accounts Settings", "stale_days") is None
	frappe.db.savepoint("sp1")
	frappe.db.rollback(save_point="sp1")
	frappe.db.commit()
	assert frappe.db.commit_count == 1
	assert frappe.db.rollback_count == 1
