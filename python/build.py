#!/usr/bin/env python3
"""
verde build.py — primary feature (CLI: verde-import)

Rebuilds a .rbxlx place from an extracted folder tree produced by extract.py
(full rebuild), or applies changes from the extracted tree into an existing
.rbxlx (differential import).

verde-import is the command:

- If the target .rbxlx does not exist → full rebuild
- If the target .rbxlx exists → scan the verde folder, match instances (by Referent
  preferentially, then by hierarchy path), and apply Source / Properties / Tags /
  Attributes from the folder into the place file. Unmatched instances in the
  .rbxlx are left untouched. This enables iterative version-control workflows on
  an existing place without losing non-script content when using scripts-only
  extracts.

When a .verde/manifest.json is present, files whose simple numeric hash + mtime
match the recorded entry are skipped early (and mtime-wins is applied against
the .rbxlx). After a successful import the manifest is refreshed.

--force bypasses the clean / mtime-win skips so every matching folder entry is
considered for application (still only written when content actually differs
via _needs_update). Useful when timestamps have drifted or the place was
touched outside Verde.

Differential import deliberately skips redundant on-disk entries so they are
never applied into the place:
- Multiple metas sharing the same Referent → only one is kept.
- Multiple metas sharing the same UniqueId (from meta) → only one is kept.
- Uniquified paths (Name_N) when a bare Name sibling is also present and the
  _N entry has no distinct Referent → treated as leftover and skipped.
- A place Item is updated at most once per import run.

When a matched place Item already has a UniqueId, that value is preserved.
When meta would replace a non-empty place property (e.g. MeshId Content) with
a blank/empty value — common with older exports that lost Content/<url>
children — the place value is kept so valid meshes are not wiped.

Understands the full structured Properties map (all types) plus Tags and
Attributes so that round-trips are as lossless as possible.

For offline dirty push/pull against a .rbxlx without opening Studio, use
verde-merge. For live Studio updates, use verde-sync.
"""

from __future__ import annotations

import argparse
import base64
import json
import platform
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from attributes import decode_attributes, encode_attributes_b64
from features.meta import walk_metas
from xml_props import sanitize_name, parse_children, parse_property_element, decode_tags_from_prop


_FS_CASE_INSENSITIVE = platform.system() in ("Darwin", "Windows")
_UNIQUIFY_RE = re.compile(r"^(.+)_([0-9]+)$")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def load_meta(path: Path) -> dict[str, Any]:
    json_path = path / ".robloxmeta.json"
    if json_path.is_file():
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    legacy = path / ".robloxmeta"
    meta: dict[str, Any] = {}
    if legacy.is_file():
        for line in legacy.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                meta[k.strip()] = v.strip()
    return meta


def script_meta_for(script_file: Path) -> dict[str, Any]:
    candidate = script_file.parent / f"{script_file.stem}.robloxmeta.json"
    if candidate.is_file():
        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            pass
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

    if "children" in structured and structured["children"]:
        _emit_structured_children(el, structured["children"])
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

    already = set(full.keys()) | {"Source", "Tags", "AttributesSerialize"}
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

        if item.is_file() and (
            item.suffix == ".lua" or item.name.endswith((".local.lua", ".module.lua"))
        ):
            if item.name.endswith(".local.lua"):
                class_name = "LocalScript"
                fs_base = item.name[: -len(".local.lua")]
            elif item.name.endswith(".module.lua"):
                class_name = "ModuleScript"
                fs_base = item.name[: -len(".module.lua")]
            else:
                class_name = "Script"
                fs_base = item.stem

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
        if (
            (item.parent / f"{base}.lua").is_file()
            or (item.parent / f"{base}.local.lua").is_file()
            or (item.parent / f"{base}.module.lua").is_file()
        ):
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


def _resolve_item_name(item: ET.Element) -> str:
    attr = item.get("name")
    if attr:
        return attr
    props = item.find("Properties")
    if props is not None:
        for p in props:
            if p.get("name") == "Name" and p.text:
                return p.text
    return "Unnamed"


