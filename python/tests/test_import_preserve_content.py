"""Differential import must not wipe valid place MeshId with blank meta from old exports."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import build


def test_blank_meta_meshid_does_not_wipe_place(tmp_path: Path):
    # Place has a good MeshId (Content + url)
    place_xml = """<?xml version="1.0" encoding="utf-8"?>
<roblox version="4">
  <Item class="MeshPart" name="MyMesh" referent="RBX1">
    <Properties>
      <string name="Name">MyMesh</string>
      <Content name="MeshId"><url>rbxassetid://111222333</url></Content>
      <bool name="Anchored">true</bool>
    </Properties>
  </Item>
</roblox>
"""
    place = tmp_path / "place.rbxlx"
    place.write_text(place_xml, encoding="utf-8")

    # Older export meta: MeshId corrupted into empty value (pre Content/url fix)
    folder = tmp_path / "extracted"
    mesh_dir = folder / "MyMesh"
    mesh_dir.mkdir(parents=True)
    meta = {
        "ClassName": "MeshPart",
        "Name": "MyMesh",
        "Referent": "RBX1",
        "Properties": {
            "Name": {"type": "string", "value": "MyMesh"},
            "MeshId": {"type": "Content", "value": ""},
            "Anchored": {"type": "bool", "value": "false"},
        },
    }
    (mesh_dir / ".robloxmeta.json").write_text(json.dumps(meta), encoding="utf-8")

    build.import_rbxlx(str(folder), str(place), force=True)

    tree = ET.parse(place)
    mesh_id = tree.find(".//Content[@name='MeshId']")
    assert mesh_id is not None
    url = mesh_id.find("url")
    assert url is not None and url.text == "rbxassetid://111222333"
    # Non-blank meta still applies
    anchored = tree.find(".//bool[@name='Anchored']")
    assert anchored is not None and anchored.text == "false"


def test_nonblank_meta_meshid_still_applies(tmp_path: Path):
    place_xml = """<?xml version="1.0" encoding="utf-8"?>
<roblox version="4">
  <Item class="MeshPart" name="MyMesh" referent="RBX1">
    <Properties>
      <string name="Name">MyMesh</string>
      <Content name="MeshId"><url>rbxassetid://111</url></Content>
    </Properties>
  </Item>
</roblox>
"""
    place = tmp_path / "place.rbxlx"
    place.write_text(place_xml, encoding="utf-8")

    folder = tmp_path / "extracted"
    mesh_dir = folder / "MyMesh"
    mesh_dir.mkdir(parents=True)
    meta = {
        "ClassName": "MeshPart",
        "Name": "MyMesh",
        "Referent": "RBX1",
        "Properties": {
            "MeshId": {
                "type": "Content",
                "children": {"url": "rbxassetid://999888777"},
            },
        },
    }
    (mesh_dir / ".robloxmeta.json").write_text(json.dumps(meta), encoding="utf-8")

    build.import_rbxlx(str(folder), str(place), force=True)

    tree = ET.parse(place)
    url = tree.find(".//Content[@name='MeshId']/url")
    assert url is not None and url.text == "rbxassetid://999888777"
