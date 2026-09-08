"""Frappe side of bank statements (docs/ARCHITECTURE.md §5.4).

``bank_import`` turns a Nyabo Document into ERPNext Bank Transactions, ``match`` pairs
them with submitted vouchers through ERPNext's own allocation, ``rules`` builds the
Nyabo Proposals for fee lines, transfers and unmatched lines (never posted here),
``cards`` renders the Telegram text, ``status`` answers ``/данс``.
"""
