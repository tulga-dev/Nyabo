"""LLM layer: the model proposes, deterministic code validates (docs/ARCHITECTURE.md §6).

Nothing in this package imports frappe except ``frappe_log`` (lazily), so the simulator
and the unit tests can run the full extraction/classification path with ``MockLlmClient``.
"""
