"""UX-08 / ARCHITECTURE principle 7: every string a user reads lives in ``nyabo_mn/i18n/mn.py``.

A Mongolian literal outside i18n is invisible to whoever edits the wording, so this test
walks the source with ``ast`` and fails on any Cyrillic string constant in a module that is
not on the allow-list below. Docstrings and comments are exempt — they are for us, not for
the accountant.

The allow-list is for Cyrillic that is *input*, not output: words Nyabo reads (statement
column headers, command names the user types, injection patterns) and fixture data. Each
entry carries the reason, and a stale entry fails too, so the list cannot rot.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "nyabo_mn"
CYRILLIC = re.compile(r"[Ѐ-ӿ]")

# Modules exempt as a whole, with the reason. Anything else that a user reads belongs in mn.py.
ALLOWED: dict[str, str] = {
	"agent/schemas.py": "field descriptions handed to the model; they quote what a receipt prints",
	"core/matching.py": "normalisation keywords (ХХК, хураамж…) matched against supplier text",
	"core/money.py": "the currency-mark regex that strips ₮/төг from a parsed amount",
	"core/quarantine.py": "injection patterns matched against untrusted document text",
	"core/statements.py": "bank statement column header keywords",
	"ebarimt/mock.py": "fixture sellers for the simulator and tests",
	"evals/golden/_generate.py": "golden eval fixtures (receipts, statements, expectations)",
	"evals/harness.py": "eval fixture company name",
	"evals/runners.py": "eval fixture company name",
	"hooks.py": "Frappe app metadata, read by bench before the app is importable",
	"matching/bank_import.py": "bank-name keywords matched against statement text",
	"matching/rules.py": "the legal citation carried by a seeded rule",
	"setup/chart_csv.py": "CSV column header aliases in the accountant's own file",
	"setup/demo.py": "demo fixture data for a test company: supplier names, remarks, expense-leaf keywords",
	"setup/inventory_intake.py": "inventory column header aliases in the accountant's own file",
	"telegram/handlers/escape.py": "the Cyrillic escape words a user types (цуцлах, буцах, алгасах)",
	"telegram/router.py": "the Cyrillic command names a user types",
	"telegram/state.py": "the role words a user types in /link",
}


def _docstring_ids(tree: ast.Module) -> set[int]:
	ids = set()
	for node in ast.walk(tree):
		if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
			body = node.body
			first = body[0] if body else None
			if (
				isinstance(first, ast.Expr)
				and isinstance(first.value, ast.Constant)
				and isinstance(first.value.value, str)
			):
				ids.add(id(first.value))
	return ids


def cyrillic_literals(path: Path) -> list[tuple[int, str]]:
	"""(line, text) for every Cyrillic string constant in the file that is not a docstring."""
	tree = ast.parse(path.read_text(encoding="utf-8"))
	docstrings = _docstring_ids(tree)
	return [
		(node.lineno, node.value)
		for node in ast.walk(tree)
		if isinstance(node, ast.Constant)
		and isinstance(node.value, str)
		and id(node) not in docstrings
		and CYRILLIC.search(node.value)
	]


def test_no_user_facing_mongolian_outside_i18n():
	offenders: list[str] = []
	for path in sorted(ROOT.rglob("*.py")):
		rel = path.relative_to(ROOT).as_posix()
		if rel.startswith("i18n/") or rel in ALLOWED:
			continue
		offenders += [f"{rel}:{line}: {text[:60]!r}" for line, text in cyrillic_literals(path)]
	assert offenders == [], (
		"Mongolian text outside nyabo_mn/i18n/mn.py — move it there and refer to it by name "
		"(add to ALLOWED only when the Cyrillic is input Nyabo reads, never output):\n" + "\n".join(offenders)
	)


# The genitive of «багана» is «баганын»: багана + ын. Settled by the founder, a native
# speaker, on 9 September 2026, against an earlier guess of «баганы» that had derived a
# fleeting final -а and a stem «баган-» taking -ы. That derivation was wrong, and the code
# carried both spellings in one conversation before it, so this keeps the ruling enforced.
GENITIVE_OF_BAGANA = "аганын"
REJECTED_GENITIVE = re.compile("аганы(?!н)")  # «баганы» only, never the tail of «баганын»
GENITIVE_SOURCES = (ROOT, ROOT.parent / "scripts")


def test_the_genitive_of_bagana_is_spelled_one_way():
	"""«Баганы» and «Баганын» once sat in the same conversation, three lines apart.

	The column-mapping flow said one thing when it cancelled and another when it finished, and
	the Nyabo Bank Layout field label said a third — which reads as carelessness in a bot an
	accountant is being asked to trust with the books. This walks the shipped source, not only
	``mn.py``, because the desk label and the spec that generates it are read by the same
	accountant as the bot's own messages.
	"""
	offenders: list[str] = []
	for root in GENITIVE_SOURCES:
		for path in sorted(root.rglob("*")):
			if not path.is_file() or path.suffix not in (".py", ".json", ".md"):
				continue
			if path.resolve() == Path(__file__).resolve():
				continue  # this file names the rejected spelling on purpose
			for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
				if REJECTED_GENITIVE.search(line):
					offenders.append(f"{path.relative_to(ROOT.parent).as_posix()}:{number}")
	assert offenders == [], f"«{GENITIVE_OF_BAGANA}», not «аганы», everywhere: {offenders}"
	assert GENITIVE_OF_BAGANA in (ROOT / "i18n" / "mn.py").read_text(encoding="utf-8")


# A case suffix hyphenated straight onto a placeholder — «{period}-д», «{date}-нд»,
# «{retention_years}-аас». Banned, and this is the second time: the numeral truncation note
# («{shown}-г») was fixed the same way a round earlier. The correct ending depends on the last
# sound of the word the placeholder renders, and a placeholder renders a *formatted* value — a
# month label («2027 оны 1-р сар» takes «сард», never «сар-д»), a numeral («5» takes «-аас», «2»
# takes «-оос»), an ISO date («…-05» takes «-нд», «…-08» takes «-д») — so one spelling in the
# source can only ever be right for some of the values it will be given. The suffix goes on a
# fixed noun the sentence supplies instead («тайлант үед ({period})», «{date} өдрийн»), or the
# label is set off with a colon.
#
# «-р» is not a case suffix but the ordinal marker, written the same after every numeral
# («9-р сар», «2-р мөр»), so it is allowed — and no case suffix begins with «р», so
# excluding it costs nothing.
SUFFIXED_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}-(?!р)[Ѐ-ӿ]")
# The one exception: a proper name or an abbreviation, where the hyphenated suffix IS the
# written form («Петровис ХХК-ийн»).
NAME_PLACEHOLDERS = {"company"}


def test_no_case_suffix_hangs_off_an_interpolated_label():
	"""MAJOR: «Компани {period}-д НӨАТ төлөгч бус» rendered «… 2027 оны 1-р сар-д …».

	Machine Mongolian on the card an accountant reads to find out whether VAT applies to them,
	and the same fault class as the numeral suffix fixed a round earlier. This sweeps the whole
	file rather than the one string, because the shape is what is banned.
	"""
	offenders = [
		f"mn.py:{line}: {text[:70]!r}"
		for line, text in cyrillic_literals(ROOT / "i18n" / "mn.py")
		for match in SUFFIXED_PLACEHOLDER.finditer(text)
		if match.group(1) not in NAME_PLACEHOLDERS
	]
	assert offenders == [], (
		"a case suffix hyphenated onto a formatted value; reword so the suffix falls on a fixed "
		"noun («тайлант үед ({period})», «{date} өдрийн») or set the label off with a colon:\n"
		+ "\n".join(offenders)
	)


def test_the_vat_card_names_the_month_without_declining_it():
	"""The card the sweep above was written for, checked as the accountant reads it."""
	from nyabo_mn.i18n import mn

	label = mn.PERIOD_LABEL.format(year=2027, month=mn.MONTHS[0])
	answer = mn.MSG_VAT_NOT_PAYER_ANSWER.format(period=label)
	assert label in answer and f"{label}-" not in answer


# Every constant that says «доорх» ("below"), and where the keyboard it points at really is.
# ``ctx.reply(text, markup)`` puts the buttons on the message itself; a line whose keyboard is
# on the *next* message is still true, because that message is below it in the chat. A line
# sent with no keyboard at all anywhere below is not, and that is what this list pins.
BELOW_POINTS_AT: dict[str, str] = {
	"MSG_ERROR_ADMIN_NOTIFIED": "telegram/router.py sends it with keyboards.menu_markup()",
	"MSG_FEATURE_UNAVAILABLE": "telegram/router.py sends it with keyboards.menu_markup()",
	"MSG_STATEMENT_LAYOUT_INCOMPLETE": (
		"statement._answer_column re-asks the column straight after it, roles keyboard and all"
	),
	"MSG_STATEMENT_LAYOUT_SAVED": (
		"statement.save_layout sends ask_layout_confirmation straight after it, mapping and buttons"
	),
	"MSG_STATEMENT_LAYOUT_UNVERIFIED": (
		"statement.run_import sends ask_layout_confirmation straight after it, mapping and buttons"
	),
	"ONB_CURRENCY_ADDED": "onboarding._on_currency sends it with keyboards.onboarding_currencies()",
	"MSG_TYPED_PROPOSED": (
		"handlers.question._send prints it as the first line of the proposal card, which goes out "
		"with keyboards.receipt_keyboard() — the [Батлах] it points at"
	),
	"AGENT_ANSWER_INJECTION_REFUSED": (
		"agent.questions returns it with FollowUp(VERB_MENU, BTN_MENU), which handlers.question "
		"draws as keyboards.question_keyboard under the answer"
	),
}


def test_every_below_points_at_a_keyboard_that_is_drawn(site):
	"""MINOR: MSG_STEP_CANNOT_SKIP said «Доорх товчнуудаас сонгоно уу» with nothing below it.

	``escape.refuse`` sends the refusal with ``ctx.reply(text)`` and no markup, so the buttons
	it meant were the open prompt's, above. A user reading «choose from the buttons below» and
	finding none is exactly the dead end UX-13 exists to remove, so the wording moved to the
	question above — and every other «доорх» in the file is pinned here with the keyboard that
	makes it true. A new one has to be added deliberately; a stale entry fails too.
	"""
	from nyabo_mn.i18n import mn

	saying_below = {
		name
		for name, value in vars(mn).items()
		if not name.startswith("_") and isinstance(value, str) and "доорх" in value.lower()
	}
	assert saying_below == set(BELOW_POINTS_AT), (
		"a string says «доорх»: send it with a keyboard (or one on the very next message) and "
		"name it here, or reword it — the refusals say «Дээрх асуултад хариулна уу» instead"
	)
	assert "доорх" not in mn.MSG_STEP_CANNOT_SKIP.lower()
	assert "доорх" not in mn.MSG_STEP_NO_BACK.lower()


@pytest.mark.parametrize("rel", sorted(ALLOWED))
def test_allow_list_has_no_stale_entry(rel: str):
	"""An exemption that no longer applies must be deleted, not left to hide a new literal."""
	path = ROOT / rel
	assert path.exists(), f"{rel} is on the allow-list but does not exist"
	assert cyrillic_literals(path), f"{rel} has no Cyrillic literal left; drop it from ALLOWED"
	assert ALLOWED[rel].strip(), f"{rel} needs a reason"
