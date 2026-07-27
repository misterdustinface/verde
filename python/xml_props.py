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
import xml.etree.ElementTree as ET
from typing import Any


def sanitize_name(name: str) -> str:
    """Make a Roblox Name safe for the filesystem."""
    invalid = '<>:"/\\|?*'
    for char in invalid:
        name = name.replace(char, "_")
    name = name.strip()
    return name or "Unnamed"


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


def decode_tags_from_prop(prop: ET.Element) -> list[str]:
    """
    Decode Tags from either BinaryString (null-separated UTF-8) or
    string/ProtectedString (comma or null separated). Returns [] on failure.
    """
    if prop.tag == "BinaryString":
        raw = (prop.text or "").replace("\n", "").replace(" ", "")
        try:
            data = base64.b64decode(raw)
            return [t.decode("utf-8", errors="replace") for t in data.split(b"\0") if t]
        except Exception:
            return []
    text = prop.text or ""
    return [t.strip() for t in text.replace("\0", ",").split(",") if t.strip()]
