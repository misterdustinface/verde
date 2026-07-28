#!/usr/bin/env python3
"""
Shared helpers for walking extracted trees and reading/writing properties.

Used by the features (search, set_replace, tags) so the meta JSON layout is
handled in one place. Also hosts small pure CLI helpers (e.g. interactive
prompts) that are shared across feature CLIs.

Machine-local metadata
----------------------
The XML `referent` attribute is a serialization-time ID local to one .rbxlx
file / one Studio session. It is useful for matching and for exact Ref
re-emission on the same machine, but it churns across saves and must not be
checked into version control.

Shared meta files (*.robloxmeta.json) therefore never contain a top-level
"Referent" key. When a Referent is known it is written to a sibling
*.robloxmeta.local.json (gitignored). load_meta_merged() overlays the local
file so import / Live Sync / search still see the value when present.

AI agent notes
--------------
The top-level directory `.ai` is reserved for notes written by AI agents
working on an extracted tree. It is never imported into Roblox Studio and is
never wiped by export. See AI_NOTES_DIRNAME / is_under_ai_notes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


# Keys that belong only in the machine-local sibling file.
LOCAL_META_KEYS = frozenset({"Referent"})

LOCAL_META_SUFFIX = ".robloxmeta.local.json"
SHARED_META_SUFFIX = ".robloxmeta.json"

# Top-level directory reserved for AI agent notes (never imported into Studio,
# never wiped by export). Starts with '.' so process_directory already skips it;
# helpers make the exclusion explicit for walkers and cleanups.
AI_NOTES_DIRNAME = ".ai"


def is_under_ai_notes(path: Path, root: Path) -> bool:
    """True if *path* is the AI notes dir or any descendant (relative to *root*)."""
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return bool(rel.parts) and rel.parts[0] == AI_NOTES_DIRNAME


def load_meta(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def local_meta_path(shared_meta_path: Path) -> Path:
    """Return the machine-local sibling path for a shared .robloxmeta.json."""
    name = shared_meta_path.name
    if name == ".robloxmeta.json":
        return shared_meta_path.with_name(".robloxmeta.local.json")
    if name.endswith(SHARED_META_SUFFIX):
        # e.g. Constants.module.robloxmeta.json → Constants.module.robloxmeta.local.json
        stem = name[: -len(SHARED_META_SUFFIX)]
        return shared_meta_path.with_name(stem + LOCAL_META_SUFFIX)
    # Fallback: append
    return shared_meta_path.with_suffix(shared_meta_path.suffix + ".local")


def load_local_meta(shared_meta_path: Path) -> dict[str, Any]:
    """Load the machine-local sibling if it exists; else empty dict."""
    local_path = local_meta_path(shared_meta_path)
    if not local_path.is_file():
        return {}
    data = load_meta(local_path)
    return data if isinstance(data, dict) else {}


def save_local_meta(shared_meta_path: Path, local: dict[str, Any]) -> None:
    """Write only LOCAL_META_KEYS to the sibling file. Deletes the file if empty."""
    local_path = local_meta_path(shared_meta_path)
    payload = {k: v for k, v in local.items() if k in LOCAL_META_KEYS and v}
    if not payload:
        if local_path.is_file():
            try:
                local_path.unlink()
            except OSError:
                pass
        return
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def save_meta(path: Path, meta: dict[str, Any]) -> None:
    """Write shared meta + machine-local sibling.

    LOCAL_META_KEYS (e.g. Referent) are never written into the shared file.
    If they are present on the in-memory dict they are migrated into the
    *.robloxmeta.local.json sibling so a set/tags pass on an old tree does
    not silently drop them.
    """
    shared, local = split_local_keys(meta)
    path.write_text(json.dumps(shared, indent=2), encoding="utf-8")
    # Also preserve any local keys that were on the in-memory meta (e.g. an
    # old shared Referent loaded via walk_metas, or a value from the sibling).
    # If the caller already has a local sibling with the same value this is a
    # no-op rewrite; if the value only lived on shared, this migrates it.
    if local:
        save_local_meta(path, local)
    else:
        # Don't delete an existing local sibling just because this save didn't
        # carry the key — the in-memory dict may have been a partial update.
        # Callers that intentionally clear Referent should call save_local_meta
        # themselves with an empty payload.
        pass


def load_meta_merged(shared_meta_path: Path) -> dict[str, Any] | None:
    """Load shared meta and overlay machine-local keys (local wins).

    Backward compatible: if an old shared file still contains "Referent",
    it is used when no local sibling exists.
    """
    shared = load_meta(shared_meta_path)
    if shared is None:
        return None
    local = load_local_meta(shared_meta_path)
    if not local:
        return shared
    merged = dict(shared)
    for k, v in local.items():
        if k in LOCAL_META_KEYS and v:
            merged[k] = v
    return merged


def split_local_keys(meta: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (shared_dict, local_dict) with LOCAL_META_KEYS moved to local."""
    shared: dict[str, Any] = {}
    local: dict[str, Any] = {}
    for k, v in meta.items():
        if k in LOCAL_META_KEYS:
            if v:
                local[k] = v
        else:
            shared[k] = v
    return shared, local


def walk_metas(root: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Yield (shared_meta_path, merged_meta) for every .robloxmeta.json under root.

    Merged meta includes any machine-local Referent so matching continues to
    work on the machine that owns the .local.json files.

    Paths under the top-level AI agent notes directory (`.ai`) are skipped so
    notes never become import candidates.
    """
    for p in root.rglob("*.robloxmeta.json"):
        # Defensive: local siblings end in .robloxmeta.local.json and should not
        # match the glob, but skip them explicitly if a naming collision appears.
        if p.name.endswith(LOCAL_META_SUFFIX):
            continue
        if is_under_ai_notes(p, root):
            continue
        meta = load_meta_merged(p)
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


def prompt_choices(variants: list[tuple[str, int]], label: str) -> list[str]:
    """Present numbered list of (value, count) and return the chosen exact values.

    Shared interactive helper used by tags and set_replace CLIs when case-
    insensitive discovery finds multiple original-cased variants.
    """
    print(f"\nAmbiguous {label} (differ only by case):")
    for i, (val, count) in enumerate(variants, 1):
        print(f"  {i}. {val!r}  ({count} instance(s))")
    print("  a. all of the above")
    print("  n. none / cancel")
    while True:
        try:
            raw = input("Choose number(s), 'a', or 'n' [n]: ").strip().lower() or "n"
        except EOFError:
            return []
        if raw in ("n", "none", "cancel", ""):
            return []
        if raw in ("a", "all"):
            return [v for v, _ in variants]
        chosen: list[str] = []
        ok = True
        for part in raw.replace(",", " ").split():
            if not part.isdigit():
                ok = False
                break
            idx = int(part)
            if not (1 <= idx <= len(variants)):
                ok = False
                break
            chosen.append(variants[idx - 1][0])
        if ok and chosen:
            # preserve order, unique
            seen: set[str] = set()
            ordered: list[str] = []
            for c in chosen:
                if c not in seen:
                    seen.add(c)
                    ordered.append(c)
            return ordered
        print("  Invalid choice; try again.")
