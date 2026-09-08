"""Statement file readers and layout detection (docs/ARCHITECTURE.md §3, §5.4).

``excel.read_rows`` turns an upload into plain rows, ``layouts`` loads and learns
``Nyabo Bank Layout`` rows, ``detect`` picks the layout for a file. Column indexes never
live in code: they come from layout data or from the accountant's answers.
"""
