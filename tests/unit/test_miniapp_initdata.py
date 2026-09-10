"""Telegram's Mini App ``initData`` is trusted only with the bot token's signature on it."""

from __future__ import annotations

import pytest

from nyabo_mn import miniapp

TOKEN = "12345:a-token-that-never-leaves-the-site"
NOW = 1_800_000_000
FIELDS = {"auth_date": NOW - 60, "query_id": "AAH", "user": {"id": 777, "first_name": "Бат"}}


def test_a_signature_made_with_the_token_is_accepted_and_the_user_read():
	fields = miniapp.verify_init_data(miniapp.sign_init_data(FIELDS, TOKEN), TOKEN, now=NOW)
	assert fields["user"] == {"id": 777, "first_name": "Бат"}
	assert fields["query_id"] == "AAH"


def test_a_tampered_field_is_refused():
	signed = miniapp.sign_init_data(FIELDS, TOKEN)
	with pytest.raises(miniapp.InitDataInvalid, match="bad hash"):
		miniapp.verify_init_data(signed.replace("777", "778"), TOKEN, now=NOW)


def test_another_bots_token_is_refused():
	with pytest.raises(miniapp.InitDataInvalid, match="bad hash"):
		miniapp.verify_init_data(miniapp.sign_init_data(FIELDS, "999:other"), TOKEN, now=NOW)


def test_yesterdays_init_data_is_refused():
	old = dict(FIELDS, auth_date=NOW - miniapp.MAX_AGE_SECONDS - 1)
	with pytest.raises(miniapp.InitDataInvalid, match="stale"):
		miniapp.verify_init_data(miniapp.sign_init_data(old, TOKEN), TOKEN, now=NOW)


def test_missing_pieces_are_refused_without_a_hash_check():
	for bad in ("", "user=%7B%7D&auth_date=1", "auth_date=abc&hash=00"):
		with pytest.raises(miniapp.InitDataInvalid):
			miniapp.verify_init_data(bad, TOKEN, now=NOW)
	with pytest.raises(miniapp.InitDataInvalid, match="missing"):
		miniapp.verify_init_data(miniapp.sign_init_data(FIELDS, TOKEN), "", now=NOW)
