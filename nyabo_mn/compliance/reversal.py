"""Corrections are reversals (ARCHITECTURE §1.5, §5.6; Law on Accounting art. 15).

A posted Journal Entry is reversed with ERPNext's ``make_reverse_journal_entry`` (debit and
credit swapped, ``reversal_of`` set); a Purchase Invoice with ``make_debit_note``
(``is_return = 1``, ``return_against``). Nothing is edited or cancelled: the original stays
in the ledger next to its reversal, both carry the reason and the approver, and a
Nyabo Correction plus a Nyabo Event record the decision for the audit trail.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import getdate, nowdate

from nyabo_mn import access
from nyabo_mn.compliance import events
from nyabo_mn.compliance.period import is_locked
from nyabo_mn.i18n import mn

# Payment Entry is deliberately NOT here (COMP-10). Every entry in this tuple has an ERPNext
# constructor that builds a *counter-document* leaving the original in place -
# ``make_reverse_journal_entry``, ``make_debit_note``. A Payment Entry has none: ERPNext undoes
# one by cancelling it, which is what re-opens the invoice through the Payment Ledger and, via
# ``remove_from_bank_transaction``, releases the statement line. A hand-built reversing Journal
# Entry would move the bank and the payable back while leaving ``outstanding_amount`` saying
# "Paid", which is a worse book than the mistake. A mis-tapped settlement is therefore corrected
# by cancelling the Payment Entry (the line returns to Unreconciled and can be settled again) or,
# when the invoice itself was wrong, by reversing the invoice - which this module does support.
SUPPORTED: tuple[str, ...] = ("Journal Entry", "Purchase Invoice")
REVERSAL_ROLES: tuple[str, ...] = ("Nyabo Accountant", "Nyabo Admin", "System Manager")


def require_rights(user: str, company: str) -> None:
	"""Reversing is an accountant action on a company the user is linked to.

	The Telegram handler checks this too, but the invariant must not depend on one caller:
	document names are a global sequence, so an unguarded ``reverse`` would let any linked
	accountant reverse another company's ledger (as ``period.lock`` guards itself).
	"""
	if user == "Administrator":
		return
	if not set(REVERSAL_ROLES).intersection(frappe.get_roles(user)):
		frappe.throw(mn.MSG_NO_PERMISSION, frappe.PermissionError)
	access.require_company(user, company)


def reason_label(reason_code: str) -> str:
	label = mn.CORRECT_REASONS.get(reason_code)
	if not label:
		frappe.throw(mn.MSG_CORRECTION_REASON_UNKNOWN.format(code=reason_code))
	return label


def already_reversed(doctype: str, name: str) -> bool:
	"""ERPNext allows one submitted reversal per source; Nyabo asks the same question first."""
	if frappe.db.exists(doctype, {"nyabo_corrects": name, "docstatus": 1}):
		return True
	if doctype == "Journal Entry":
		return bool(frappe.db.exists("Journal Entry", {"reversal_of": name, "docstatus": 1}))
	return bool(
		frappe.db.exists("Purchase Invoice", {"return_against": name, "is_return": 1, "docstatus": 1})
	)


def is_reversal(doctype: str, doc: Any) -> bool:
	"""True when the document is itself a correction, so reversing it would nest the chain.

	ERPNext refuses this too, in English and only at the end of ``make_reverse_journal_entry``
	/ ``make_debit_note``; the correction chain stays one level deep (art. 15.1), so Nyabo
	asks first and answers in Mongolian.
	"""
	if (doc.get("nyabo_corrects") or "").strip():
		return True
	if doctype == "Journal Entry":
		return bool(doc.get("reversal_of"))
	return int(doc.get("is_return") or 0) == 1


def _primary_document_ref(original: Any) -> str:
	"""The reversal's own primary document is the correction record naming the original (art. 15.1)."""
	existing = (original.get("nyabo_primary_document_ref") or "").strip()
	return existing or f"{original.doctype} {original.name}"


