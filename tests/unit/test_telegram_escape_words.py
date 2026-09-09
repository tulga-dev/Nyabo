"""UX-13: the words a user types to get out, and the rows they tap instead.

The founder typed «алгасах» into the inventory step and the step's parser answered
«1-р мөрийг уншиж чадсангүй». Whatever a step does with its input, these words have to be
recognised before it ever sees them, and they have to survive the punctuation a phone
keyboard adds by itself.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from nyabo_mn.i18n import mn
from nyabo_mn.telegram import keyboards
from nyabo_mn.telegram.handlers import escape, onboarding


@pytest.mark.parametrize(
	("typed", "verb"),
	[
		("алгасах", escape.SKIP),
		("Алгасах", escape.SKIP),
		("  алгасах  ", escape.SKIP),
		("/skip", escape.SKIP),
		("/алгасах", escape.SKIP),
		("цуцлах", escape.CANCEL),
		("болих", escape.CANCEL),
		("болих уу", escape.CANCEL),
		("Болих уу?", escape.CANCEL),
		("«болих уу»", escape.CANCEL),
		("гарах", escape.CANCEL),
		("/cancel", escape.CANCEL),
		("/cancel@nyabo_bot", escape.CANCEL),
		("/цуцлах", escape.CANCEL),
		("буцах", escape.BACK),
		("/back", escape.BACK),
		("цэс", escape.MENU),
		("меню", escape.MENU),
	],
)
def test_the_escape_words_are_understood(typed: str, verb: str):
	assert escape.intent(typed) == verb


@pytest.mark.parametrize(
	"typed",
	[
		"",
		"   ",
		"Принтерийн хор, 5, 45000",
		"гарах зардал",  # an account search, not a way out
		"цуцлахыг хүсэхгүй байна",
		"5001234567",
		"/эхлэх",
		"/меню",
		"/start",
	],
)
def test_ordinary_input_is_not_an_escape(typed: str):
	"""Matching is on the whole message: a step's own answer must reach the step."""
	assert escape.intent(typed) is None


def test_reverse_is_not_read_as_back():
	"""«Буцаах» is BTN_REVERSE — reversing a posted entry — and must never mean "go back"."""
	assert mn.BTN_REVERSE == "Буцаах"
	assert escape.intent(mn.BTN_REVERSE.lower()) is None
	assert escape.intent(mn.BTN_BACK.lower()) == escape.BACK


def test_every_button_label_that_is_an_escape_is_also_understood_typed():
	"""A user who types what the button says gets what the button does."""
	assert escape.intent(mn.BTN_CANCEL.lower()) == escape.CANCEL
	assert escape.intent(mn.BTN_SKIP.lower()) == escape.SKIP
	assert escape.intent(mn.BTN_MENU.lower()) == escape.MENU


# --- the rows themselves -------------------------------------------------------------------------


def test_escape_row_is_ordered_and_fits_the_callback_budget():
	row = keyboards.escape_row("onb:inv_wait", back=True, skip=True)
	assert [b["text"] for b in row] == [mn.BTN_BACK, mn.BTN_SKIP, mn.BTN_CANCEL]
	assert [b["callback_data"] for b in row] == [
		"e:onb:back:inv_wait",
		"e:onb:skip:inv_wait",
		"e:onb:cancel:inv_wait",
	]
	assert row[-1]["style"] == keyboards.STYLE_DANGER
	for scope in (
		keyboards.SCOPE_ONBOARDING,
		keyboards.SCOPE_ACCOUNT_SEARCH,
		keyboards.SCOPE_REJECT_TEXT,
		keyboards.SCOPE_CORRECTION,
		keyboards.SCOPE_LAYOUT,
		keyboards.SCOPE_BANK_FIND,
		keyboards.SCOPE_ERROR,
	):
		for verb in (keyboards.ESCAPE_CANCEL, keyboards.ESCAPE_BACK, keyboards.ESCAPE_SKIP):
			data = keyboards.escape_data(scope, verb)
			assert len(data.encode("utf-8")) <= keyboards.MAX_CALLBACK_DATA_BYTES


