#!/usr/bin/env python3
"""
Load the canonical interesting-properties list from luau/interesting_properties.luau.

This is the single source of truth (Luau-first). Python extracts the string
literals so both languages stay in sync without a second copy.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Relative to this file: python/interesting.py → ../luau/interesting_properties.luau
_DEFAULT_LUAU = Path(__file__).resolve().parent.parent / "luau" / "interesting_properties.luau"


def load_interesting_props(luau_path: Path | None = None) -> set[str]:
    """Return the set of interesting property names.

    Priority:
      1. VERDE_INTERESTING_PROPS env var (comma-separated)
      2. ./verde.interesting file (one prop per line or comma-separated)
      3. The canonical luau/interesting_properties.luau table
    """
    env = os.environ.get("VERDE_INTERESTING_PROPS", "").strip()
    if env:
        return {p.strip() for p in env.split(",") if p.strip()}

    cfg = Path("verde.interesting")
    if cfg.is_file():
        text = cfg.read_text(encoding="utf-8")
        props: set[str] = set()
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            for p in line.split(","):
                p = p.strip()
                if p:
                    props.add(p)
        if props:
            return props

    path = luau_path or _DEFAULT_LUAU
    if not path.is_file():
        # Extremely minimal fallback if the Luau file is missing
        return {
            "Source", "Name", "SoundId", "Texture", "MeshId", "Image",
            "Anchored", "CanCollide", "CastShadow", "Transparency",
            "Enabled", "Disabled",
        }

    text = path.read_text(encoding="utf-8")
    # Extract every "string" literal that appears inside the returned table.
    # The file is deliberately a flat list of strings, so this is reliable.
    return set(re.findall(r'"([^"]+)"', text))
