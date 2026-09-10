"""One accountant's acceptance of one uncited rule for one company's books.

WHY a controller at all: the row is a compliance record, so the two things that make it one
are enforced here rather than trusted to every caller — the rule it names must exist, and the
name (``company:kind:rule``) must be unique, which is what makes the row a *fact* about a
company rather than a pile of taps. ``rules.verify.accept`` is the only writer; the desk may
delete a row (that is how an acceptance is withdrawn, and the Nyabo Event stays either way).
"""

from frappe.model.document import Document


class NyaboRuleAcceptance(Document):
	def validate(self) -> None:
		import frappe

		from nyabo_mn.i18n import mn
		from nyabo_mn.rules import verify

		doctype = verify.doctype_for(self.rule_kind)
		if not doctype:
			frappe.throw(mn.MSG_RULE_NOT_FOUND.format(rule=self.rule))
		if not frappe.db.exists(doctype, self.rule):
			frappe.throw(mn.MSG_RULE_NOT_FOUND.format(rule=self.rule))
		self.rule_doctype = doctype
