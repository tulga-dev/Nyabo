"""Register the bot's command menu with Telegram (UX-12).

Telegram will not accept a Cyrillic command name: BotCommand.command is "1-32 characters.
Can contain only lowercase English letters, digits and underscores" (Bot API, read
2026-09-09). So the ☰ menu carries Latin names — ``/bank``, ``/close``, ``/setup`` — while
the accountant keeps typing ``/данс``, ``/хаалт``, ``/эхлэх``; ``router._commands()`` maps
both spellings to the same handler and the Mongolian description beside each Latin name
says which Cyrillic command it is.

Only the commands a linked user can actually run are registered. ``/link`` and ``/status``
are admin bootstrap commands and stay out of everyone's menu; ``/whoami`` is a diagnostic
the admin instructions mention.

Run after deploying, next to ``webhook.setup_webhook``::

    bench --site <site> execute nyabo_mn.telegram.commands.setup_commands
"""

from __future__ import annotations

from typing import Any

from nyabo_mn.i18n import mn
from nyabo_mn.log import log_event

# Latin command names in menu order; each must exist in ``router._commands()``.
MENU_COMMANDS: tuple[str, ...] = (
	"start",
	"menu",
	# /cancel is the floor under every form (UX-13): it needs no card on screen, survives
	# scroll-back, and is the one way out that works when the user has lost their place.
	# ``router.is_routable`` is what checks it reaches a handler — it runs before the command
	# table, because every command clears the conversation it would otherwise be cancelling.
	"cancel",
	"help",
	"bank",
	"close",
	"quality",
	"policy",
	"company",
	"setup",
	# /rules (/дүрэм) is in everyone's menu although only an admin may verify: the accountant whose
	# receipt was refused for an unverified rule has to be able to find out who can clear it, and
	# ``admin.handle_rules`` answers them with that rather than with a bare refusal.
	"rules",
)

# BotCommandScopeAllPrivateChats: Nyabo is a one-to-one bot, and a group chat would show
# the menu to people who are not linked to any company.
SCOPE_ALL_PRIVATE_CHATS = {"type": "all_private_chats"}
MENU_BUTTON_COMMANDS = {"type": "commands"}
MAX_DESCRIPTION_CHARS = 256


def bot_commands() -> list[dict[str, str]]:
	"""The BotCommand array, built from ``mn.BOT_COMMAND_DESCRIPTIONS`` so wording stays in i18n."""
	return [
		{
			"command": name,
			"description": mn.BOT_COMMAND_DESCRIPTIONS[name][:MAX_DESCRIPTION_CHARS],
		}
		for name in MENU_COMMANDS
	]


def setup_commands(bot: Any = None) -> dict[str, Any]:
	"""``bench --site <site> execute nyabo_mn.telegram.commands.setup_commands``"""
	from nyabo_mn.telegram.api import get_bot

	bot = bot or get_bot()
	commands = bot_commands()
	bot.set_my_commands(commands, scope=SCOPE_ALL_PRIVATE_CHATS)
	bot.set_chat_menu_button(menu_button=MENU_BUTTON_COMMANDS)
	log_event("telegram.commands.registered", count=len(commands))
	return {"commands": [c["command"] for c in commands]}


__all__ = ["MENU_COMMANDS", "bot_commands", "setup_commands"]
