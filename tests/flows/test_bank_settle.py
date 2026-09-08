"""An unpaid invoice is settled by a Payment Entry, never by a bare allocation.

ERPNext's ``Bank Transaction.add_payment_entries`` / ``allocate_payment_entries`` only
record a link and stamp a clearance date; they post nothing. Allocating an unpaid invoice
would therefore leave the supplier payable open and the bank overstated for good, which is
why ``matching.match.reconcile`` refuses it and ``settle`` creates the Payment Entry the
accountant taps for (DECISIONS BANK-08, BANK-09, COMP-10).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from frappe.utils import getdate

from nyabo_mn.core import dates
from nyabo_mn.i18n import mn
from nyabo_mn.matching import bank_import, cards, match, rules
from nyabo_mn.telegram import api
from tests.fixtures.statements import make_fixtures as fixtures
from tests.fixtures.telegram import fake_bot
from tests.flows import bank_helpers as helpers

ACCOUNTANT = "acc@example.com"
ACCOUNTANT_ROLES = ["Nyabo Accountant", "Accounts User"]
OWNER = "owner@example.com"


@pytest.fixture
def books(company, frappe_hooks):
	with frappe_hooks(without_apps=("nyabo_mn",)):
		yield company


@pytest.fixture
def banks(books):
	helpers.register_layouts()
	helpers.ensure_role("Accounts User")  # ERPNext's own role; the Payment Entry permission table names it
	return helpers.setup_banks(books)


@pytest.fixture
def guarded_books(company):
	"""The same site with Nyabo's own doc_events left on (nyabo_mn/hooks.py)."""
	helpers.register_layouts()
	helpers.ensure_role("Accounts User")
	return company, helpers.setup_banks(company)


def _import(company: str, builder) -> dict:
	filename, data = builder()
	return bank_import.import_statement(helpers.statement_document(company, filename, data))


def _bt(**filters):
	import frappe

	name = frappe.db.get_value("Bank Transaction", filters, "name")
	assert name, filters
	return frappe.get_doc("Bank Transaction", name)


def _payable(company: str) -> str:
	import frappe

	return frappe.get_cached_value("Company", company, "default_payable_account")


def _other_company() -> str:
	from nyabo_mn.setup.provision_company import provision_company

	name = "Хоёр ХХК"
	provision_company(name, "HOY", vat_registered=0)
	return name


def test_unpaid_purchase_invoice_cannot_be_reconciled(books, banks):
	"""reconcile() refuses the invoice and leaves the statement line untouched."""
	import frappe

	pi = helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01")
	assert frappe.db.get_value("Purchase Invoice", pi.name, "status") == "Unpaid"
	assert match.settlement_needed("Purchase Invoice", pi.name) is True

	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	assert bt.status == "Unreconciled"
	with pytest.raises(match.MatchError) as info:
		match.reconcile(bt.name, "Purchase Invoice", pi.name, ACCOUNTANT)
	assert info.value.message_mn == mn.MSG_BANK_NEEDS_PAYMENT_ENTRY.format(
		doctype="Purchase Invoice", name=pi.name
	)
	bt.reload()
	assert bt.status == "Unreconciled" and not bt.payment_entries
	assert float(bt.unallocated_amount) == 93500.0
	assert frappe.db.count("Payment Entry") == 0
	# The invoice is not a bank-GL candidate at all; it is a settlement candidate.
	assert match.candidates_for(books, banks["khan_gl"], direction=-1) == []
	candidate = match.settlement_candidate(bt.name)
	assert candidate is not None and (candidate.doctype, candidate.name) == ("Purchase Invoice", pi.name)


