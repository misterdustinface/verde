#!/usr/bin/env python3
"""
Shared helpers for walking extracted trees and reading/writing properties.

Used by the features (search, set_replace, tags) so the meta JSON layout is
handled in one place.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


def load_meta(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_meta(path: Path, meta: dict[str, Any]) -> None:
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def walk_metas(root: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Yield (meta_path, meta) for every .robloxmeta.json under root."""
    for p in root.rglob("*.robloxmeta.json"):
        meta = load_meta(p)
        if meta:
            yield p, meta


def get_prop_value(meta: dict[str, Any], prop_name: str) -> Any:
    """Look up a property value from top-level flat or structured Properties."""
    if prop_name in meta and not isinstance(meta[prop_name], dict):
        return meta[prop_name]
    props = meta.get("Properties") or {}
    if prop_name in props:
        structured = props[prop_name]
        if isinstance(structured, dict):
            return structured.get("value")
        return structured
    return None


def _infer_xml_type(value: str) -> str:
    low = value.lower()
    if low in ("true", "false"):
        return "bool"
    try:
        int(value)
        return "int"
    except ValueError:
        pass
    try:
        float(value)
        return "float"
    except ValueError:
        pass
    return "string"


def set_prop_value(
    meta: dict[str, Any],
    prop_name: str,
    new_value: str,
    only_if_old: str | None = None,
) -> bool:
    """Set prop_name to new_value in both flat and structured forms.

    If only_if_old is given, the change happens only when the current value
    equals only_if_old (string comparison). Returns True if anything changed.

    Complex properties (those whose structured form uses a "children" dict,
    e.g. Vector3, CFrame, Color3, NumberSequence) are refused — only scalar /
    string-like properties can be set safely via this helper.
    """
    changed = False
    current = get_prop_value(meta, prop_name)

    if only_if_old is not None:
        if current is None or str(current) != only_if_old:
            return False

    # Structured Properties map — refuse complex (children) forms
    props = meta.setdefault("Properties", {})
    if not isinstance(props, dict):
        props = {}
        meta["Properties"] = props

    if prop_name in props:
        structured = props[prop_name]
        if isinstance(structured, dict) and "children" in structured:
            # Cannot safely overwrite a complex property with a scalar string
            return False
        if isinstance(structured, dict):
            old_val = structured.get("value")
            if (str(old_val) if old_val is not None else "") != new_value:
                structured["value"] = new_value
                changed = True
        else:
            if str(structured) != new_value:
                props[prop_name] = new_value
                changed = True
    else:
        # Create a new structured entry (scalar)
        props[prop_name] = {
            "type": _infer_xml_type(new_value),
            "value": new_value,
        }
        changed = True

    # Top-level flat (interesting props)
    if prop_name in meta and not isinstance(meta[prop_name], dict):
        if str(meta[prop_name]) != new_value:
            meta[prop_name] = new_value
            changed = True
    elif prop_name not in meta or isinstance(meta.get(prop_name), dict):
        # Keep flat in sync for newly created interesting-looking props
        meta[prop_name] = new_value
        changed = True

    return changed


def matches(
    meta: dict[str, Any],
    *,
    class_filter: str | None = None,
    name_filter: str | None = None,
    name_contains: str | None = None,
    tag_filter: str | None = None,
    prop_name: str | None = None,
    prop_contains: str | None = None,
) -> bool:
    if class_filter and str(meta.get("ClassName", "")).lower() != class_filter.lower():
        return False
    name = str(meta.get("Name", ""))
    if name_filter and name.lower() != name_filter.lower():
        return False
    if name_contains and name_contains.lower() not in name.lower():
        return False
    if tag_filter:
        tags = meta.get("Tags") or []
        if not any(str(t).lower() == tag_filter.lower() for t in tags):
            return False
    if prop_name:
        val = get_prop_value(meta, prop_name)
        if val is None:
            return False
        if prop_contains is not None and prop_contains.lower() not in str(val).lower():
            return False
    return True
