"""The simulator prints two regime columns for the fuel receipt (snapshot) and cleans up after itself."""

from __future__ import annotations

from pathlib import Path

import pytest

from nyabo_mn.simulator import run as sim

SNAPSHOT = Path(__file__).resolve().parents[1] / "fixtures" / "golden" / "simulator_petrovis_fuel.txt"


def test_fuel_receipt_snapshot_off_site():
	text = sim.simulate_receipt("petrovis_fuel", print_output=False, use_site=False)
	expected = SNAPSHOT.read_text(encoding="utf-8").rstrip("\n")
	assert text == expected, (
		"simulator output changed; update tests/fixtures/golden/simulator_petrovis_fuel.txt if intended"
	)


def test_snapshot_shows_both_entries_with_citations():
	text = SNAPSHOT.read_text(encoding="utf-8")
	assert "Худалдан авалтын нэхэмжлэх" in text and "Ерөнхий журналын бичилт" in text
	assert "Дт 1810" in text and "77 272.73" in text and "85 000" in text
	assert text.count("Заавар 116 (2000)") == 2 and text.count("Нягтлан батална") == 2
	assert "НӨАТ: суутгана" in text and "НӨАТ: зардалд орно" in text


def test_load_case_prefers_extraction_then_classification_then_path(tmp_path):
	assert sim.load_case("petrovis_fuel").kind == "extraction"
	assert sim.load_case("classify_taxi_simplified_1pct").kind == "classification"
	with pytest.raises(LookupError):
		sim.load_case("no_such_case")
	path = tmp_path / "case.json"
	path.write_text(sim.GOLDEN_DIR.joinpath("fx.json").read_text(encoding="utf-8"), encoding="utf-8")
	assert sim.load_case(path).kind == "fx"


def test_run_entry_point_prints(site, capsys):
	text = sim.run("taxi")
	out = capsys.readouterr().out
	assert text in out and "Юу Би Каб" in text
	assert sim.simulate_receipt("taxi", print_output=False, use_site=False) == text


def test_on_the_stub_sim_companies_are_provisioned_and_cleaned(site):
	import frappe

	text = sim.simulate_receipt("nomin_supermarket", print_output=False)
	assert frappe.flags.nyabo_simulation is True
	assert "6510" in text
	assert not frappe.db.exists("Company", "SIM-vat_payer") and not frappe.db.exists(
		"Company", "SIM-simplified_1pct"
	)
	assert (
		frappe.db.count("Nyabo Proposal") == 0
		and frappe.db.count("Account", {"company": "SIM-vat_payer"}) == 0
	)


def test_keep_companies_leaves_the_proposals_for_inspection(site):
	import frappe

	sim.simulate_receipt("nomin_supermarket", print_output=False, keep_companies=True)
	assert frappe.db.exists("Company", "SIM-vat_payer")
	proposals = frappe.get_all("Nyabo Proposal", fields=["company", "vat_treatment", "needs_accountant"])
	assert {(p.company, p.vat_treatment) for p in proposals} == {
		("SIM-vat_payer", "withheld"),
		("SIM-simplified_1pct", "in_expense"),
	}
	assert all(p.needs_accountant == 1 for p in proposals)  # seed patterns are unverified
	assert sim.cleanup_sim_company("SIM-vat_payer") == []
	assert not frappe.db.exists("Company", "SIM-vat_payer")


def test_statement_simulation_from_csv(tmp_path):
	path = tmp_path / "khan.csv"
	path.write_text(
		"Огноо,Гүйлгээний утга,Дебит,Кредит,Үлдэгдэл\n"
		"2026-06-15,Гүйлгээний шимтгэл,1000,,99000\n"
		"2026-06-16,Петровис ХХК шатахуун,85000,,14000\n"
		"2026-06-17,Хэрэглэгч ХХК төлбөр,,1200000,1214000\n",
		encoding="utf-8",
	)
	text = sim.simulate_statement(path, print_output=False)
	assert "khan.csv" in text
	assert text.count("→") == 3 and "банкны хураамж" in text and "тохирох баримт олдсонгүй" in text
