#!/usr/bin/env python3
"""
Shared pure helpers for Roblox .rbxlx property / name handling.

Extracted from extract.py and build.py so the structured property parser,
name sanitisation, script ClassName ↔ filesystem extension mapping, and
related utilities live in one place. Used by both export and import paths
to keep round-trips consistent and the codebase smaller / more readable.
"""

from __future__ import annotations

import base64
import platform
import xml.etree.ElementTree as ET
from typing import Any


FS_CASE_INSENSITIVE = platform.system() in ("Darwin", "Windows")

# Canonical script ClassName ↔ filesystem extension mapping.
# Single source of truth for export, import, bare-script discovery, and path_key
# stripping. Keep in sync with Luau scriptRelPath / metaRelPath stems.
SCRIPT_EXTENSIONS = (".lua", ".local.lua", ".module.lua")


def script_extension_for(class_name: str) -> str:
    """Return the filesystem extension for a script ClassName."""
    if class_name == "LocalScript":
        return ".local.lua"
    if class_name == "ModuleScript":
        return ".module.lua"
    return ".lua"


def parse_script_filename(name: str) -> tuple[str, str] | None:
    """Return (ClassName, instance_name) for a script filename, or None if not a script.

    Handles the three Verde extensions. The instance_name is the stem that should
    appear in hierarchy path_keys (type suffix already stripped).
    """
    if name.endswith(".local.lua"):
        return "LocalScript", name[: -len(".local.lua")]
    if name.endswith(".module.lua"):
        return "ModuleScript", name[: -len(".module.lua")]
    if name.endswith(".lua"):
        return "Script", name[: -len(".lua")]
    return None


def strip_script_type_stem(base: str) -> str:
    """Strip a trailing .module / .local type stem from a meta/script base name.

    Used when building hierarchy path_keys from companion meta filenames
    (Name.module.robloxmeta.json → Name).
    """
    if base.endswith(".module"):
        return base[: -len(".module")]
    if base.endswith(".local"):
        return base[: -len(".local")]
    return base


def sanitize_name(name: str) -> str:
    """Make a Roblox Name safe for the filesystem."""
    invalid = '<>:"/\\|?*'
    for char in invalid:
        name = name.replace(char, "_")
    name = name.strip()
    return name or "Unnamed"


def claim_unique_name(base: str, claimed: set[str]) -> str:
    """Return a unique filesystem name, mutating *claimed*.

    On case-insensitive filesystems the key is casefolded so Foo / foo
    cannot collide. The returned name is the first free variant
    (base, base_2, base_3, …).
    """
    name = base
    counter = 1
    key = name.casefold() if FS_CASE_INSENSITIVE else name
    while key in claimed:
        counter += 1
        name = f"{base}_{counter}"
        key = name.casefold() if FS_CASE_INSENSITIVE else name
    claimed.add(key)
    return name


def resolve_item_name(
    item: ET.Element,
    *,
    flat: dict[str, Any] | None = None,
    full_props: dict[str, Any] | None = None,
) -> str:
    """Resolve the display/Name of an Item, preferring the Name *property*.

    Studio treats the Name property as the source of truth; the Item@name
    attribute is often absent or lags. Preferring the property matches the
    historical extract fix (v0.5.3) and keeps export/import path maps aligned.

    When *flat* / *full_props* are already available (export path) they are
    consulted first to avoid a second Properties walk. Otherwise the element
    is inspected directly.
    """
    if flat is not None and isinstance(flat.get("Name"), str) and flat["Name"]:
        return flat["Name"]

    if full_props is not None:
        structured = full_props.get("Name")
        if isinstance(structured, dict):
            val = structured.get("value")
            if isinstance(val, str) and val:
                return val

    props = item.find("Properties")
    if props is not None:
        for p in props:
            if p.get("name") == "Name" and p.text:
                return p.text

    attr = item.get("name")
    if attr:
        return attr

    return "Unnamed"


def parse_children(elem: ET.Element) -> dict[str, Any]:
    """Recursively parse XML child elements into a nested dict structure."""
    children: dict[str, Any] = {}
    for child in elem:
        if len(child) == 0 and not child.attrib:
            val: Any = child.text if child.text is not None else ""
        else:
            sub = parse_children(child)
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