def test_settle_creates_a_payment_entry_that_clears_the_payable(books, banks, as_user):
	"""The payable returns to zero, the bank is credited and the line ends Reconciled."""
	import frappe
	from erpnext.accounts.utils import get_balance_on

	pi = helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01")
	payable = _payable(books)
	assert get_balance_on(payable, party_type="Supplier", party="Петровис ХХК") == -93500.0

	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	bank_before = get_balance_on(banks["khan_gl"])
	with as_user(ACCOUNTANT, ACCOUNTANT_ROLES) as user:
		result = match.settle(bt.name, "Purchase Invoice", pi.name, user, telegram_id="2002")

	assert result["voucher_doctype"] == "Purchase Invoice" and result["voucher_name"] == pi.name
	assert result["allocated"] == "93500.00"
	payment = frappe.get_doc("Payment Entry", result["payment_entry"])
	assert int(payment.docstatus) == 1 and payment.payment_type == "Pay"
	assert str(payment.posting_date) == "2026-09-02" and payment.party == "Петровис ХХК"
	assert payment.paid_from == banks["khan_gl"] and payment.paid_to == payable
	assert payment.bank_account == banks["khan"] and payment.reference_no
	assert [(r.reference_doctype, r.reference_name, r.allocated_amount) for r in payment.references] == [
		("Purchase Invoice", pi.name, 93500.0)
	]

	# The payable nets to zero and the bank carries the credit.
	assert get_balance_on(payable, party_type="Supplier", party="Петровис ХХК") == 0.0
	assert get_balance_on(banks["khan_gl"]) == bank_before - 93500.0
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 0.0
	assert frappe.db.get_value("Purchase Invoice", pi.name, "status") == "Paid"

	bt.reload()
	assert bt.status == "Reconciled" and float(bt.unallocated_amount) == 0.0
	assert [(p.payment_document, p.payment_entry) for p in bt.payment_entries] == [
		("Payment Entry", payment.name)
	]
	assert str(frappe.db.get_value("Payment Entry", payment.name, "clearance_date")) == "2026-09-02"

	events = frappe.get_all(
		"Nyabo Event",
		filters={"event_type": "bank_line_settled", "ref_name": bt.name},
		fields=["actor_user", "actor_telegram_id", "payload_json"],
	)
	assert len(events) == 1 and events[0].actor_user == ACCOUNTANT
	payload = json.loads(events[0].payload_json)
	assert payload["payment_entry"] == payment.name and payload["voucher_name"] == pi.name
	assert payload["outstanding_before"] == "93500.00" and payload["outstanding_after"] == "0.00"

	# A settled line is spent: a second tap is refused.
	with pytest.raises(match.MatchError) as info:
		match.settle(bt.name, "Purchase Invoice", pi.name, "Administrator")
	assert info.value.message_mn == mn.MSG_BANK_SETTLE_NOT_NEEDED.format(
		doctype="Purchase Invoice", name=pi.name
	)


def test_partial_line_allocates_the_smaller_amount(books, banks, as_user):
	"""A statement line smaller than the invoice pays part of it; the rest stays outstanding."""
	import frappe
	from erpnext.accounts.utils import get_balance_on

	pi = helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 150000, "2026-09-01")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	with as_user(ACCOUNTANT, ACCOUNTANT_ROLES) as user:
		result = match.settle(bt.name, "Purchase Invoice", pi.name, user)

	assert result["allocated"] == "93500.00"
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 56500.0
	assert frappe.db.get_value("Purchase Invoice", pi.name, "status") == "Unpaid"
	assert get_balance_on(_payable(books), party_type="Supplier", party="Петровис ХХК") == -56500.0
	bt.reload()
	assert bt.status == "Reconciled" and float(bt.unallocated_amount) == 0.0
	assert match.settlement_needed("Purchase Invoice", pi.name) is True


def test_over_allocation_is_refused(books, banks, as_user):
	"""A line bigger than what the invoice owes is refused instead of parked as an advance."""
	import frappe

	pi = helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 50000, "2026-09-01")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	with as_user(ACCOUNTANT, ACCOUNTANT_ROLES) as user, pytest.raises(match.MatchError) as info:
		match.settle(bt.name, "Purchase Invoice", pi.name, user)
	assert info.value.message_mn == mn.MSG_BANK_SETTLE_OVER_ALLOCATION.format(
		name=pi.name, outstanding="50000.00", amount="93500.00"
	)
	assert frappe.db.count("Payment Entry") == 0
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 50000.0
	bt.reload()
	assert bt.status == "Unreconciled" and not bt.payment_entries


def test_automatic_run_never_creates_a_payment_entry(books, banks):
	"""ARCHITECTURE §1.3: a posting needs a tap, so the line stays unmatched with a card."""
	import frappe

	pi = helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01")
	summary = _import(books, fixtures.khan_xlsx)

	assert frappe.db.count("Payment Entry") == 0
	assert summary["matched"] == 0
	assert summary["match"]["unmatched"] == 4 and summary["match"]["settlement_offered"] == 1
	line = _bt(withdrawal=93500.0)
	assert line.status == "Unreconciled" and not line.payment_entries

	# A re-run over the same statement is just as inert, and names the candidate it will not post.
	stats = match.run(books, banks["khan"], send_cards=False)
	assert frappe.db.count("Payment Entry") == 0 and stats["matched"] == 0
	detail = next(d for d in stats["details"] if d["name"] == line.name)
	assert detail["kind"] == "none" and detail["settlement_candidate"] == f"Purchase Invoice {pi.name}"
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 93500.0

	# The card names the invoice and offers the settlement tap.
	text, proposal = cards.render_bank_line(line.name)
	assert proposal is None and mn.CARD_BANK_UNMATCHED in text
	assert pi.name in text and mn.CARD_BANK_SETTLE_HINT.split(":")[0] in text