def test_the_longest_state_name_still_fits_the_64_byte_datum():
	"""Telegram: callback_data is "1-64 bytes". Every state a prompt can be drawn for is checked.

	The step rides in the datum (UX-13 follow-up), so the budget now depends on the longest
	state name in the app, not only on the scope.
	"""
	states = [
		f"{keyboards.SCOPE_ONBOARDING}:{step}"
		for step in (*onboarding.BACK_STEPS, "vat", "inv_wait", "inv_confirm", "acc_name")
	]
	states += [
		keyboards.STATE_CORRECTION_TEXT,
		keyboards.SCOPE_ACCOUNT_SEARCH,
		keyboards.SCOPE_REJECT_TEXT,
		keyboards.SCOPE_BANK_FIND,
		keyboards.SCOPE_ERROR,
		f"{keyboards.SCOPE_LAYOUT}:999",
	]
	longest = max(states, key=len)
	for state in states:
		for verb in (
			keyboards.ESCAPE_CANCEL,
			keyboards.ESCAPE_BACK,
			keyboards.ESCAPE_SKIP,
			keyboards.ESCAPE_MENU,
		):
			data = keyboards.escape_data(state, verb)
			assert len(data.encode("utf-8")) <= keyboards.MAX_CALLBACK_DATA_BYTES, data
	assert len(keyboards.escape_data(longest, keyboards.ESCAPE_CANCEL).encode("utf-8")) < 40


def test_a_scope_is_the_state_prefix_it_was_drawn_for():
	"""``escape.state_scope`` is what tells a live step from a card scrolled back to."""
	assert escape.state_scope("onb:inv_wait") == keyboards.SCOPE_ONBOARDING
	assert escape.state_scope("layout:3") == keyboards.SCOPE_LAYOUT
	assert escape.state_scope("acc_search") == keyboards.SCOPE_ACCOUNT_SEARCH
	assert escape.state_scope(None) == ""
	assert escape.state_step("onb:inv_wait") == "inv_wait"
	assert escape.state_step("acc_search") == ""


def test_a_button_is_stale_unless_it_was_drawn_for_the_open_step():
	"""The comparison the staleness guard makes, without a chat around it."""
	assert escape.drawn_for_open_step("onb", "inv_wait", "onb:inv_wait") is True
	assert escape.drawn_for_open_step("onb", "acc_name", "onb:inv_wait") is False
	assert escape.drawn_for_open_step("onb", "inv_wait", "layout:0") is False
	assert escape.drawn_for_open_step("acc_search", None, "acc_search") is True
	# A card drawn before the step rode along: the flow is all there is to compare.
	assert escape.drawn_for_open_step("onb", None, "onb:acc_name") is True


def test_the_bot_api_versions_the_buttons_are_credited_to_are_the_right_ones():
	"""A quoted source has to be correct, and these two fields are the deployment's floor.

	api-changelog, Bot API 9.4 (2026-02-09): "Added the field style to the classes
	KeyboardButton and InlineKeyboardButton, allowing bots to change the color of buttons."
	Bot API 10.3 (2026-08-24): "Added the class DisabledButton and the field disabled to the
	class InlineKeyboardButton." The style field was credited to 10.3, which is neither where
	it came from nor the reason the deployment needs 10.3.
	"""
	source = Path(keyboards.__file__).read_text(encoding="utf-8")
	style_note = source.split("STYLE_DANGER")[0].split("InlineKeyboardButton.style")[1]
	assert "9.4" in style_note and "10.3" not in style_note
	spent_note = inspect.getdoc(keyboards.spent) or ""
	assert "10.3" in spent_note and "DisabledButton" in spent_note
	assert "9.4" not in spent_note
	# The module says what the two fields cost the deployment.
	assert "10.3" in (keyboards.__doc__ or "") and "9.4" in (keyboards.__doc__ or "")


def test_spent_disables_every_button_and_drops_its_data():
	"""A DisabledButton is a button *type*: "Exactly one of the fields other than text,
	icon_custom_emoji_id, and style must be used to specify the type of the button"."""
	original = keyboards.onboarding_confirm("summary")
	spent = keyboards.spent(original)
	buttons = [b for row in spent["inline_keyboard"] for b in row]
	assert buttons and all(b["disabled"] == {} for b in buttons)
	assert all("callback_data" not in b for b in buttons)
	assert [b["text"] for b in buttons] == [b["text"] for row in original["inline_keyboard"] for b in row]
	# The styles survive, so the cancelled card still reads the way it did.
	assert keyboards.STYLE_SUCCESS in [b.get("style") for b in buttons]
	assert keyboards.spent(None) == keyboards.empty_markup()
