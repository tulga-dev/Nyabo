"""params / regime / guard / patterns against the synced seed."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import frappe
import pytest

from nyabo_mn.core.models import Regime
from nyabo_mn.core.rules_engine import MissingRuleError, PendingRuleError
from nyabo_mn.i18n import mn
from nyabo_mn.rules import guard, params, patterns, regime


def test_params_get_is_dated_and_never_falls_back(seeded):
	assert params.get_decimal(
		"vat.registration_threshold", dt.date(2026, 12, 31), allow_unverified=True
	) == Decimal("50000000")
	assert params.get_decimal(
		"vat.registration_threshold", dt.date(2027, 1, 1), allow_unverified=True
	) == Decimal("400000000")
	assert params.get("vat.rate", dt.date(2027, 6, 1), allow_unverified=True).as_decimal() == Decimal("0.1")
	# the 2027 simplified-regime change is still a Government bill: pending, value null (D-012)
	with pytest.raises(PendingRuleError):
		params.get("simplified.revenue_threshold", dt.date(2027, 3, 1), allow_unverified=True)
	with pytest.raises(MissingRuleError):
		params.get("vat.registration_threshold", dt.date(2025, 12, 31), allow_unverified=True)
	# verified Law on Accounting rows pass the guard without any flag
	assert params.get_decimal("retention.years", dt.date(2026, 1, 1)) == Decimal("10")
	assert [r.effective_from.year for r in params.history("vat.registration_threshold")] == [2026, 2027]
	# the seed quote reaches the DocType (quote_mn), verified rows always carry one
	assert frappe.db.get_value("Nyabo Tax Parameter", "retention.years:2016-01-01", "quote_mn").startswith(
		"11.1."
	)


def test_guard_refuses_unverified_rules_with_the_mongolian_message(seeded, frappe_flags):
	# si.employee_rate is a derived total (sum of the per-fund rows) and ships unverified
	assert not frappe.db.get_value("Nyabo Tax Parameter", "si.employee_rate:2026-01-01", "verified")
	with pytest.raises(guard.UnverifiedRuleError) as excinfo:
		params.get("si.employee_rate", dt.date(2026, 3, 1))
	assert str(excinfo.value) == mn.MSG_UNVERIFIED_RULE_BLOCKED.format(rule="si.employee_rate")
	assert isinstance(excinfo.value, frappe.ValidationError)

	with pytest.raises(guard.UnverifiedRuleError, match="bank_fee_expense"):
		guard.require_verified("bank_fee_expense")
	with pytest.raises(guard.UnverifiedRuleError):
		guard.require_verified(("Nyabo Bank Layout", "generic_mn"))
	with pytest.raises(guard.UnverifiedRuleError):
		guard.require_verified(patterns.load("payable_pay"))
	with pytest.raises(guard.UnverifiedRuleError, match="no-such-rule"):
		guard.require_verified("no-such-rule")  # unknown names count as unverified
	assert guard.is_verified("retention.years:2016-01-01") and not guard.is_verified("bank_fee_expense")

	frappe.db.set_value("Nyabo Posting Pattern", "bank_fee_expense", "verified", 1)
	guard.require_verified(
		"bank_fee_expense", frappe.get_doc("Nyabo Tax Parameter", "retention.years:2016-01-01")
	)

	with frappe_flags(nyabo_simulation=True):
		assert guard.is_simulation()
		guard.require_verified("payable_pay", ("Nyabo Bank Layout", "generic_mn"))
		assert params.get("si.employee_rate", dt.date(2026, 3, 1)).as_decimal() == Decimal("0.095")
	assert not guard.is_simulation()


def test_guard_accepts_every_rule_shape(seeded):
	"""The evals harness passes a core PatternSpec; the pipeline a document; period checks a name."""
	spec = patterns.load("purchase_expense_vat_payer")
	with pytest.raises(guard.UnverifiedRuleError, match="purchase_expense_vat_payer"):
		guard.require_verified(spec)
	with pytest.raises(guard.UnverifiedRuleError, match="purchase_expense_vat_payer"):
		guard.require_verified(frappe.get_doc("Nyabo Posting Pattern", "purchase_expense_vat_payer"))
	with pytest.raises(guard.UnverifiedRuleError, match="purchase_expense_vat_payer"):
		guard.require_verified(("Nyabo Posting Pattern", "purchase_expense_vat_payer"))
	with pytest.raises(guard.UnverifiedRuleError, match="purchase_expense_vat_payer"):
		guard.require_verified("purchase_expense_vat_payer")
	verified_spec = patterns.load("sale_cash_vat_payer")
	assert verified_spec.verified
	guard.require_verified(
		verified_spec,
		frappe.get_doc("Nyabo Posting Pattern", "sale_cash_vat_payer"),
		("Nyabo Posting Pattern", "sale_cash_vat_payer"),
		"sale_cash_vat_payer",
		[params.get("retention.years", dt.date(2026, 1, 1))],
	)


def test_posting_context_follows_a_regime_switch(company_v03):
	assert regime.history(company_v03) == [("vat_payer", dt.date(2026, 1, 1), None)]
	regime.set_regime(company_v03, regime.REGIME_SIMPLIFIED, "2027-01-01", note="орлого 400 сая-с доош")
	assert regime.history(company_v03) == [
		("vat_payer", dt.date(2026, 1, 1), dt.date(2026, 12, 31)),
		("simplified_1pct", dt.date(2027, 1, 1), None),
	]
	before = regime.posting_context(company_v03, "2026-12-31")
	after = regime.posting_context(company_v03, dt.date(2027, 1, 1))
	assert before.regime is Regime.VAT_PAYER and before.is_vat_payer and before.input_vat_recoverable
	assert before.summary_kind == "vat_monthly"
	assert (
		after.regime is Regime.SIMPLIFIED_1PCT and not after.is_vat_payer and not after.input_vat_recoverable
	)
	assert after.summary_kind == "simplified_quarterly" and after.effective_from == dt.date(2027, 1, 1)
	with pytest.raises(MissingRuleError):
		regime.posting_context(company_v03, "2025-06-01")
	# same regime and start twice is a no-op
	regime.set_regime(company_v03, regime.REGIME_SIMPLIFIED, "2027-01-01")
	assert len(regime.history(company_v03)) == 2


def test_company_settings_validate_contiguous_regimes_and_expense_code(company_v03):
	settings = frappe.get_doc("Nyabo Company Settings", company_v03)
	settings.append("regimes", {"regime": "simplified_1pct", "effective_from": "2027-01-01"})
	with pytest.raises(frappe.ValidationError, match="сүүлийн горим"):
		settings.save()
	settings.reload()
	settings.regimes[0].effective_to = "2026-12-31"
	settings.append("regimes", {"regime": "simplified_1pct", "effective_from": "2027-02-01"})
	with pytest.raises(frappe.ValidationError, match="завсар"):
		settings.save()
	settings.reload()
	settings.regimes[0].effective_to = "2026-12-31"
	settings.append("regimes", {"regime": "simplified_1pct", "effective_from": "2026-12-01"})
	with pytest.raises(frappe.ValidationError, match="давхцаж"):
		settings.save()
	settings.reload()
	settings.default_expense_code = "9999"
	with pytest.raises(frappe.ValidationError, match="9999"):
		settings.save()
	settings.reload()
	settings.default_expense_code = "6910"  # V1 alias -> 7090 in the v0.3 chart
	settings.save()
	with pytest.raises(frappe.ValidationError, match="горим байхгүй"):
		regime.set_regime(company_v03, "flat_tax", "2028-01-01")


def test_patterns_select_delegates_to_core(seeded):
	ctx_vat = regime.regime_on([("vat_payer", "2026-01-01", None)], dt.date(2026, 5, 1))
	ctx_simple = regime.regime_on([("simplified_1pct", "2026-01-01", None)], dt.date(2026, 5, 1))
	assert patterns.select("purchase_invoice", ctx_vat, {"family": "purchase_expense"}).pattern_id == (
		"purchase_expense_vat_payer"
	)
	assert patterns.select("Purchase Invoice", ctx_simple, {"family": "purchase_expense"}).pattern_id == (
		"purchase_expense_non_vat"
	)
	assert (
		patterns.select("journal_entry", ctx_simple, {"family": "bank_fee"}).pattern_id == "bank_fee_expense"
	)
	assert patterns.load("bank_fee_expense").lines[0].selector == "role:bank_fee"
	assert len(patterns.load_all()) == frappe.db.count("Nyabo Posting Pattern")
	with pytest.raises(Exception, match="no-such-pattern"):
		patterns.load("no-such-pattern")
