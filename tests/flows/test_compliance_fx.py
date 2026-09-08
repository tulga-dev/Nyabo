"""Mongolbank rate import: parsing the observed JSON shape, idempotent Currency Exchange rows, CSV entry point."""

from __future__ import annotations

from decimal import Decimal

import frappe
import pytest
from erpnext.setup.utils import get_exchange_rate

from nyabo_mn.compliance import fx_rates
from nyabo_mn.i18n import mn

PAYLOAD = {
	"success": True,
	"data": [
		{
			"RATE_DATE": "2026-09-01",
			"USD": "3,595.21",
			"EUR": "4,168.83",
			"XAU": "15,891,691.05",
			"SDR": "4,921.40",
		},
		{
			"RATE_DATE": "2026-09-02",
			"USD": "3,594.29",
			"EUR": "4,161.47",
			"XAU": "15,539,463.53",
			"SDR": "4,918.28",
		},
	],
}


def test_parse_mongolbank_json_skips_metals_and_parses_thousands():
	rows = fx_rates.parse_mongolbank_json(PAYLOAD)
	assert [(r["date"].isoformat(), r["currency"], r["rate"]) for r in rows] == [
		("2026-09-01", "USD", Decimal("3595.21")),
		("2026-09-01", "EUR", Decimal("4168.83")),
		("2026-09-02", "USD", Decimal("3594.29")),
		("2026-09-02", "EUR", Decimal("4161.47")),
	]
	assert fx_rates.parse_mongolbank_json({"success": False, "data": []}) == []
	with pytest.raises(ValueError):
		fx_rates.parse_mongolbank_json({"success": True, "data": [{"RATE_DATE": "2026-09-01", "USD": "n/a"}]})


def test_import_rates_is_idempotent_and_feeds_get_exchange_rate(site):
	rows = fx_rates.parse_mongolbank_json(PAYLOAD)
	assert fx_rates.import_rates(rows) == 2  # EUR is not a Currency on this site
	assert fx_rates.import_rates(rows) == 0
	assert frappe.db.count("Currency Exchange") == 2
	doc = frappe.get_doc("Currency Exchange", "2026-09-01-USD-MNT")
	assert (doc.for_buying, doc.for_selling, doc.to_currency) == (1, 1, "MNT")
	assert get_exchange_rate("USD", "MNT", "2026-09-01") == 3595.21
	assert get_exchange_rate("USD", "MNT", "2026-09-05") == 3594.29
	assert frappe.db.exists("Nyabo Event", {"event_type": mn.EVENT_FX_RATES_IMPORTED})


def test_fetch_is_refused_without_the_site_flag(site):
	assert fx_rates.fetch_enabled() is False
	with pytest.raises(frappe.ValidationError) as exc:
		fx_rates.fetch_mongolbank("2026-09-01", "2026-09-02")
	assert mn.MSG_FX_FETCH_DISABLED in str(exc.value)


def test_import_csv_entry_point(site, tmp_path, capsys):
	path = tmp_path / "rates.csv"
	path.write_text('date,currency,rate\n2026-09-03,usd,"3,595.32"\n2026-09-03,MNT,1\n', encoding="utf-8")
	assert fx_rates.import_csv(str(path)) == 1
	assert "1" in capsys.readouterr().out
	assert get_exchange_rate("USD", "MNT", "2026-09-03") == 3595.32
