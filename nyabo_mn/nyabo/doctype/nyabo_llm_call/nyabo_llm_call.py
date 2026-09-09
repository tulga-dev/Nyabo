"""Nyabo LLM Call controller.

The class name is Frappe's, not ours: ``frappe.model.base_document.import_controller``
builds it as ``doctype.replace(" ", "").replace("-", "")`` and raises ImportError when no
class of that name is in the module. "Nyabo LLM Call" therefore has to be ``NyaboLLMCall``
— ``NyaboLlmCall`` made the DocType unloadable, so migrate skipped it and the site ran
without it. ``tests/unit/test_doctype_controllers.py`` holds every controller to that rule.
"""

from frappe.model.document import Document


class NyaboLLMCall(Document):
	pass
