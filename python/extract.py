#!/usr/bin/env python3
"""
verde extract.py — primary feature (CLI: verde-export)

Exports a Roblox .rbxlx place into a folder hierarchy that is easy to version-control,
search, and edit.

- Scripts → .lua / .local.lua / .module.lua (Source content)
- All other Instances → folder + .robloxmeta.json (ClassName, Name, Tags, Attributes, ALL properties)
- Hierarchy is preserved.
- Full property type support for successful round-trips.
- Default: only the cascading directories that lead to scripts (use --all for full hierarchy).
- Empty directories are never retained.
- Name collision handling:
  - Within a single export, sibling instances that share the same Name still get
    numeric suffixes (Name, Name_2, …) so both can live on disk.
  - On case-insensitive filesystems (macOS / Windows) uniqueness is also
    case-insensitive so a "Foo" / "foo" pair cannot overwrite each other.
  - Paths that already exist on disk from a previous export are *reused* (no new
    digit suffix). Content is compared: identical files are left untouched;
    differing files are overwritten by default, or prompted with --interactive.
  - After re-export, stale uniquified siblings (Name_N left when the collision
    disappeared) are removed so the tree does not accumulate orphans.
- After a successful export a .verde/manifest.json is written so later merge/import
  can skip unchanged files (simple adler32 hash + mtime).
- Selective: --root PATH and/or --tag TAG limit the exported tree.
- Machine-local Referent is written to *.robloxmeta.local.json (gitignored),
  never into the shared .robloxmeta.json that is checked into VCS.
- A top-level .gitignore is created/updated so *.robloxmeta.local.json is ignored.
- The top-level `.ai` directory is reserved for AI agent notes: it is created
  (with a short README) if missing, and is never pruned, cleaned, or overwritten
  by export.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from attributes import decode_attributes
from features.meta import (
    AI_NOTES_DIRNAME,
    LOCAL_META_KEYS,
    is_under_ai_notes,
    local_meta_path,
    save_local_meta,
    split_local_keys,
)
from interesting import load_interesting_props
from xml_props import (
    FS_CASE_INSENSITIVE,
    SCRIPT_EXTENSIONS,
    claim_unique_name,
    decode_tags_from_prop,
    decode_tags_from_structured,
    parse_property_element,
    parse_shared_strings,
    resolve_item_name,
    sanitize_name,
    script_extension_for,
)


# Pattern that must appear in the extracted folder's .gitignore so machine-local
# Referent files are never committed. Also used when creating a fresh file.
_LOCAL_META_GITIGNORE_PATTERN = "*.robloxmeta.local.json"

_DEFAULT_GITIGNORE = """\
# Verde — machine-local metadata (Referent and other session-only data).
# These files are useful on the machine that produced the export but churn
# across Studio saves and must not be checked into version control.
*.robloxmeta.local.json
"""

_AI_NOTES_README = """\
# AI Agent Notes (`.ai/`)

This top-level directory is reserved for **AI agent notes** on a Verde-extracted
project tree. It exists whether or not the project already contains any
Verde-specific notes, plans, or agent history.

## What this folder is for

- Scratchpads, observations, architecture notes, and decisions made while an
  AI agent analyses or edits this tree.
- Cross-session context that helps future agents (or the same agent later)
  understand the project without re-deriving everything from scratch.
- Anything that improves long-term project understanding and is **not** Roblox
  instance data (scripts, properties, tags, attributes, hierarchy).

You are encouraged to leave **valuable, durable notes** here. Prefer concise
summaries of structure, non-obvious conventions, known pitfalls, and open
questions over ephemeral chat logs. Future analysis benefits from durable
context more than from raw transcripts.

## Guarantees from Verde

- **`verde-import` / `verde-merge`** never import anything under `.ai/` into a
  place file or into Roblox Studio.
- **`verde-export`** never deletes, prunes, or overwrites the contents of this
  directory. Re-exports leave your notes intact.
- Files here are not tracked in `.verde/manifest.json`.

This folder is intentionally outside the Roblox instance tree so agent context
stays on disk with the project and stays out of Studio.
"""


def extract_properties(
    item: ET.Element,
    interesting: set[str],
    shared_strings: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[str], dict[str, Any], dict[str, Any]]:
    flat: dict[str, Any] = {}
    tags: list[str] = []
    full: dict[str, Any] = {}
    attributes: dict[str, Any] = {}

    props_elem = item.find("Properties")
    if props_elem is None:
        return flat, tags, full, attributes

    for prop in list(props_elem):
        prop_name = prop.get("name")
        if not prop_name:
            continue

        structured = parse_property_element(prop)
        full[prop_name] = structured

        if prop_name == "Tags":
            decoded = decode_tags_from_structured(structured, shared_strings)
            if decoded:
                tags = decoded
                full.pop("Tags", None)
            continue

        if prop_name == "AttributesSerialize" and structured.get("type") == "BinaryString":
            decoded = decode_attributes(structured.get("value") or "")
            if decoded:
                attributes = decoded
                full.pop("AttributesSerialize", None)
            continue

        if prop_name in interesting and structured.get("type") in (
            "string",
            "ProtectedString",
            "Content",
            "token",
            "BinaryString",
        ):
            flat[prop_name] = structured.get("value") or ""

        if prop_name in interesting and structured.get("type") in ("bool", "int", "float", "double", "token"):
            flat[prop_name] = structured.get("value")

    return flat, tags, full, attributes
