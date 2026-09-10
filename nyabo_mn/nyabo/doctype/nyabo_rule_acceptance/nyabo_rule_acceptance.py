"""One accountant's acceptance of one uncited rule for one company's books, as it then read.

WHY a controller at all: the row is a compliance record, so the things that make it one are
enforced here rather than trusted to every caller.

* The rule it names must exist, and its DocType is derived rather than accepted from the caller.
* The rule's **content** is stamped on the row before it is named (``rule_fingerprint``,
  ``rule_content_json``). An acceptance is one person saying «I have read this and these books
  work this way», so it is about the debit and credit lines that were in front of them, not
  about a rule id for ever. A later deploy that rewrites those lines leaves this row saying
  exactly what it always said, and ``rules.verify.acceptance`` stops treating it as covering the
  new content.
* The name is ``company:kind:rule:fingerprint``, so one company answering for one version of one
  rule is one row, and answering again for a changed version is a second row rather than an edit
  of the first — two decisions, taken on two texts.

``rules.verify.accept`` is the only writer, and nothing rewrites a row afterwards: it is
append-only in this controller the way ``Nyabo Event`` is — which is also why there is no free
text field on the row. A ``note`` column stood here that nothing could ever fill: ``accept`` never
set it, no role held ``write``, and the ``validate`` below refuses every save that is not an
insert. A schema that offers a place to record something, and then cannot hold anything there, is
worse than not offering it.

The desk may still delete a row — that is how an acceptance is withdrawn, the rule stops posting
again the moment it is, and the ``rule_accepted_for_company`` event stays either way. That deletion is the one difference from
Nyabo Event, and it is deliberate: an edit rewrites what a person read, a deletion does not
claim they read anything.
"""

from __future__ import annotations

import json

import frappe
from frappe.model.document import Document

from nyabo_mn.i18n import mn


class NyaboRuleAcceptance(Document):
	def before_insert(self) -> None:
		"""Stamp the rule's DocType and the content being accepted, before the row is named.

		Frappe runs ``before_insert`` ahead of naming, which is what lets the fingerprint be part
		of the document name. It is computed here rather than trusted from the caller: the row is
		the evidence, and evidence a caller can dictate is not evidence.
		"""
		from nyabo_mn.rules import verify

		doctype = self._rule_doctype()
		content = verify.rule_content(doctype, self.rule)
		self.rule_doctype = doctype
		self.rule_fingerprint = verify.fingerprint(content)
		self.rule_content_json = json.dumps(content, ensure_ascii=False, sort_keys=True)

	def validate(self) -> None:
		"""Append-only: what a named person took responsibility for cannot be edited afterwards.

		``Nyabo Accountant`` held ``write`` and the identifying fields were only read-only in the
		UI, so the accountant an acceptance names could change the rule, the company or the date
		with nothing in the record marking it. The permissions no longer grant ``write`` to
		anybody, and this refuses the save as well, because a compliance record must not depend
		on a role table somebody may edit in the desk.
		"""
		if not self.is_new():
			frappe.throw(mn.MSG_ACCEPTANCE_APPEND_ONLY)
		self.rule_doctype = self._rule_doctype()

	def _rule_doctype(self) -> str:
		from nyabo_mn.rules import verify

		doctype = verify.doctype_for(self.rule_kind)
		if not doctype or not frappe.db.exists(doctype, self.rule):
			frappe.throw(mn.MSG_RULE_NOT_FOUND.format(rule=self.rule))
		return doctype
