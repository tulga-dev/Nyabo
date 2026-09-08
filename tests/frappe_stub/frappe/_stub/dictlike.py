"""``frappe._dict``: a dict whose keys are also attributes (missing keys read as None)."""

from __future__ import annotations

from typing import Any


class _dict(dict):  # noqa: N801 - mirrors frappe._dict
	__slots__ = ()

	def __getattr__(self, key: str) -> Any:
		if key.startswith("__"):
			raise AttributeError(key)
		return self.get(key)

	def __setattr__(self, key: str, value: Any) -> None:
		self[key] = value

	def __delattr__(self, key: str) -> None:
		try:
			del self[key]
		except KeyError as exc:
			raise AttributeError(key) from exc

	def __getstate__(self) -> dict:
		return dict(self)

	def __setstate__(self, state: dict) -> None:
		self.update(state)

	def copy(self) -> _dict:
		return _dict(dict.copy(self))

	def update(self, *args: Any, **kwargs: Any) -> _dict:  # type: ignore[override]
		super().update(*args, **kwargs)
		return self