def _stamp(target: Any, original: Any, reason_text_full: str, user: str) -> None:
	target.nyabo_correction_reason = reason_text_full
	target.nyabo_corrects = original.name
	target.nyabo_approved_by = user
	target.source_document = original.get("source_document")
	target.nyabo_primary_document_ref = _primary_document_ref(original)
	target.nyabo_proposal = original.get("nyabo_proposal")
	target.nyabo_explanation = mn.EXPL_REVERSAL.format(original=original.name, reason=reason_text_full)[:300]


def reverse(
	doctype: str,
	name: str,
	reason_code: str,
	reason_text: str,
	user: str,
	telegram_id: str | int | None = None,
) -> dict[str, Any]:
	"""Create, submit and record the reversal of a posted document.

	Returns ``{"reversal_doctype", "reversal_name", "dated_in_original_period"}``. The
	reversal is dated on the original's posting date while that month is open, else today;
	the flag lets the bot warn the accountant (``MSG_CORRECTION_PERIOD_CLOSED``).
	"""
	if doctype not in SUPPORTED:
		frappe.throw(mn.MSG_CORRECTION_UNSUPPORTED_DOCTYPE.format(doctype=doctype))
	label = reason_label(reason_code)
	original = frappe.get_doc(doctype, name)
	require_rights(user, str(original.company or ""))
	if int(original.docstatus or 0) != 1:
		frappe.throw(mn.MSG_CORRECTION_NOT_SUBMITTED.format(name=name))
	if is_reversal(doctype, original):
		frappe.throw(mn.MSG_CORRECTION_IS_REVERSAL)
	if already_reversed(doctype, name):
		frappe.throw(mn.MSG_CORRECTION_ALREADY_REVERSED)
	reason_text_full = f"{label}: {reason_text}".strip(": ").strip() if reason_text else label
	locked, _period = is_locked(original.company, original.posting_date)
	posting_date = getdate(nowdate()) if locked else getdate(original.posting_date)

	if doctype == "Journal Entry":
		from erpnext.accounts.doctype.journal_entry.journal_entry import make_reverse_journal_entry

		target = make_reverse_journal_entry(name)
		target.posting_date = posting_date
		target.user_remark = reason_text_full
	else:
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note

		target = make_debit_note(name)
		target.posting_date = posting_date
		target.due_date = posting_date
		if target.meta.has_field("set_posting_time"):
			target.set_posting_time = 1
		target.remarks = reason_text_full
	_stamp(target, original, reason_text_full, user)
	target.flags.ignore_permissions = True
	target.insert()
	target.submit()

	correction = frappe.get_doc(
		{
			"doctype": "Nyabo Correction",
			"proposal": original.get("nyabo_proposal"),
			"company": original.company,
			"field": "reversed",
			"proposed_value": name,
			"corrected_value": target.name,
			"corrected_by": user,
			"corrected_telegram_id": str(telegram_id) if telegram_id is not None else None,
			"reason": label,
			"reason_text": reason_text,
			"source": "reversal",
			"posted_doctype": doctype,
			"posted_name": name,
			"reversal_name": target.name,
			"supplier": original.get("supplier"),
		}
	)
	correction.flags.ignore_permissions = True
	correction.insert()
	events.log(
		mn.EVENT_ENTRY_REVERSED,
		company=original.company,
		ref_doctype=doctype,
		ref_name=name,
		reason=reason_text_full,
		payload={
			"reversal_doctype": doctype,
			"reversal_name": target.name,
			"correction": correction.name,
			"approved_by": user,
			"dated_in_original_period": not locked,
			"posting_date": posting_date.isoformat(),
		},
		actor_telegram_id=telegram_id,
	)
	original.add_comment(
		"Comment", mn.MSG_CORRECTION_DONE.format(reversal=target.name, reason=label, approver=user)
	)
	return {
		"reversal_doctype": doctype,
		"reversal_name": target.name,
		"dated_in_original_period": not locked,
	}