def test_find_candidates_offers_the_unpaid_invoice(books, banks):
	"""[Баримт хайх] still finds the invoice; it is flagged as needing settlement."""
	pi = helpers.unpaid_purchase_invoice(books, "Хос ХХК", 50000, "2026-08-20")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=50000.0)
	found = match.find_candidates(bt.name, "Хос")
	assert found and (found[0]["voucher_doctype"], found[0]["voucher_name"]) == ("Purchase Invoice", pi.name)
	assert found[0]["needs_settlement"] is True
	# The paid invoice of the same company is offered without the flag.
	paid = helpers.paid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01", banks["khan_gl"])
	other = match.find_candidates(_bt(withdrawal=93500.0).name, "Петровис")
	assert other and other[0]["voucher_name"] == paid.name and other[0]["needs_settlement"] is False


def test_settle_is_refused_for_an_owner(books, banks, as_user):
	"""A Payment Entry posts to the ledger, so the owner's tap is refused (§5.3 step 7)."""
	import frappe

	pi = helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	with as_user(OWNER, ["Nyabo Owner"]) as owner:
		frappe.get_doc(
			{
				"doctype": "Nyabo User Link",
				"telegram_id": "700501",
				"user": owner,
				"role": "Owner",
				"status": "active",
				"companies": [{"company": books}],
			}
		).insert(ignore_permissions=True)
	with as_user(OWNER, ["Nyabo Owner"]) as user, pytest.raises(match.MatchError) as info:
		match.settle(bt.name, "Purchase Invoice", pi.name, user)
	assert info.value.message_mn == mn.MSG_ACCOUNTANT_ONLY
	assert frappe.db.count("Payment Entry") == 0


# --- the Telegram tap ---------------------------------------------------------------------------


def test_accountant_taps_the_settlement_button(books, banks):
	"""The card carries [Төлбөр бүртгэх]; the tap answers with the Payment Entry it created."""
	import frappe

	from nyabo_mn.telegram.handlers import bank as bank_handler

	pi = helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	user = str(fake_bot.link_user(8101, "Accountant", books).user)

	bot = fake_bot.FakeBotApi()
	with api.use_bot(bot):
		bank_handler.send_bank_card(bot, 8101, bt.name)
	assert bot.callback_datas() == [
		f"b:{bt.name}:st:pi:{pi.name}",
		f"b:{bt.name}:find",
		f"b:{bt.name}:exp",
		f"b:{bt.name}:later",
	]
	assert pi.name in bot.last_text

	outcome = fake_bot.run(bot, fake_bot.callback_update(8101, f"b:{bt.name}:st:pi:{pi.name}", message_id=71))
	payment = frappe.get_value("Payment Entry", {"docstatus": 1}, "name")
	assert outcome["result"] == {"payment_entry": payment, "voucher_name": pi.name}
	assert bot.sent("edit_message_text")[-1]["text"] == mn.MSG_BANK_SETTLED.format(
		payment=payment, voucher=pi.name
	)
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 0.0
	assert frappe.get_doc("Bank Transaction", bt.name).status == "Reconciled"
	assert frappe.db.count("Nyabo Event", {"event_type": "bank_line_settled"}) == 1
	assert frappe.db.get_value("Nyabo Event", {"event_type": "bank_line_settled"}, "actor_user") == user


def test_the_find_flow_offers_the_settlement_tap(books, banks):
	"""[Баримт хайх] onto an unpaid invoice explains and offers the tap instead of failing."""
	import frappe

	from nyabo_mn.telegram.handlers import bank as bank_handler

	pi = helpers.unpaid_purchase_invoice(books, "Хос ХХК", 50000, "2026-08-20")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=50000.0)
	fake_bot.link_user(8102, "Accountant", books)

	bot = fake_bot.FakeBotApi()
	with api.use_bot(bot):
		bank_handler.send_bank_card(bot, 8102, bt.name)
	fake_bot.run(bot, fake_bot.callback_update(8102, f"b:{bt.name}:find", message_id=72))
	fake_bot.run(bot, fake_bot.message_update(8102, "Хос"))
	assert pi.name in bot.last_text
	assert bot.callback_datas().index(f"b:{bt.name}:m:0") == 0
	outcome = fake_bot.run(bot, fake_bot.callback_update(8102, f"b:{bt.name}:m:0", message_id=73))
	assert outcome["result"] == {"needs_settlement": pi.name}
	assert bot.last_text == mn.MSG_BANK_NEEDS_PAYMENT_ENTRY.format(doctype="Purchase Invoice", name=pi.name)
	assert bot.callback_datas() == [f"b:{bt.name}:st:pi:{pi.name}", f"b:{bt.name}:later"]
	assert frappe.db.count("Payment Entry") == 0

	outcome = fake_bot.run(bot, fake_bot.callback_update(8102, f"b:{bt.name}:st:pi:{pi.name}", message_id=73))
	assert outcome["result"]["voucher_name"] == pi.name
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 0.0