def _build_instance_maps(
    root: ET.Element,
) -> tuple[dict[str, ET.Element], dict[str, ET.Element]]:
    referent_map: dict[str, ET.Element] = {}
    path_map: dict[str, ET.Element] = {}
    taken: dict[int, set[str]] = {}

    def walk(item: ET.Element, parent: ET.Element | None, current_path: str) -> None:
        if item.tag != "Item":
            return

        raw_name = _resolve_item_name(item)
        fs_base = sanitize_name(raw_name)
        parent_id = id(parent) if parent is not None else 0
        if parent_id not in taken:
            taken[parent_id] = set()
        used = taken[parent_id]

        fs_name = fs_base
        counter = 1
        key = fs_name.casefold() if _FS_CASE_INSENSITIVE else fs_name
        while key in used:
            counter += 1
            fs_name = f"{fs_base}_{counter}"
            key = fs_name.casefold() if _FS_CASE_INSENSITIVE else fs_name
        used.add(key)

        full_path = f"{current_path}/{fs_name}" if current_path else fs_name
        path_map[full_path] = item

        ref = item.get("referent")
        if ref:
            referent_map[ref] = item

        for child in item:
            if child.tag == "Item":
                walk(child, item, full_path)

    for top in root.findall("Item"):
        walk(top, None, "")

    return referent_map, path_map


def _clear_properties(item: ET.Element) -> None:
    for props in list(item.findall("Properties")):
        item.remove(props)


def _get_source(item: ET.Element) -> str:
    props = item.find("Properties")
    if props is None:
        return ""
    for p in props:
        if p.get("name") == "Source":
            return p.text if p.text is not None else ""
    return ""


def _get_tags(item: ET.Element) -> list[str]:
    props = item.find("Properties")
    if props is None:
        return []
    for p in props:
        if p.get("name") == "Tags":
            return decode_tags_from_prop(p)
    return []


def _get_attributes(item: ET.Element) -> dict[str, Any]:
    props = item.find("Properties")
    if props is None:
        return {}
    for p in props:
        if p.get("name") == "AttributesSerialize" and p.tag == "BinaryString":
            return decode_attributes(p.text or "")
    return {}


def _get_unique_id(item: ET.Element) -> str | None:
    """Return the UniqueId property value already present on an Item, or None."""
    props = item.find("Properties")
    if props is None:
        return None
    for p in props:
        if p.get("name") == "UniqueId" and p.text:
            return p.text.strip()
    return None


def _meta_unique_id(meta: dict[str, Any]) -> str | None:
    """Return UniqueId value stored in a folder meta, if any."""
    props = meta.get("Properties") or {}
    structured = props.get("UniqueId")
    if isinstance(structured, dict):
        val = structured.get("value")
        return str(val).strip() if val is not None else None
    if isinstance(structured, str) and structured.strip():
        return structured.strip()
    return None


def _is_uniquified_path(path_key: str) -> tuple[bool, str]:
    """If the final path segment looks like Name_N, return (True, bare path)."""
    if not path_key:
        return False, path_key
    parts = path_key.split("/")
    last = parts[-1]
    m = _UNIQUIFY_RE.match(last)
    if not m:
        return False, path_key
    bare_last = m.group(1)
    bare = "/".join(parts[:-1] + [bare_last]) if len(parts) > 1 else bare_last
    return True, bare


def _current_structured_props(item: ET.Element) -> dict[str, Any]:
    full: dict[str, Any] = {}
    props_elem = item.find("Properties")
    if props_elem is None:
        return full
    for prop in list(props_elem):
        prop_name = prop.get("name")
        if not prop_name or prop_name in ("Source", "Tags", "AttributesSerialize"):
            continue
        full[prop_name] = parse_property_element(prop)
    return full


def _structured_is_blank(structured: Any) -> bool:
    """True when a structured property has no meaningful value.

    Covers plain empty text and Content/SharedString without a usable child
    (e.g. missing or empty <url>) — the form older broken MeshId exports take.
    """
    if structured is None:
        return True
    if not isinstance(structured, dict):
        return str(structured).strip() == ""
    children = structured.get("children")
    if isinstance(children, dict) and children:

        def _child_blank(v: Any) -> bool:
            if isinstance(v, dict):
                if v.get("_value") is not None and str(v.get("_value")).strip() != "":
                    return False
                # attrs-only or nested empties
                rest = {k: x for k, x in v.items() if k != "_attrs"}
                if not rest:
                    return True
                return all(_child_blank(x) for x in rest.values())
            if isinstance(v, list):
                return all(_child_blank(x) for x in v)
            return v is None or str(v).strip() == ""

        return all(_child_blank(v) for v in children.values())
    val = structured.get("value")
    return val is None or str(val).strip() == ""


