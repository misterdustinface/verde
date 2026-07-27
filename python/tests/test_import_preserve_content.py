"""Differential import: default VCS semantics vs --preserve-content recovery."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import build


def _write_place(tmp_path: Path, mesh_url: str = "rbxassetid://111222333") -> Path:
    place_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<roblox version="4">
  <Item class="MeshPart" name="MyMesh" referent="RBX1">
    <Properties>
      <string name="Name">MyMesh</string>
      <Content name="MeshId"><url>{mesh_url}</url></Content>
      <bool name="Anchored">true</bool>
    </Properties>
  </Item>
</roblox>
"""
    place = tmp_path / "place.rbxlx"
    place.write_text(place_xml, encoding="utf-8")
    return place


def _write_blank_mesh_meta(folder: Path) -> None:
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


def test_default_blank_meta_meshid_applies(tmp_path: Path):
    """VCS-correct: intentional empty MeshId in export clears the place MeshId."""
    place = _write_place(tmp_path)
    folder = tmp_path / "extracted"
    _write_blank_mesh_meta(folder)

    build.import_rbxlx(str(folder), str(place), force=True, preserve_content=False)

    tree = ET.parse(place)
    mesh_id = tree.find(".//Content[@name='MeshId']")
    assert mesh_id is not None
    url = mesh_id.find("url")
    # Blank applied: no url child / empty
    assert url is None or not (url.text or "").strip()
    # Other meta still applies
    anchored = tree.find(".//bool[@name='Anchored']")
    assert anchored is not None and anchored.text == "false"


def test_preserve_content_keeps_place_meshid(tmp_path: Path):
    """Recovery: --preserve-content refuses blank meta wipe of good place MeshId."""
    place = _write_place(tmp_path, "rbxassetid://111222333")
    folder = tmp_path / "extracted"
    _write_blank_mesh_meta(folder)

    build.import_rbxlx(str(folder), str(place), force=True, preserve_content=True)

    tree = ET.parse(place)
    url = tree.find(".//Content[@name='MeshId']/url")
    assert url is not None and url.text == "rbxassetid://111222333"
    anchored = tree.find(".//bool[@name='Anchored']")
    assert anchored is not None and anchored.text == "false"


def test_nonblank_meta_meshid_still_applies(tmp_path: Path):
    place = _write_place(tmp_path, "rbxassetid://111")
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

    build.import_rbxlx(str(folder), str(place), force=True, preserve_content=False)

    tree = ET.parse(place)
    url = tree.find(".//Content[@name='MeshId']/url")
    assert url is not None and url.text == "rbxassetid://999888777"