def test_the_tap_is_refused_for_an_owner_and_for_another_company(books, banks):
	"""The callback re-checks the line's company and the accountant role; neither may post."""
	import frappe

	pi = helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	data = f"b:{bt.name}:st:pi:{pi.name}"

	fake_bot.link_user(8103, "Owner", books)
	bot = fake_bot.FakeBotApi()
	outcome = fake_bot.run(bot, fake_bot.callback_update(8103, data, message_id=74))
	assert outcome["result"] == {"refused": "permission"}
	assert bot.sent("answer_callback_query")[-1]["text"] == mn.MSG_ACCOUNTANT_ONLY
	assert frappe.db.count("Payment Entry") == 0

	other_company = _other_company()
	fake_bot.link_user(8104, "Accountant", other_company)
	bot.clear()
	outcome = fake_bot.run(bot, fake_bot.callback_update(8104, data, message_id=75))
	assert outcome["result"] is None
	assert bot.sent("answer_callback_query")[-1]["text"] == mn.MSG_NO_PERMISSION
	assert frappe.db.count("Payment Entry") == 0


# --- one test per verified problem the first attempt had -----------------------------------------


def test_another_company_s_invoice_is_refused_before_erpnext_is_reached(books, banks, as_user):
	"""S1 / S12: the invoice's company must be the statement line's, or nothing is built.

	Without the check ``get_payment_entry`` builds a Payment Entry in the *other* company's
	books carrying this company's bank account; only ``submit`` notices, in English, and a
	docstatus-1 document with no GL behind it is left in the other company's ledger.
	"""
	import frappe

	other = _other_company()
	foreign = helpers.unpaid_purchase_invoice(other, "Петровис ХХК", 93500, "2026-09-01")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	with as_user(ACCOUNTANT, ACCOUNTANT_ROLES) as user, pytest.raises(match.MatchError) as info:
		match.settle(bt.name, "Purchase Invoice", foreign.name, user)
	assert info.value.message_mn == mn.MSG_BANK_VOUCHER_NOT_FOUND.format(
		doctype="Purchase Invoice", name=foreign.name
	)
	assert frappe.db.count("Payment Entry") == 0
	assert frappe.db.get_value("Purchase Invoice", foreign.name, "outstanding_amount") == 93500.0


def test_a_withdrawal_may_not_settle_a_sales_invoice(books, banks, as_user):
	"""S2 / S11: a withdrawal pays a Purchase Invoice, a deposit collects a Sales Invoice.

	The wrong pairing produced a Receive that DEBITED the bank for a line where money left
	it, and marked the line Reconciled - double the overstatement this change removes.
	"""
	import frappe

	si = helpers.unpaid_sales_invoice(books, "Хэрэглэгч ХХК", 93500, "2026-09-01")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	with as_user(ACCOUNTANT, ACCOUNTANT_ROLES) as user, pytest.raises(match.MatchError) as info:
		match.settle(bt.name, "Sales Invoice", si.name, user)
	assert info.value.message_mn == mn.MSG_BANK_SETTLE_WRONG_DIRECTION.format(
		doctype="Sales Invoice", name=si.name
	)
	assert frappe.db.count("Payment Entry") == 0
	bt.reload()
	assert bt.status == "Unreconciled"


def test_a_deposit_may_not_settle_a_purchase_invoice(books, banks, as_user):
	"""S11, the mirror case: a deposit line tapped against a payable moved the bank down."""
	import frappe

	pi = helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 1250000, "2026-09-01")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(deposit=1250000.0)
	with as_user(ACCOUNTANT, ACCOUNTANT_ROLES) as user, pytest.raises(match.MatchError) as info:
		match.settle(bt.name, "Purchase Invoice", pi.name, user)
	assert info.value.message_mn == mn.MSG_BANK_SETTLE_WRONG_DIRECTION.format(
		doctype="Purchase Invoice", name=pi.name
	)
	assert frappe.db.count("Payment Entry") == 0
	# The candidate scan never offered it either.
	assert match.settlement_candidate(bt.name) is None


def test_a_deposit_settles_a_sales_invoice_and_is_a_receive(books, banks, as_user):
	"""The direction that IS allowed: an inflow collects a receivable with a Receive entry."""
	import frappe
	from erpnext.accounts.utils import get_balance_on

	si = helpers.unpaid_sales_invoice(books, "Хэрэглэгч ХХК", 1250000, "2026-09-01")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(deposit=1250000.0)
	bank_before = get_balance_on(banks["khan_gl"])
	with as_user(ACCOUNTANT, ACCOUNTANT_ROLES) as user:
		result = match.settle(bt.name, "Sales Invoice", si.name, user)
	payment = frappe.get_doc("Payment Entry", result["payment_entry"])
	assert payment.payment_type == "Receive" and payment.paid_to == banks["khan_gl"]
	assert get_balance_on(banks["khan_gl"]) == bank_before + 1250000.0
	assert frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount") == 0.0


