"""Small text helpers shared by backend output paths."""

from __future__ import annotations


def truncate_with_marker(
    value: object,
    max_chars: int,
    marker: str = "\n...[truncated]",
) -> str:
    """Truncate text without hiding that truncation happened."""
    if max_chars < 0:
        raise ValueError("max_chars must be non-negative")
    text = "" if value is None else str(value)
    if len(text) <= max_chars:
        return text
    if max_chars <= len(marker):
        return marker[:max_chars]
    return text[: max_chars - len(marker)].rstrip() + marker