def _merge_structured_props(
    place_props: dict[str, Any],
    meta_props: dict[str, Any],
) -> dict[str, Any]:
    """Overlay meta Properties onto place Properties for differential import.

    Place is the base. Meta wins for keys it carries, except when meta would
    replace a non-blank place value with a blank one. That protects MeshId /
    TextureID / SoundId (and similar) when importing older exports whose Content
    values were corrupted into empty strings.
    """
    merged = dict(place_props)
    for key, meta_val in meta_props.items():
        place_val = place_props.get(key)
        if place_val is not None and not _structured_is_blank(place_val) and _structured_is_blank(meta_val):
            continue
        merged[key] = meta_val
    return merged


def _needs_update(
    item: ET.Element,
    meta: dict[str, Any],
    source: str | None,
) -> bool:
    if "ClassName" in meta and str(meta["ClassName"]) != (item.get("class") or ""):
        return True
    if "Name" in meta and str(meta["Name"]) != _resolve_item_name(item):
        return True
    if "Referent" in meta and str(meta["Referent"]) != (item.get("referent") or ""):
        return True

    if source is not None and source != _get_source(item):
        return True

    meta_tags = meta.get("Tags")
    if meta_tags is None:
        meta_tags = []
    elif isinstance(meta_tags, str):
        meta_tags = [meta_tags] if meta_tags else []
    if list(meta_tags) != _get_tags(item):
        return True

    meta_attrs = meta.get("Attributes") or {}
    if meta_attrs != _get_attributes(item):
        return True

    # Compare against the merged view so blank meta MeshIds do not force a write
    place_props = _current_structured_props(item)
    meta_props = meta.get("Properties") or {}
    merged_props = _merge_structured_props(place_props, meta_props)
    if merged_props != place_props:
        return True

    special = {"ClassName", "Name", "Tags", "Attributes", "Properties", "Referent"}
    already = set(meta_props.keys()) | {"Source", "Tags", "AttributesSerialize"}
    for key, val in meta.items():
        if key in special or key in already:
            continue
        if not isinstance(val, (str, int, float, bool)):
            continue
        cur = place_props.get(key)
        if cur is None:
            return True
        if isinstance(cur, dict) and "value" in cur:
            if str(cur["value"]) != str(val):
                return True
        elif str(cur) != str(val):
            return True

    return False


def _apply_meta_to_item(
    item: ET.Element,
    meta: dict[str, Any],
    source: str | None = None,
) -> None:
    if "ClassName" in meta:
        item.set("class", str(meta["ClassName"]))
    if "Name" in meta:
        item.set("name", str(meta["Name"]))
    if "Referent" in meta:
        item.set("referent", str(meta["Referent"]))

    # Merge place Properties with meta. Blank/broken meta values (typical of
    # older MeshId exports that lost Content/<url>) do not overwrite good
    # place values. UniqueId on the place Item always wins.
    place_props = _current_structured_props(item)
    meta_props = dict(meta.get("Properties") or {})
    merged = _merge_structured_props(place_props, meta_props)
    existing_uid = _get_unique_id(item)
    if existing_uid is not None:
        merged["UniqueId"] = {"type": "UniqueId", "value": existing_uid}

    meta = dict(meta)
    meta["Properties"] = merged

    _clear_properties(item)
    add_properties(item, meta, source=source)


def _prefer_candidate(
    a: dict[str, Any],
    b: dict[str, Any],
    path_map: dict[str, ET.Element],
) -> dict[str, Any]:
    """Prefer the candidate whose path exists in the place, else non-uniquified name."""
    a_in_place = a["path_key"] in path_map if a["path_key"] else False
    b_in_place = b["path_key"] in path_map if b["path_key"] else False
    if a_in_place and not b_in_place:
        return a
    if b_in_place and not a_in_place:
        return b
    a_uni, _ = _is_uniquified_path(a["path_key"] or "")
    b_uni, _ = _is_uniquified_path(b["path_key"] or "")
    if a_uni and not b_uni:
        return b
    if b_uni and not a_uni:
        return a
    return a  # stable: keep first