def test_a_line_a_proposal_already_posted_may_not_also_be_settled(books, banks, as_user):
	"""S10: one statement line, one credit to the bank.

	A posted bank_line proposal used to leave the line looking untouched (the lookup asked
	for status "proposed" only), so it was re-carded, the settlement button was offered and
	the bank was credited a second time for the same 93,500₮.
	"""
	import frappe
	from erpnext.accounts.utils import get_balance_on

	from nyabo_mn.agent import post
	from tests.flows.conftest import seed_patterns

	pi = helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	proposal = match.propose_expense(bt.name, "6210", "Administrator")
	# The seed pattern ships unverified; an admin verifies the row in the desk before it posts.
	seed_patterns(verified=True, only=(rules.EXPENSE_PATTERN_ID,))
	post.post_proposal(proposal, "Administrator")
	after_proposal = get_balance_on(banks["khan_gl"])

	assert rules.existing_proposal(bt.name) == proposal
	assert match.settlement_candidate(bt.name) is None
	stats = match.run(books, banks["khan"], send_cards=False)
	assert stats["skipped_proposed"] >= 1
	with as_user(ACCOUNTANT, ACCOUNTANT_ROLES) as user, pytest.raises(match.MatchError) as info:
		match.settle(bt.name, "Purchase Invoice", pi.name, user)
	assert info.value.message_mn == mn.MSG_BANK_SETTLE_ALREADY_PROPOSED.format(proposal=proposal)
	assert frappe.db.count("Payment Entry") == 0
	assert get_balance_on(banks["khan_gl"]) == after_proposal


def test_a_foreign_currency_invoice_is_neither_offered_nor_settled(books, banks, as_user):
	"""S13: outstanding_amount is in the invoice's currency, the line's amount in the bank's.

	Comparing them across currencies made a 93,500 USD invoice a candidate for a 93,500₮
	withdrawal and allocated 93,500 against it.
	"""
	import frappe

	usd = helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01", currency="USD")
	assert frappe.db.get_value("Purchase Invoice", usd.name, "currency") == "USD"
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)

	assert match.settlement_candidate(bt.name) is None
	assert all(c["voucher_name"] != usd.name for c in match.find_candidates(bt.name, "Петровис"))
	with as_user(ACCOUNTANT, ACCOUNTANT_ROLES) as user, pytest.raises(match.MatchError) as info:
		match.settle(bt.name, "Purchase Invoice", usd.name, user)
	assert info.value.message_mn.startswith(mn.MSG_BANK_SETTLE_CURRENCY_MISMATCH.split(":")[0])
	assert frappe.db.count("Payment Entry") == 0


def test_a_reversed_invoice_is_no_settlement_candidate(books, banks, as_user):
	"""S16: a debit note voids the invoice, so settling it would leave a phantom prepayment."""
	import frappe

	from nyabo_mn.compliance import reversal

	pi = helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	reversal.reverse("Purchase Invoice", pi.name, "amount", "буруу дүн", "Administrator")

	assert match.settlement_needed("Purchase Invoice", pi.name) is False
	assert match.settlement_candidate(bt.name) is None
	assert all(c.name != pi.name for c in match.open_invoice_candidates(books, direction=-1))
	with as_user(ACCOUNTANT, ACCOUNTANT_ROLES) as user, pytest.raises(match.MatchError) as info:
		match.settle(bt.name, "Purchase Invoice", pi.name, user)
	assert info.value.message_mn == mn.MSG_BANK_SETTLE_REVERSED.format(
		doctype="Purchase Invoice", name=pi.name
	)
	assert frappe.db.count("Payment Entry") == 0


def test_a_closed_period_is_refused_in_mongolian(books, banks, as_user):
	"""S15: the same MSG_POSTING_IN_CLOSED_PERIOD every other posting path gives."""
	import frappe

	from nyabo_mn.agent.post import ClosedPeriodError

	pi = helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	frappe.get_doc(
		{
			"doctype": "Accounting Period",
			"period_name": "2026-09a",
			"company": books,
			"start_date": "2026-09-01",
			"end_date": "2026-09-07",
			"closed_documents": [
				{"document_type": dt, "closed": 1}
				for dt in ("Journal Entry", "Purchase Invoice", "Sales Invoice", "Payment Entry")
			],
		}
	).insert(ignore_permissions=True)

	with as_user(ACCOUNTANT, ACCOUNTANT_ROLES) as user, pytest.raises(ClosedPeriodError) as info:
		match.settle(bt.name, "Purchase Invoice", pi.name, user)
	assert info.value.message_mn == mn.MSG_POSTING_IN_CLOSED_PERIOD.format(
		date="2026-09-02", period=dates.period_label(dates.period_of(getdate("2026-09-02")))
	)
	assert frappe.db.count("Payment Entry") == 0


