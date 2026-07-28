#!/usr/bin/env python3
"""
Shared pure helpers for Roblox .rbxlx property / name handling.

Extracted from extract.py and build.py so the structured property parser,
name sanitisation, and related utilities live in one place. Used by both
export and import paths to keep round-trips consistent and the codebase
smaller / more readable.
"""

from __future__ import annotations

import base64
import platform
import xml.etree.ElementTree as ET
from typing import Any


FS_CASE_INSENSITIVE = platform.system() in ("Darwin", "Windows")


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


def _decode_tags_text(text: str) -> list[str]:
    """Split a Tags string (comma or null separated) into a clean list."""
    return [t.strip() for t in text.replace("\0", ",").split(",") if t.strip()]


def _decode_tags_binary(raw: str) -> list[str]:
    """Decode a base64 BinaryString Tags value (null-separated UTF-8)."""
    cleaned = (raw or "").replace("\n", "").replace(" ", "")
    try:
        data = base64.b64decode(cleaned)
        return [t.decode("utf-8", errors="replace") for t in data.split(b"\0") if t]
    except Exception:
        return []


def decode_tags_from_prop(prop: ET.Element) -> list[str]:
    """
    Decode Tags from BinaryString, string/ProtectedString, or SharedString.
    Returns [] on failure or empty.
    """
    if prop.tag == "BinaryString":
        return _decode_tags_binary(prop.text or "")
    # SharedString may carry the payload as text or as a child.
    if prop.tag == "SharedString":
        if prop.text and prop.text.strip():
            return _decode_tags_text(prop.text)
        for child in prop:
            if child.text and child.text.strip():
                try:
                    return _decode_tags_binary(child.text)
                except Exception:
                    return _decode_tags_text(child.text)
        return []
    # string / ProtectedString / anything else with text
    return _decode_tags_text(prop.text or "")


def decode_tags_from_structured(structured: dict[str, Any]) -> list[str]:
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
        if isinstance(val, str) and val.strip():
            try:
                return _decode_tags_binary(val)
            except Exception:
                return _decode_tags_text(val)
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