def import_rbxlx(extracted_dir: str, output_rbxlx: str, force: bool = False) -> None:
    input_path = Path(extracted_dir)
    if not input_path.is_dir():
        print(f"Error: Directory not found: {extracted_dir}")
        return

    out_path = Path(output_rbxlx)
    if not out_path.is_file():
        build_rbxlx(extracted_dir, output_rbxlx)
        return

    print(f"Importing changes from {extracted_dir} → existing {output_rbxlx}")
    if force:
        print("  (--force: mtime-win / clean-manifest skips disabled)")

    manifest = None
    rbxlx_mtime = None
    try:
        from features.sync import load_manifest, is_file_dirty

        manifest = load_manifest(input_path)
        try:
            rbxlx_mtime = out_path.stat().st_mtime
        except OSError:
            pass
    except Exception:
        is_file_dirty = None  # type: ignore

    tree = ET.parse(str(out_path))
    root = tree.getroot()

    referent_map, path_map = _build_instance_maps(root)

    # --- Collect candidates (after dirty filter) ---
    candidates: list[dict[str, Any]] = []
    skipped_clean = 0

    for meta_path, meta in walk_metas(input_path):
        rel = meta_path.relative_to(input_path)
        rel_str = str(rel).replace("\\", "/")
        source: str | None = None
        path_key: str | None = None
        related_rels: list[str] = [rel_str]

        if meta_path.name == ".robloxmeta.json":
            path_key = str(rel.parent).replace("\\", "/")
            if path_key in (".", ""):
                path_key = ""
        else:
            base_for_script = meta_path.name[: -len(".robloxmeta.json")]
            script_file = None
            for cand in meta_path.parent.iterdir():
                if not cand.is_file():
                    continue
                if cand.stem == base_for_script and (
                    cand.suffix == ".lua"
                    or cand.name.endswith((".local.lua", ".module.lua"))
                ):
                    script_file = cand
                    break
            if script_file is not None:
                source = read_text(script_file)
                try:
                    related_rels.append(
                        str(script_file.relative_to(input_path)).replace("\\", "/")
                    )
                except ValueError:
                    pass
            path_key = str((rel.parent / base_for_script)).replace("\\", "/")

        if not force and manifest is not None and is_file_dirty is not None:
            any_dirty = False
            for r in related_rels:
                if is_file_dirty(input_path, r, manifest, rbxlx_mtime=rbxlx_mtime):
                    any_dirty = True
                    break
            if not any_dirty:
                skipped_clean += 1
                continue

        candidates.append(
            {
                "meta_path": meta_path,
                "rel": rel,
                "meta": meta,
                "source": source,
                "path_key": path_key or "",
                "ref": meta.get("Referent") if isinstance(meta.get("Referent"), str) else None,
                "uid": _meta_unique_id(meta),
            }
        )

    # --- Drop redundant disk entries (do not import them) ---
    # Prefer entries that map into the place, then non-uniquified names.
    by_ref: dict[str, dict[str, Any]] = {}
    by_uid: dict[str, dict[str, Any]] = {}
    path_keys_present = {c["path_key"] for c in candidates if c["path_key"]}
    kept: list[dict[str, Any]] = []
    skipped_redundant = 0

    for c in candidates:
        # Name_N leftover when bare Name is also a candidate and this entry
        # has no distinct Referent of its own → skip as redundant disk file.
        is_uni, bare = _is_uniquified_path(c["path_key"])
        if is_uni and bare in path_keys_present and not c["ref"]:
            print(f"  · skip redundant disk entry {c['rel']} (Name_N leftover of {bare})")
            skipped_redundant += 1
            continue

        if c["ref"]:
            prev = by_ref.get(c["ref"])
            if prev is not None:
                winner = _prefer_candidate(prev, c, path_map)
                if winner is prev:
                    print(f"  · skip redundant disk entry {c['rel']} (same Referent as {prev['rel']})")
                    skipped_redundant += 1
                    continue
                # Replace previous with this one; remove prev from kept
                print(f"  · skip redundant disk entry {prev['rel']} (same Referent as {c['rel']})")
                skipped_redundant += 1
                kept = [k for k in kept if k is not prev]
                by_ref[c["ref"]] = c
                if prev.get("uid"):
                    by_uid.pop(prev["uid"], None)
            else:
                by_ref[c["ref"]] = c

        if c["uid"]:
            prev = by_uid.get(c["uid"])
            if prev is not None and prev is not c:
                winner = _prefer_candidate(prev, c, path_map)
                if winner is prev:
                    print(f"  · skip redundant disk entry {c['rel']} (same UniqueId as {prev['rel']})")
                    skipped_redundant += 1
                    if c["ref"] and by_ref.get(c["ref"]) is c:
                        by_ref.pop(c["ref"], None)
                    continue
                print(f"  · skip redundant disk entry {prev['rel']} (same UniqueId as {c['rel']})")
                skipped_redundant += 1
                kept = [k for k in kept if k is not prev]
                by_uid[c["uid"]] = c
                if prev.get("ref") and by_ref.get(prev["ref"]) is prev:
                    by_ref.pop(prev["ref"], None)
            else:
                by_uid[c["uid"]] = c

        kept.append(c)

    # --- Apply kept candidates (each place Item at most once) ---
    updated = 0
    unchanged = 0
    skipped_no_match = 0
    applied_items: set[int] = set()  # id(item)

    for c in kept:
        meta = c["meta"]
        source = c["source"]
        path_key = c["path_key"]
        ref = c["ref"]

        item: ET.Element | None = None
        if ref and ref in referent_map:
            item = referent_map[ref]
        elif path_key and path_key in path_map:
            item = path_map[path_key]

        if item is None:
            print(f"  · no match for {c['rel']} (skip; will not auto-create yet)")
            skipped_no_match += 1
            continue

        item_id = id(item)
        if item_id in applied_items:
            print(f"  · skip {c['rel']} (place instance already updated this run)")
            skipped_redundant += 1
            continue

        # Safety net: keep the UniqueId already on the place Item.
        existing_uid = _get_unique_id(item)
        if existing_uid is not None:
            meta = dict(meta)
            props = dict(meta.get("Properties") or {})
            props["UniqueId"] = {"type": "UniqueId", "value": existing_uid}
            meta["Properties"] = props

        if not _needs_update(item, meta, source):
            unchanged += 1
            applied_items.add(item_id)
            continue

        _apply_meta_to_item(item, meta, source=source)
        applied_items.add(item_id)
        updated += 1

    if updated:
        ET.indent(tree, space="  ")
        tree.write(str(out_path), encoding="utf-8", xml_declaration=True)
        print(f"✓ Applied {updated} instance update(s) into {output_rbxlx}")
    else:
        print(f"✓ No content changes needed in {output_rbxlx}")

    if unchanged:
        print(f"  ({unchanged} matched instance(s) already up to date)")
    if skipped_clean:
        print(f"  ({skipped_clean} entry(ies) skipped — clean per manifest / mtime-win)")
    if skipped_redundant:
        print(f"  ({skipped_redundant} redundant disk entry(ies) skipped — Name_N / shared Referent or UniqueId)")
    if skipped_no_match:
        print(f"  ({skipped_no_match} folder entries had no matching instance in the place)")
    print("Open the place in Studio (or re-open) to see the changes.")

    try:
        from features.sync import write_manifest

        write_manifest(input_path, rbxlx_path=out_path)
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Import changes from a Verde extracted folder into an existing .rbxlx "
            "(or create the .rbxlx if it does not exist — full rebuild). "
            "CLI: verde-import. "
            "Use --force to ignore mtime-win / clean-manifest skips. "
            "Redundant on-disk entries (Name_N leftovers, shared Referent/UniqueId) "
            "are skipped so they are not imported into the place. "
            "Blank/broken meta Content values (e.g. old MeshId exports) do not "
            "overwrite valid place values."
        )
    )
    parser.add_argument("extracted_dir", help="Path to extracted Verde folder")
    parser.add_argument(
        "output_rbxlx",
        nargs="?",
        default="RebuiltPlace.rbxlx",
        help="Target .rbxlx path (created if missing; updated in place if present)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Force consideration of all matching folder files, bypassing the "
            "manifest clean-check and mtime-win logic that would otherwise skip "
            "files older than the target .rbxlx. Content is still only written "
            "when it actually differs. Redundant disk entries are still skipped. "
            "Blank meta Content values still do not overwrite valid place values."
        ),
    )
    args = parser.parse_args()
    import_rbxlx(args.extracted_dir, args.output_rbxlx, force=args.force)


if __name__ == "__main__":
    main()