def _assert_a_failed_reconcile_leaves_no_payment_entry(books, banks, as_user, monkeypatch) -> None:
	"""The S3 invariant, asserted identically with and without Nyabo's own ``doc_events``."""
	import frappe
	from erpnext.accounts.utils import get_balance_on

	pi = helpers.unpaid_purchase_invoice(
		books, "Петровис ХХК", 93500, "2026-09-01", nyabo_primary_document_ref="Нэхэмжлэх PET-1"
	)
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	payable_before = get_balance_on(_payable(books), party_type="Supplier", party="Петровис ХХК")
	bank_before = get_balance_on(banks["khan_gl"])

	def boom(*args, **kwargs):
		raise frappe.ValidationError("reconcile exploded")

	monkeypatch.setattr(match, "reconcile", boom)
	with as_user(ACCOUNTANT, ACCOUNTANT_ROLES) as user, pytest.raises(frappe.ValidationError):
		match.settle(bt.name, "Purchase Invoice", pi.name, user)

	assert frappe.get_all("Payment Entry", filters={"docstatus": 1}) == []
	assert frappe.db.count("Payment Entry") == 0
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 93500.0
	assert get_balance_on(_payable(books), party_type="Supplier", party="Петровис ХХК") == payable_before
	assert get_balance_on(banks["khan_gl"]) == bank_before
	bt.reload()
	assert bt.status == "Unreconciled" and float(bt.unallocated_amount) == 93500.0
	# And the line is settleable again: the failure left nothing that blocks a retry.
	assert match.settlement_needed("Purchase Invoice", pi.name) is True


def test_a_failed_reconcile_leaves_no_payment_entry_behind(books, banks, as_user, monkeypatch):
	"""S3: insert + submit + reconcile are one unit; a failure in the last undoes the first two."""
	_assert_a_failed_reconcile_leaves_no_payment_entry(books, banks, as_user, monkeypatch)


def test_a_failed_reconcile_leaves_no_payment_entry_behind_under_the_guards(
	guarded_books, as_user, monkeypatch
):
	"""K3: the same invariant in the only configuration a site ever has — doc_events ACTIVE.

	``_discard_payment_entry`` cancels the Payment Entry and deletes it, but
	``_stamp_settlement`` has already written ``nyabo_explanation``, so
	``compliance.hooks.block_delete_of_posted`` refused the delete every single time. The
	cleanup's own broad ``except`` swallowed the refusal, and a failed settle left a cancelled
	Payment Entry in the books. The variant above could not see it: its fixture drops the hooks.
	"""
	books, banks = guarded_books
	_assert_a_failed_reconcile_leaves_no_payment_entry(books, banks, as_user, monkeypatch)


def test_a_bank_account_with_no_gl_account_is_refused(books, banks, as_user):
	"""S3: an empty GL account made get_payment_entry credit the company default bank."""
	import frappe

	pi = helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	frappe.db.set_value("Bank Account", banks["khan"], "account", None)

	with as_user(ACCOUNTANT, ACCOUNTANT_ROLES) as user, pytest.raises(match.MatchError) as info:
		match.settle(bt.name, "Purchase Invoice", pi.name, user)
	assert info.value.message_mn == mn.MSG_BANK_SETTLE_NO_BANK_ACCOUNT
	assert frappe.db.count("Payment Entry") == 0


def test_a_plainly_linked_accountant_can_tap_with_no_extra_role_grant(books, banks):
	"""S4: linking an Accountant is all the site does; the tap must work as that user.

	``state.ensure_frappe_user`` grants ERPNext's Accounts User (TG-05) and ``settle`` posts
	with ``ignore_permissions`` after its own check, like every other Nyabo posting path.
	"""
	import frappe

	pi = helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	link = fake_bot.link_user(8105, "Accountant", books)
	assert "Accounts User" in frappe.get_roles(link.user)

	previous = frappe.session.user
	frappe.set_user(link.user)
	try:
		result = match.settle(bt.name, "Purchase Invoice", pi.name, link.user, telegram_id="8105")
	finally:
		frappe.set_user(previous)
	assert frappe.db.get_value("Payment Entry", result["payment_entry"], "docstatus") == 1
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 0.0


def test_the_candidate_scan_is_two_queries_per_direction_not_one_per_invoice(books, banks, monkeypatch):
	"""S5: the scan was O(open invoices) per line, per card and per [Буцах] tap."""
	import frappe

	for index in range(12):
		helpers.unpaid_purchase_invoice(books, f"Нийлүүлэгч {index} ХХК", 10000 + index, "2026-09-01")
	_import(books, fixtures.khan_xlsx)

	calls = {"get_value": 0, "get_all": 0}
	real_get_value, real_get_all = frappe.db.get_value, frappe.get_all

	def counted_get_value(*args, **kwargs):
		calls["get_value"] += 1
		return real_get_value(*args, **kwargs)

	def counted_get_all(*args, **kwargs):
		calls["get_all"] += 1
		return real_get_all(*args, **kwargs)

	monkeypatch.setattr(frappe.db, "get_value", counted_get_value)
	monkeypatch.setattr(frappe, "get_all", counted_get_all)
	before = dict(calls)
	match.open_invoice_candidates(books, direction=-1, currency="MNT")
	# Two queries whatever the number of invoices: the rows, then the returns that void them.
	assert calls["get_all"] - before["get_all"] == 2
	assert calls["get_value"] - before["get_value"] == 0


