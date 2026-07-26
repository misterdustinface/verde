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
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from attributes import decode_attributes, encode_attributes_b64
from features.meta import walk_metas


_FS_CASE_INSENSITIVE = platform.system() in ("Darwin", "Windows")


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


def _sanitize_name(name: str) -> str:
    invalid = '<>:"/\\|?*'
    for char in invalid:
        name = name.replace(char, "_")
    name = name.strip()
    return name or "Unnamed"


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
        fs_base = _sanitize_name(raw_name)
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
        if p.get("name") != "Tags":
            continue
        if p.tag == "BinaryString":
            raw = (p.text or "").replace("\n", "").replace(" ", "")
            try:
                data = base64.b64decode(raw)
                return [t.decode("utf-8", errors="replace") for t in data.split(b"\0") if t]
            except Exception:
                return []
        text = p.text or ""
        return [t.strip() for t in text.replace("\0", ",").split(",") if t.strip()]
    return []


def _get_attributes(item: ET.Element) -> dict[str, Any]:
    props = item.find("Properties")
    if props is None:
        return {}
    for p in props:
        if p.get("name") == "AttributesSerialize" and p.tag == "BinaryString":
            return decode_attributes(p.text or "")
    return {}


def _parse_children(elem: ET.Element) -> dict[str, Any]:
    children: dict[str, Any] = {}
    for child in elem:
        if len(child) == 0 and not child.attrib:
            val: Any = child.text if child.text is not None else ""
        else:
            sub = _parse_children(child)
            if child.attrib:
                if not isinstance(sub, dict):
                    sub = {"_value": sub} if sub else {}
                sub = dict(sub)
                sub["_attrs"] = dict(child.attrib)
            val = sub if sub else (child.text if child.text is not None else "")

        if child.tag in children:
            existing = children[child.tag]
            if not isinstance(existing, list):
                children[child.tag] = [existing]
            children[child.tag].append(val)
        else:
            children[child.tag] = val
    return children


def _parse_property_element(prop: ET.Element) -> dict[str, Any]:
    tag = prop.tag
    result: dict[str, Any] = {"type": tag}

    if tag in (
        "string",
        "ProtectedString",
        "bool",
        "int",
        "int64",
        "float",
        "double",
        "token",
        "BinaryString",
        "Content",
        "SharedString",
        "Ref",
        "UniqueId",
        "BrickColor",
    ):
        result["value"] = prop.text if prop.text is not None else ""
        return result

    children = _parse_children(prop)
    if children:
        result["children"] = children
    else:
        result["value"] = prop.text if prop.text is not None else ""

    return result


def _current_structured_props(item: ET.Element) -> dict[str, Any]:
    full: dict[str, Any] = {}
    props_elem = item.find("Properties")
    if props_elem is None:
        return full
    for prop in list(props_elem):
        prop_name = prop.get("name")
        if not prop_name or prop_name in ("Source", "Tags", "AttributesSerialize"):
            continue
        full[prop_name] = _parse_property_element(prop)
    return full


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

    meta_props = meta.get("Properties") or {}
    current_props = _current_structured_props(item)
    if meta_props != current_props:
        return True

    special = {"ClassName", "Name", "Tags", "Attributes", "Properties", "Referent"}
    already = set(meta_props.keys()) | {"Source", "Tags", "AttributesSerialize"}
    for key, val in meta.items():
        if key in special or key in already:
            continue
        if not isinstance(val, (str, int, float, bool)):
            continue
        cur = current_props.get(key)
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

    _clear_properties(item)
    add_properties(item, meta, source=source)


def import_rbxlx(extracted_dir: str, output_rbxlx: str) -> None:
    input_path = Path(extracted_dir)
    if not input_path.is_dir():
        print(f"Error: Directory not found: {extracted_dir}")
        return

    out_path = Path(output_rbxlx)
    if not out_path.is_file():
        build_rbxlx(extracted_dir, output_rbxlx)
        return

    print(f"Importing changes from {extracted_dir} → existing {output_rbxlx}")

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

    updated = 0
    unchanged = 0
    skipped_no_match = 0
    skipped_clean = 0

    for meta_path, meta in walk_metas(input_path):
        rel = meta_path.relative_to(input_path)
        rel_str = str(rel).replace("\\", "/")
        source: str | None = None
        path_key: str | None = None
        base_for_script: str | None = None
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

        if manifest is not None and is_file_dirty is not None:
            any_dirty = False
            for r in related_rels:
                if is_file_dirty(input_path, r, manifest, rbxlx_mtime=rbxlx_mtime):
                    any_dirty = True
                    break
            if not any_dirty:
                skipped_clean += 1
                continue

        item: ET.Element | None = None
        ref = meta.get("Referent")
        if isinstance(ref, str) and ref in referent_map:
            item = referent_map[ref]
        elif path_key is not None and path_key in path_map:
            item = path_map[path_key]
        elif path_key == "":
            pass

        if item is None:
            print(f"  · no match for {rel} (skip; will not auto-create yet)")
            skipped_no_match += 1
            continue

        if not _needs_update(item, meta, source):
            unchanged += 1
            continue

        _apply_meta_to_item(item, meta, source=source)
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
    if skipped_no_match:
        print(f"  ({skipped_no_match} folder entries had no matching instance in the place)")
    print("Open the place in Studio (or re-open) to see the changes.")

    # Refresh manifest so the next verde-merge starts from a clean baseline.
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
            "CLI: verde-import."
        )
    )
    parser.add_argument("extracted_dir", help="Path to extracted Verde folder")
    parser.add_argument(
        "output_rbxlx",
        nargs="?",
        default="RebuiltPlace.rbxlx",
        help="Target .rbxlx path (created if missing; updated in place if present)",
    )
    args = parser.parse_args()
    import_rbxlx(args.extracted_dir, args.output_rbxlx)


if __name__ == "__main__":
    main()