def parse_property_element(prop: ET.Element) -> dict[str, Any]:
    """Parse a single <Properties> child into the structured {type, value|children} form.

    Simple scalar types are stored as {type, value}. Types that may carry child
    elements (notably Content with a <url> child for MeshId / TextureID) keep
    the children structure when present so MeshParts and similar round-trip.
    """
    tag = prop.tag
    result: dict[str, Any] = {"type": tag}

    # Content / SharedString / Ref often use child elements (e.g. <url>…</url>)
    # in modern Studio XML. Prefer children when present so MeshId is not lost.
    if tag in ("Content", "SharedString", "Ref"):
        children = parse_children(prop)
        if children:
            result["children"] = children
            return result
        result["value"] = prop.text if prop.text is not None else ""
        return result

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
        "UniqueId",
        "BrickColor",
    ):
        result["value"] = prop.text if prop.text is not None else ""
        return result

    children = parse_children(prop)
    if children:
        result["children"] = children
    else:
        result["value"] = prop.text if prop.text is not None else ""

    return result


def parse_shared_strings(root: ET.Element) -> dict[str, str]:
    """Build md5 → base64-payload map from the root <SharedStrings> table.

    Studio places frequently store Tags (and some other long strings) as
    SharedString references whose real BinaryString-style content lives here.
    The key is the md5 attribute; the element text is the base64 of the value.
    """
    table: dict[str, str] = {}
    ss = root.find("SharedStrings")
    if ss is None:
        return table
    for child in ss:
        if child.tag != "SharedString":
            continue
        md5 = child.get("md5")
        if not md5:
            continue
        table[md5] = (child.text or "").strip()
    return table


def _decode_tags_text(text: str) -> list[str]:
    """Split a Tags string (comma or null separated) into a clean list."""
    return [t.strip() for t in text.replace("\0", ",").split(",") if t.strip()]


def _decode_tags_binary(raw: str) -> list[str]:
    """Decode a base64 BinaryString Tags value (null-separated UTF-8)."""
    cleaned = (raw or "").replace("\n", "").replace(" ", "")
    if not cleaned:
        return []
    try:
        data = base64.b64decode(cleaned)
        return [t.decode("utf-8", errors="replace") for t in data.split(b"\0") if t]
    except Exception:
        return []


def decode_tags_from_prop(
    prop: ET.Element,
    shared_strings: dict[str, str] | None = None,
) -> list[str]:
    """
    Decode Tags from BinaryString, string/ProtectedString, or SharedString.
    Returns [] on failure or empty.

    When the property is a SharedString, *shared_strings* (from
    parse_shared_strings) is used to resolve the md5 key to the real payload.
    The hash itself is never treated as tag data.
    """
    if prop.tag == "BinaryString":
        return _decode_tags_binary(prop.text or "")
    if prop.tag == "SharedString":
        key = (prop.text or "").strip()
        if not key:
            # Rare child form (legacy / non-standard)
            for child in prop:
                if child.text and child.text.strip():
                    try:
                        return _decode_tags_binary(child.text)
                    except Exception:
                        return _decode_tags_text(child.text)
            return []
        if shared_strings and key in shared_strings:
            return _decode_tags_binary(shared_strings[key])
        # Unknown / missing table entry → empty (do not decode the hash)
        return []
    # string / ProtectedString / anything else with text
    return _decode_tags_text(prop.text or "")


def decode_tags_from_structured(
    structured: dict[str, Any],
    shared_strings: dict[str, str] | None = None,
) -> list[str]:
    """
    Decode Tags from a structured property dict produced by parse_property_element.
    Handles BinaryString, string/ProtectedString, and SharedString forms.
    """
    if not isinstance(structured, dict):
        return []
    typ = structured.get("type")
    if typ == "BinaryString":
        return _decode_tags_binary(str(structured.get("value") or ""))
    if typ in ("string", "ProtectedString"):
        return _decode_tags_text(str(structured.get("value") or ""))
    if typ == "SharedString":
        val = structured.get("value")
        key = str(val).strip() if isinstance(val, str) else ""
        if key and shared_strings and key in shared_strings:
            return _decode_tags_binary(shared_strings[key])
        # children form (uncommon for Tags)
        children = structured.get("children")
        if isinstance(children, dict):
            for v in children.values():
                if isinstance(v, str) and v.strip():
                    try:
                        return _decode_tags_binary(v)
                    except Exception:
                        return _decode_tags_text(v)
                if isinstance(v, dict) and v.get("_value"):
                    s = str(v["_value"])
                    try:
                        return _decode_tags_binary(s)
                    except Exception:
                        return _decode_tags_text(s)
        return []
    val = structured.get("value")
    if isinstance(val, str) and val.strip():
        return _decode_tags_text(val)
    return []
