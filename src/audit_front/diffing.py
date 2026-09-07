"""Deciding whether the analyst actually changed anything.

Harder than `before != after`, for two reasons:

* The editors rebuild a full payload every render, turning absent keys into
  empty lists. Raw comparison would report "unsaved changes" the instant a
  stage loaded, training analysts to ignore the warning.
* A backend key the model renames (``id`` -> ``rec_id``) would look like an
  edit for the same reason.

So both sides are normalised through the stage's model first, and empty is
treated as equal to absent.
"""

from __future__ import annotations

from typing import Any

from .pipeline import StageSpec


def is_empty(value: Any) -> bool:
    """A missing key and an empty value mean the same thing to an analyst."""
    return value is None or value == "" or value == [] or value == {}


def canonical(spec: StageSpec, payload: dict[str, Any]) -> dict[str, Any]:
    """Normalise a payload through the stage's model before comparing."""
    try:
        return spec.model.model_validate(payload).model_dump(exclude_none=True)
    except Exception:
        return dict(payload)


def changed_fields(spec: StageSpec, before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Fields whose content genuinely differs, ignoring empty-vs-absent noise."""
    left, right = canonical(spec, before), canonical(spec, after)
    return sorted(
        key
        for key in set(left) | set(right)
        if not (is_empty(left.get(key)) and is_empty(right.get(key)))
        and left.get(key) != right.get(key)
    )


def has_changes(spec: StageSpec, before: dict[str, Any], after: dict[str, Any]) -> bool:
    return bool(changed_fields(spec, before, after))


def change_summary(spec: StageSpec, before: dict[str, Any], after: dict[str, Any]) -> str:
    """A short description of what changed, for the audit trail.

    Names fields and counts rather than dumping values:
    ``"changed: entity_filter (-3), reasoning (+1)"``.
    """
    fields = changed_fields(spec, before, after)
    if not fields:
        return "no effective change"

    left, right = canonical(spec, before), canonical(spec, after)
    parts: list[str] = []
    for field in fields[:4]:
        old, new = left.get(field), right.get(field)
        if isinstance(old, list) and isinstance(new, list):
            delta = len(new) - len(old)
            sign = f"+{delta}" if delta > 0 else str(delta) if delta else "reworded"
            parts.append(f"{field} ({sign})")
        else:
            parts.append(field)
    if len(fields) > 4:
        parts.append(f"and {len(fields) - 4} more")
    return "changed: " + ", ".join(parts)
