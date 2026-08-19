"""--all / --delete / --rename must not wipe real *_N assets.

Referent lives in gitignored local.json, so identity has to work from
shared UniqueId and from meta Name == path stem.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import build
import extract


def _write_place(tmp_path: Path) -> Path:
    place_xml = """<?xml version="1.0" encoding="utf-8"?>
<roblox version="4">
  <Item class="Workspace" name="Workspace" referent="RBX1">
    <Properties>
      <string name="Name">Workspace</string>
    </Properties>
    <Item class="Part" name="Part" referent="RBX2">
      <Properties>
        <string name="Name">Part</string>
        <string name="UniqueId">uid-part</string>
      </Properties>
    </Item>
    <Item class="Part" name="Part_2" referent="RBX3">
      <Properties>
        <string name="Name">Part_2</string>
        <string name="UniqueId">uid-part-2</string>
      </Properties>
    </Item>
    <Item class="Folder" name="Utility" referent="RBX4">
      <Properties>
        <string name="Name">Utility</string>
        <string name="UniqueId">uid-util</string>
      </Properties>
    </Item>
  </Item>
</roblox>
"""
    place = tmp_path / "TheGame.rbxlx"
    place.write_text(place_xml, encoding="utf-8")
    return place


def _names(place: Path) -> set[str]:
    tree = ET.parse(place)
    return {item.get("name") or "" for item in tree.iter("Item")}
