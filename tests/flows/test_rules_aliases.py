"""rules.aliases: V1 -> v0.3 aliases, roles, identity for chart codes, refusal of null roles."""

from __future__ import annotations

import frappe
import pytest

from nyabo_mn.core.rules_engine import MissingRuleError
from nyabo_mn.rules import aliases
from nyabo_mn.setup.chart import ChartError


def test_v1_codes_resolve_to_v03_accounts(company_v03):
	assert aliases.chart_scheme(company_v03) == "v03"
	assert aliases.resolve_code(company_v03, "6210") == "7003"
	assert aliases.resolve_code(company_v03, "1810") == "1210"
	assert aliases.account_for(company_v03, "6210") == "7003 - Шатахуун - GUR"
	assert aliases.account_for(company_v03, "role:input_vat") == "1210 - НӨАТ-ын авлага - GUR"
	assert aliases.account_for(company_v03, "role:bank_fee").startswith("7012")
	# a code that exists in the installed chart is that account, even though V1 also had a 6110
	assert aliases.resolve_code(company_v03, "6110") == "6110"
	assert (
		aliases.account_for(company_v03, "role:stock_adjustment")
		== "6110 - Бараа материалын тохируулга - GUR"
	)
	assert (
		aliases.resolve_code(company_v03, "9999") == "9999"
	)  # identity: nothing known, chart_db refuses later
	with pytest.raises(ChartError):
		aliases.account_for(company_v03, "9999")
	assert frappe.db.count("Nyabo Account Alias", {"company": company_v03, "scheme": "v1"}) == 40
	alias = frappe.get_doc("Nyabo Account Alias", f"{company_v03}:v1:6210")
	assert alias.target_account == "7003 - Шатахуун - GUR"
	assert aliases.resolver(company_v03)("role:cash") == "1001"


def test_v1_company_keeps_identity_and_v1_roles(company):
	assert aliases.chart_scheme(company) == "v1"
	assert aliases.resolve_code(company, "6210") == "6210"
	assert aliases.account_for(company, "role:bank") == "1120 - Банкны харилцах данс - TST"
	with pytest.raises(MissingRuleError) as excinfo:
		aliases.resolve_code(company, "role:si_payable")  # D-013: V1 has no SI payable leaf
	assert "si_payable" in excinfo.value.message_mn


def test_alias_controller_checks_the_target_exists(company_v03):
	with pytest.raises(frappe.ValidationError, match="8888"):
		frappe.get_doc(
			{
				"doctype": "Nyabo Account Alias",
				"company": company_v03,
				"scheme": "accountant",
				"alias_code": "1",
				"target_code": "8888",
			}
		).insert()
	name = aliases.upsert_alias(company_v03, "accountant", "1", "7003")
	assert name == f"{company_v03}:accountant:1"
	assert aliases.resolve_code(company_v03, "1", scheme="accountant") == "7003"
	assert aliases.alias_target(company_v03, "1", scheme="v1") is None
