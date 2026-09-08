"""Frappe side of "rules as data" (docs/ARCHITECTURE.md §1.1, §1.2, §1.6, §9).

`params` reads dated Nyabo Tax Parameter rows, `regime` is the only module that knows
the regime names, `patterns` loads Nyabo Posting Pattern rows, `guard` refuses
unverified rules for real postings, `seed` upserts the JSON seed into the DocTypes and
`aliases` turns codes, aliases and roles into the company's chart codes. Everything that
does not need the database lives in `nyabo_mn.core.rules_engine`.
"""