def test_the_settlement_hint_and_button_never_suppress_a_card(books, banks, monkeypatch):
	"""S7: the hint is decoration; a failure inside the scan must not stop the card batch."""
	from nyabo_mn.telegram.handlers import bank as bank_handler

	helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)

	def boom(*args, **kwargs):
		raise RuntimeError("candidate scan exploded")

	monkeypatch.setattr(match, "settlement_candidate", boom)
	text, proposal = cards.render_bank_line(bt.name)
	assert proposal is None and mn.CARD_BANK_UNMATCHED in text

	bot = fake_bot.FakeBotApi()
	with api.use_bot(bot):
		bank_handler.send_bank_card(bot, 8106, bt.name)
	assert bot.callback_datas() == [f"b:{bt.name}:find", f"b:{bt.name}:exp", f"b:{bt.name}:later"]


def test_a_voucher_name_too_long_for_the_callback_never_suppresses_a_card(books, banks):
	"""K1: Telegram caps callback data at 64 bytes, and the card outranks the button.

	``keyboards.encode`` refuses a longer datum with ``CallbackDataTooLong``, and nothing on
	the import path caught it: ``settle_offer`` guards only the candidate scan and
	``_send_card`` only Telegram / settings errors. One renamed invoice therefore aborted the
	whole statement import, so every later line went uncarded too.
	"""
	import frappe

	from nyabo_mn.telegram import keyboards
	from nyabo_mn.telegram.handlers import bank as bank_handler

	# What a rename leaves behind on a real site; the series stays because ERPNext requires it.
	long_name = "ACC-PINV-2026-" + "9" * 50
	pi = helpers.unpaid_purchase_invoice(
		books, "Петровис ХХК", 93500, "2026-09-01", name=long_name, naming_series="ACC-PINV-.YYYY.-"
	)
	assert pi.name == long_name

	filename, data = fixtures.khan_xlsx()
	document = helpers.statement_document(books, filename, data)
	frappe.db.set_value("Nyabo Document", document, "telegram_chat_id", "8107")

	bot = fake_bot.FakeBotApi()
	with api.use_bot(bot):
		summary = bank_import.import_statement(document)

	bt = _bt(withdrawal=93500.0)
	# The invoice IS the settlement candidate, and its datum genuinely overflows the limit.
	candidate = match.settlement_candidate(bt.name)
	assert candidate is not None and candidate.name == long_name
	with pytest.raises(keyboards.CallbackDataTooLong):
		keyboards.encode(keyboards.PREFIX_BANK, bt.name, "st", "pi", long_name)

	# The import ran to the end and every unmatched line got its card.
	assert summary["match"]["settlement_offered"] == 1
	assert summary["match"]["cards_sent"] == summary["match"]["unmatched"] == 4

	bot.clear()
	with api.use_bot(bot):
		bank_handler.send_bank_card(bot, 8107, bt.name)
	assert bot.callback_datas() == [f"b:{bt.name}:find", f"b:{bt.name}:exp", f"b:{bt.name}:later"]
	assert long_name in bot.last_text  # the card still names the invoice the accountant needs
	# The find flow's own offer drops the same button rather than raising.
	assert keyboards.bank_settle(bt.name, "Purchase Invoice", long_name) == keyboards.empty_markup()


def test_a_settlement_carries_the_nyabo_compliance_trail(guarded_books, as_user):
	"""S14: a Payment Entry is a posting, so it comes under the same guards as the rest.

	Runs with Nyabo's own ``doc_events`` active (the other tests in this file drop them),
	because the point is exactly that the four handlers now fire for a Payment Entry.
	"""
	import frappe

	from nyabo_mn import hooks

	books, _banks = guarded_books
	pi = helpers.unpaid_purchase_invoice(
		books,
		"Петровис ХХК",
		93500,
		"2026-09-01",
		nyabo_primary_document_ref="Нэхэмжлэх PET-1",
	)
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	with as_user(ACCOUNTANT, ACCOUNTANT_ROLES) as user:
		result = match.settle(bt.name, "Purchase Invoice", pi.name, user)

	assert set(hooks.doc_events["Payment Entry"]) == {
		"validate",
		"before_submit",
		"before_update_after_submit",
		"on_trash",
	}
	payment = frappe.get_doc("Payment Entry", result["payment_entry"])
	assert payment.nyabo_explanation and pi.name in payment.nyabo_explanation
	assert payment.nyabo_approved_by == ACCOUNTANT
	assert payment.source_document and frappe.db.exists("Nyabo Document", payment.source_document)
	assert payment.nyabo_primary_document_ref == f"Purchase Invoice {pi.name}"
	assert str(payment.nyabo_retain_until) == "2036-09-02"

	# No edit after submit, and no delete once it is cancelled.
	payment.reference_no = "tampered"
	with pytest.raises(frappe.ValidationError):
		payment.save()
	payment.reload()
	payment.flags.ignore_permissions = True
	payment.cancel()
	with pytest.raises(frappe.ValidationError):
		frappe.delete_doc("Payment Entry", payment.name, ignore_permissions=True)


