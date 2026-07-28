"""MeshPart MeshId / TextureID Content-with-url child must survive export/build."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import export
import build
from xml_props import parse_property_element


def test_content_with_url_child_parsed():
    xml = (
        '<Content name="MeshId">'
        "<url>rbxassetid://123456789</url>"
        "</Content>"
    )
    el = ET.fromstring(xml)
    structured = parse_property_element(el)
    assert structured["type"] == "Content"
    assert "children" in structured
    assert structured["children"]["url"] == "rbxassetid://123456789"


def test_content_plain_text_still_works():
    xml = '<Content name="MeshId">rbxassetid://999</Content>'
    el = ET.fromstring(xml)
    structured = parse_property_element(el)
    assert structured["type"] == "Content"
    assert structured.get("value") == "rbxassetid://999"
    assert "children" not in structured


def test_meshpart_meshid_url_roundtrip(tmp_path: Path):
    rbxlx = """<?xml version="1.0" encoding="utf-8"?>
<roblox version="4">
  <Item class="MeshPart" name="MyMesh">
    <Properties>
      <string name="Name">MyMesh</string>
      <Content name="MeshId"><url>rbxassetid://123456789</url></Content>
      <Content name="TextureID"><url>rbxassetid://987654321</url></Content>
      <bool name="Anchored">true</bool>
    </Properties>
  </Item>
</roblox>
"""
    src = tmp_path / "in.rbxlx"
    src.write_text(rbxlx, encoding="utf-8")
    out = tmp_path / "extracted"
    export.export(str(src), str(out), scripts_only=False)

    meta = json.loads((out / "MyMesh" / ".robloxmeta.json").read_text())
    assert meta["ClassName"] == "MeshPart"
    mesh_id = meta["Properties"]["MeshId"]
    assert mesh_id["type"] == "Content"
    assert mesh_id["children"]["url"] == "rbxassetid://123456789"
    tex = meta["Properties"]["TextureID"]
    assert tex["children"]["url"] == "rbxassetid://987654321"

    rebuilt = tmp_path / "out.rbxlx"
    build.build_rbxlx(str(out), str(rebuilt))
    tree = ET.parse(rebuilt)
    mesh_el = tree.find(".//Content[@name='MeshId']")
    assert mesh_el is not None
    url = mesh_el.find("url")
    assert url is not None and url.text == "rbxassetid://123456789"
    tex_el = tree.find(".//Content[@name='TextureID']/url")
    assert tex_el is not None and tex_el.text == "rbxassetid://987654321"
