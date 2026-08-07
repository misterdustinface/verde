#!/usr/bin/env python3
"""
verde build.py — primary feature (CLI: verde-import)

Rebuilds a .rbxlx place from an extracted folder tree produced by extract.py
(full rebuild), or applies changes from the extracted tree into an existing
.rbxlx (differential import).

verde-import is the command:

- If the target .rbxlx does not exist → full rebuild
- If the target .rbxlx exists → scan the verde folder, match instances (by Referent
  preferentially, then by UniqueId property from shared meta, then by hierarchy
  path), and apply Source / Properties / Tags / Attributes from the folder into
  the place file. UniqueId matching prevents same-Name siblings from cross-applying
  Color / CFrame / other properties when machine-local Referent files are absent.

When a folder entry has no match in the place, missing intermediate parents are
recursively created as Folders (Name taken from the path segment; UniqueId left
for Studio). The leaf is then created under the now-guaranteed parent
(ClassName / Name / Referent / Source / Tags / Attributes from meta). This
supports both hand-added / AI-generated files that lack intermediate folders in
the place and deep trees whose parents were never exported.

Bare script files (.lua / .local.lua / .module.lua) that lack a companion
.robloxmeta.json are also discovered and treated as new candidates (defaults
invented from the filename). This matches full-rebuild behaviour and prevents
hand-added or AI-generated scripts from being silently ignored. The invented
Name is always written both as Item@name and as the Name property so Studio
preserves it (property is the source of truth; attribute alone can be reset
to ClassName).

Clean (manifest / mtime-win) only skips when the place *still has* a matching
Item. A disk entry that is absent from the place is always treated as a create
candidate, so additions of missing files happen by default (no --force needed).

After create/update, high-confidence renames and unmatched leftovers are handled:

- High-confidence rename (any ClassName): exactly one newly-created sibling of
  the same ClassName under the same parent (for scripts, identical Source is
  preferred when present) → the old Item is removed by default.
  Pass --no-rename to report only.
- Pure leftovers (unmatched place instances with no rename match) are removed
  by default, but only under parents that appear in the folder extract.
  Place content outside the exported tree is never pruned.
  Pass --no-delete to report only.

Scripts-only safety: when every candidate in the run is a Script / LocalScript /
ModuleScript (or when --scripts-only is passed), pure prune is limited to those
ClassNames so a normal scripts-only import does not wipe non-script content.
High-confidence renames still apply to any ClassName.

--scripts-only forces consideration of only script candidates and the scripts-only
prune safety. Useful when the extracted tree was produced with --all but only
scripts should be pushed back into the place.

Selective import (--root / --tag, or automatic from .verde/partial.json written
by a selective export):
- Only candidates under the given root path (or carrying the given tag, plus
  ancestors) are considered.
- Prune and scripts-only safety are recomputed against the filtered set so
  content outside the selective scope is never touched.
- Hierarchy mirroring from selective export already makes path-based grafting
  correct; the partial manifest and CLI flags make the scope explicit.

When a .verde/manifest.json is present, files whose simple numeric hash + mtime
match the recorded entry are skipped for writing *only when the place still has
the match* (and mtime-wins is applied against the .rbxlx). After a successful
import the manifest is refreshed.

--force bypasses the clean / mtime-win skips so every matching folder entry is
considered for application (still only written when content actually differs
via _needs_update). Useful when timestamps have drifted or the place was
touched outside Verde.

Differential import deliberately skips redundant on-disk entries so they are
never applied into the place:
- Multiple metas sharing the same Referent → only one is kept.
- Multiple metas sharing the same UniqueId (from meta) → only one is kept.
- Uniquified paths (Name_N) when a bare Name sibling is also present and the
  _N entry has no distinct Referent or UniqueId → treated as leftover and skipped.
- A place Item is updated at most once per import run.

Property merge on differential apply:
- Place is the base; meta overlays keys it carries.
- By default meta wins even when blank (intentional MeshId clears propagate).
- --preserve-content: blank/broken meta Content does not overwrite non-blank
  place values — recovery only for older exports that lost Content/<url>.
- UniqueId on the place Item is always preserved.

Understands the full structured Properties map (all types) plus Tags and
Attributes so that round-trips are as lossless as possible.

Referent is read from the machine-local sibling (*.robloxmeta.local.json) when
present; shared .robloxmeta.json files never contain it.

The top-level `.ai` directory (AI agent notes) is never walked for candidates
and is never imported into the place.

For offline dirty push/pull against a .rbxlx without opening Studio, use
verde-merge. For live Studio updates, use verde-sync.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from attributes import decode_attributes, encode_attributes_b64
from features.meta import AI_NOTES_DIRNAME, is_under_ai_notes, load_meta_merged, walk_metas
from xml_props import (
    SCRIPT_EXTENSIONS,
    claim_unique_name,
    decode_tags_from_prop,
    parse_children,
    parse_property_element,
    parse_script_filename,
    parse_shared_strings,
    resolve_item_name,
    sanitize_name,
    script_extension_for,
    strip_script_type_stem,
)


_UNIQUIFY_RE = re.compile(r"^(.+)_([0-9]+)$")
_SCRIPT_CLASSES = frozenset({"Script", "LocalScript", "ModuleScript"})
_LEFTOVER_PRINT_LIMIT = 20

# Identity CoordinateFrame / CFrame components. Incomplete or all-zero rotation
# matrices cause the Roblox engine to place instances at extreme Y (commonly
# ~0, -100000, 0) and lose orientation. Fill missing keys and replace singular
# matrices before emit so corrupted or partial metas never produce the sentinel.
_COORDINATE_FRAME_IDENTITY = {
    "X": "0",
    "Y": "0",
    "Z": "0",
    "R00": "1",
    "R01": "0",
    "R02": "0",
    "R10": "0",
    "R11": "1",
    "R12": "0",
    "R20": "0",
    "R21": "0",
    "R22": "1",
}


def _normalize_coordinate_frame_children(children: dict[str, Any] | None) -> dict[str, Any]:
    """Fill missing CoordinateFrame components with identity; replace all-zero rotation.

    Incomplete or singular matrices cause the Roblox engine to place instances at
    extreme positions (commonly ~0, -100000, 0) and lose orientation. Identity at
    the given (or origin) position is the safe fallback requested for corrupted
    assets (favourite chair / sub-models).
    """
    if not isinstance(children, dict):
        return dict(_COORDINATE_FRAME_IDENTITY)
    out = dict(children)
    for k, v in _COORDINATE_FRAME_IDENTITY.items():
        if k not in out or out[k] is None or str(out[k]).strip() == "":
            out[k] = v
    try:
        rot_vals = [
            float(out[k])
            for k in (
                "R00",
                "R01",
                "R02",
                "R10",
                "R11",
                "R12",
                "R20",
                "R21",
                "R22",
            )
        ]
        if all(abs(v) < 1e-12 for v in rot_vals):
            for k, v in _COORDINATE_FRAME_IDENTITY.items():
                if k.startswith("R"):
                    out[k] = v
    except (TypeError, ValueError):
        for k, v in _COORDINATE_FRAME_IDENTITY.items():
            if k.startswith("R"):
                out[k] = v
    return out


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def load_meta(path: Path) -> dict[str, Any]:
    """Load shared + machine-local meta for a directory (folder instances)."""
    json_path = path / ".robloxmeta.json"
    if json_path.is_file():
        merged = load_meta_merged(json_path)
        if merged is not None:
            return merged

    legacy = path / ".robloxmeta"
    meta: dict[str, Any] = {}
    if legacy.is_file():
        for line in legacy.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                meta[k.strip()] = v.strip()
    return meta


def script_meta_for(script_file: Path) -> dict[str, Any]:
    """Load shared + machine-local meta for a script companion file."""
    candidate = script_file.parent / f"{script_file.stem}.robloxmeta.json"
    if candidate.is_file():
        merged = load_meta_merged(candidate)
        if merged is not None:
            return merged
    return {}


def _emit_structured_children(parent_el: ET.Element, children: dict[str, Any]) -> None:
    for child_name, child_val in children.items():
        items = child_val if isinstance(child_val, list) else [child_val]
        for val in items:
            if isinstance(val, dict):
                child_el = ET.SubElement(parent_el, child_name)
                attrs = val.get("_attrs")
                if attrs and isinstance(attrs, dict):
                    for ak, av in attrs.items():
                        child_el.set(ak, str(av))
                remaining = {k: v for k, v in val.items() if k != "_attrs"}
                if remaining:
                    if set(remaining.keys()) == {"_value"}:
                        child_el.text = str(remaining["_value"]) if remaining["_value"] is not None else ""
                    else:
                        _emit_structured_children(child_el, remaining)
            else:
                child_el = ET.SubElement(parent_el, child_name)
                child_el.text = str(val) if val is not None else ""


def _emit_property(props_elem: ET.Element, name: str, structured: dict[str, Any]) -> None:
    tag = structured.get("type", "string")
    el = ET.SubElement(props_elem, tag)
    el.set("name", name)

    children = structured.get("children")
    if tag in ("CoordinateFrame", "CFrame") and children is not None:
        children = _normalize_coordinate_frame_children(
            children if isinstance(children, dict) else None
        )

    if children:
        _emit_structured_children(el, children)
    else:
        val = structured.get("value")
        el.text = str(val) if val is not None else ""


def add_properties(
    item_elem: ET.Element,
    meta: dict[str, Any],
    source: str | None = None,
) -> None:
    props = ET.SubElement(item_elem, "Properties")

    if source is not None:
        el = ET.SubElement(props, "ProtectedString")
        el.set("name", "Source")
        el.text = source

    full = meta.get("Properties") or {}
    tags = meta.get("Tags") or []
    if isinstance(tags, str):
        tags = [tags] if tags else []

    # Studio treats the Name *property* as source of truth. Item@name alone can
    # be ignored / reset to ClassName on open. Always emit the property when we
    # know the intended name (from top-level meta or from structured Properties).
    name_val = meta.get("Name")
    if name_val is None and isinstance(full.get("Name"), dict):
        name_val = full["Name"].get("value")
    if name_val is not None and str(name_val) and "Name" not in full:
        el = ET.SubElement(props, "string")
        el.set("name", "Name")
        el.text = str(name_val)

    for prop_name, structured in full.items():
        if prop_name == "Source":
            continue
        if prop_name == "AttributesSerialize":
            continue
        if prop_name == "Tags" and tags:
            continue
        if not isinstance(structured, dict) or "type" not in structured:
            el = ET.SubElement(props, "string")
            el.set("name", prop_name)
            el.text = str(structured)
            continue
        _emit_property(props, prop_name, structured)

    if tags:
        if isinstance(tags, list) and tags:
            raw = b"\0".join(t.encode("utf-8") for t in tags)
            b64 = base64.b64encode(raw).decode("ascii")
            el = ET.SubElement(props, "BinaryString")
            el.set("name", "Tags")
            el.text = b64
        elif isinstance(tags, str) and tags:
            el = ET.SubElement(props, "string")
            el.set("name", "Tags")
            el.text = tags

    attributes = meta.get("Attributes")
    if attributes:
        b64 = encode_attributes_b64(attributes)
        el = ET.SubElement(props, "BinaryString")
        el.set("name", "AttributesSerialize")
        el.text = b64

    already = set(full.keys()) | {"Source", "Tags", "AttributesSerialize", "Name"}
    for key, val in meta.items():
        if key in ("ClassName", "Name", "Tags", "Attributes", "Properties", "Referent") or key in already:
            continue
        if isinstance(val, (str, int, float, bool)):
            if isinstance(val, bool) or (isinstance(val, str) and val.lower() in ("true", "false")):
                tag = "bool"
                text = str(val).lower()
            elif isinstance(val, int):
                tag = "int"
                text = str(val)
            elif isinstance(val, float):
                tag = "float"
                text = str(val)
            else:
                tag = "string"
                text = str(val)
            el = ET.SubElement(props, tag)
            el.set("name", key)
            el.text = text


def process_directory(dir_path: Path, parent_element: ET.Element) -> None:
    for item in sorted(dir_path.iterdir()):
        if item.name.startswith("."):
            continue
        if item.name == AI_NOTES_DIRNAME:
            continue

        if item.is_file():
            parsed = parse_script_filename(item.name)
            if parsed is not None:
                class_name, fs_base = parsed
                meta = script_meta_for(item)
                class_name = meta.get("ClassName", class_name)
                xml_name = meta.get("Name", fs_base)

                item_elem = ET.SubElement(parent_element, "Item")
                item_elem.set("class", class_name)
                item_elem.set("name", xml_name)
                if "Referent" in meta:
                    item_elem.set("referent", str(meta["Referent"]))

                source = read_text(item)
                add_properties(item_elem, meta, source=source)

                children_dir = item.parent / fs_base
                if children_dir.is_dir() and children_dir != dir_path:
                    process_directory(children_dir, item_elem)
                continue

        if not item.is_dir():
            continue

        base = item.name
        if any((item.parent / f"{base}{ext}").is_file() for ext in SCRIPT_EXTENSIONS):
            continue

        meta = load_meta(item)
        class_name = meta.get("ClassName", "Folder")
        name = meta.get("Name", item.name)

        item_elem = ET.SubElement(parent_element, "Item")
        item_elem.set("class", class_name)
        item_elem.set("name", name)
        if "Referent" in meta:
            item_elem.set("referent", str(meta["Referent"]))

        add_properties(item_elem, meta)
        process_directory(item, item_elem)


def build_rbxlx(input_dir: str, output_rbxlx: str = "RebuiltPlace.rbxlx") -> None:
    input_path = Path(input_dir)
    if not input_path.is_dir():
        print(f"Error: Directory not found: {input_dir}")
        return

    print(f"Building .rbxlx from: {input_dir}")

    root = ET.Element("roblox")
    root.set("version", "4")
    ET.SubElement(root, "ExternalScriptReferences")
    ET.SubElement(root, "ExternalAssets")

    process_directory(input_path, root)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(output_rbxlx, encoding="utf-8", xml_declaration=True)

    print(f"✓ Successfully created: {output_rbxlx}")
    print("You can now open this file in Roblox Studio.")


def _build_instance_maps(
    root: ET.Element,
) -> tuple[
    dict[str, ET.Element],
    dict[str, ET.Element],
    dict[ET.Element, ET.Element | None],
    dict[str, ET.Element],
]:
    """Return (referent_map, path_map, parent_map, unique_id_map).

    parent_map maps every Item element to its parent Item (or None for top-level).
    unique_id_map maps the UniqueId *property* value to the Item (first wins).
    UniqueId is stable across Studio sessions and lives in shared meta, so it is
    the correct secondary match key when Referent (machine-local) is absent —
    preventing same-Name siblings from cross-applying Color/CFrame/etc.
    """
    referent_map: dict[str, ET.Element] = {}
    path_map: dict[str, ET.Element] = {}
    parent_map: dict[ET.Element, ET.Element | None] = {}
    unique_id_map: dict[str, ET.Element] = {}
    taken: dict[int, set[str]] = {}

    def walk(item: ET.Element, parent: ET.Element | None, current_path: str) -> None:
        if item.tag != "Item":
            return

        raw_name = resolve_item_name(item)
        fs_base = sanitize_name(raw_name)
        parent_id = id(parent) if parent is not None else 0
        if parent_id not in taken:
            taken[parent_id] = set()
        used = taken[parent_id]

        fs_name = claim_unique_name(fs_base, used)

        full_path = f"{current_path}/{fs_name}" if current_path else fs_name
        path_map[full_path] = item
        parent_map[item] = parent

        ref = item.get("referent")
        if ref:
            referent_map[ref] = item

        # UniqueId property (stable, shared meta) — secondary match key
        props_el = item.find("Properties")
        if props_el is not None:
            for p in props_el:
                if p.get("name") == "UniqueId" and p.text and p.text.strip():
                    uid = p.text.strip()
                    if uid not in unique_id_map:
                        unique_id_map[uid] = item
                    break

        for child in item:
            if child.tag == "Item":
                walk(child, item, full_path)

    for top in root.findall("Item"):
        walk(top, None, "")

    return referent_map, path_map, parent_map, unique_id_map