def _desk_payment_entry(company: str, bank_gl: str, invoice: str) -> Any:
	"""What the desk, the Bank Reconciliation Tool and a Payment Request all build: a bare one.

	``get_payment_entry`` is ERPNext's own constructor and carries no Nyabo field, which is
	the whole point — nothing here names a primary document.
	"""
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	payment = get_payment_entry("Purchase Invoice", invoice, bank_account=bank_gl)
	payment.posting_date = "2026-09-02"
	payment.reference_no = "desk-1"
	payment.reference_date = "2026-09-02"
	payment.flags.ignore_permissions = True
	return payment


def test_a_payment_entry_nyabo_did_not_make_needs_no_primary_document(guarded_books):
	"""K2: art. 13.7 is asked of Nyabo's postings, not of every Payment Entry on the site.

	ERPNext submits Payment Entries of its own — from the desk, from the Bank Reconciliation
	Tool (``create_payment_entry_bts``) and from a Payment Request — and none of them can name
	a primary document. Journal Entry has ``system_generated_source`` as its escape hatch and
	that returns None for anything else, so putting Payment Entry in PRIMARY_DOCUMENT_DOCTYPES
	refused every payment the company made (COMP-10).
	"""
	import frappe

	books, banks = guarded_books
	pi = helpers.unpaid_purchase_invoice(
		books, "Петровис ХХК", 93500, "2026-09-01", nyabo_primary_document_ref="Нэхэмжлэх PET-1"
	)
	payment = _desk_payment_entry(books, banks["khan_gl"], pi.name)
	payment.insert()
	assert not any(payment.get(field) for field in ("nyabo_proposal", "source_document"))
	assert not payment.get("nyabo_explanation") and not payment.get("nyabo_primary_document_ref")
	payment.submit()

	assert int(payment.docstatus) == 1
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 0.0
	# It is nobody's Nyabo document, so the art. 11.1 trash guard does not hold it either
	# (``force`` only skips the GL Entry link check; ``on_trash`` still runs).
	payment.cancel()
	frappe.delete_doc("Payment Entry", payment.name, ignore_permissions=True, force=True)
	assert not frappe.db.exists("Payment Entry", payment.name)


def test_a_nyabo_payment_entry_without_its_primary_document_is_still_refused(guarded_books):
	"""The other half of K2: the Nyabo trail is what makes art. 13.7 apply, and it still does."""
	import frappe

	books, banks = guarded_books
	pi = helpers.unpaid_purchase_invoice(
		books, "Петровис ХХК", 93500, "2026-09-01", nyabo_primary_document_ref="Нэхэмжлэх PET-1"
	)
	payment = _desk_payment_entry(books, banks["khan_gl"], pi.name)
	# A settlement that lost its source document: Nyabo's explanation, nothing behind it.
	payment.nyabo_explanation = "Тест: эх баримтгүй төлбөр"
	payment.insert()
	assert not payment.get("source_document") and not payment.get("nyabo_primary_document_ref")

	with pytest.raises(frappe.ValidationError) as info:
		payment.submit()
	assert mn.MSG_PRIMARY_DOCUMENT_REQUIRED in str(info.value)
	assert int(frappe.db.get_value("Payment Entry", payment.name, "docstatus")) == 0
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 93500.0


def test_cancelling_a_settlement_returns_the_line_and_the_payable(books, banks, as_user):
	"""S17: the stub's cancel path was dead, so nothing about undoing a settlement was tested."""
	import frappe
	from erpnext.accounts.utils import get_balance_on

	pi = helpers.unpaid_purchase_invoice(books, "Петровис ХХК", 93500, "2026-09-01")
	_import(books, fixtures.khan_xlsx)
	bt = _bt(withdrawal=93500.0)
	payable_before = get_balance_on(_payable(books), party_type="Supplier", party="Петровис ХХК")
	bank_before = get_balance_on(banks["khan_gl"])
	with as_user(ACCOUNTANT, ACCOUNTANT_ROLES) as user:
		result = match.settle(bt.name, "Purchase Invoice", pi.name, user)

	payment = frappe.get_doc("Payment Entry", result["payment_entry"])
	payment.flags.ignore_permissions = True
	payment.cancel()

	assert int(frappe.db.get_value("Payment Entry", payment.name, "docstatus")) == 2
	assert get_balance_on(_payable(books), party_type="Supplier", party="Петровис ХХК") == payable_before
	assert get_balance_on(banks["khan_gl"]) == bank_before
	assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 93500.0
	bt.reload()
	assert bt.status == "Unreconciled" and float(bt.unallocated_amount) == 93500.0
	assert not bt.payment_entries
	# The line can be settled again from scratch.
	assert match.settlement_needed("Purchase Invoice", pi.name) is True
