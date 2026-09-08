"""Telegram handlers, one module per flow (docs/ARCHITECTURE.md §3).

Each handler takes the ``Ctx`` from ``nyabo_mn.telegram.context`` and returns quickly;
model and import work is enqueued and replies later through ``receipt.send_proposal_card``
or ``statement`` follow-ups.
"""
