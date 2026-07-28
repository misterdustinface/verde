"""Unit tests for Verde property export / emission and Tags handling.

Stronger coverage: multiple property types, hierarchy, interesting-props overrides,
empty Tags, CFrame, sequences, and edge cases.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import export
import build


def make_minimal_rbxlx(props_xml: str, class_name: str = "Part", name: str = "TestPart") -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<roblox version="4">
  <Item class="{class_name}" name="{name}">
    <Properties>
{props_xml}
    </Properties>
  </Item>
</roblox>
"""


def test_string_and_bool_roundtrip(tmp_path: Path):
    xml = make_minimal_rbxlx(
        '      <string name="SoundId">rbxassetid://123</string>\n'
        '      <bool name="Anchored">true</bool>\n'
    )
    src = tmp_path / "in.rbxlx"
    src.write_text(xml, encoding="utf-8")
    out = tmp_path / "extracted"
    export.export(str(src), str(out))

    meta = json.loads((out / "TestPart" / ".robloxmeta.json").read_text())
    assert meta["ClassName"] == "Part"
    assert meta["Name"] == "TestPart"
    assert "Properties" in meta
    assert meta["Properties"]["SoundId"]["type"] == "string"
    assert meta["Properties"]["SoundId"]["value"] == "rbxassetid://123"
    assert meta["Properties"]["Anchored"]["type"] == "bool"
    assert meta["Properties"]["Anchored"]["value"] == "true"
    # Flattened interesting
    assert meta.get("SoundId") == "rbxassetid://123"
    assert meta.get("Anchored") == "true"

    rebuilt = tmp_path / "out.rbxlx"
    build.build_rbxlx(str(out), str(rebuilt))
    tree = ET.parse(rebuilt)
    sound = tree.find(".//string[@name='SoundId']")
    assert sound is not None and sound.text == "rbxassetid://123"
    anchored = tree.find(".//bool[@name='Anchored']")
    assert anchored is not None and anchored.text == "true"


def test_vector3_and_color3(tmp_path: Path):
    xml = make_minimal_rbxlx(
        """      <Vector3 name="Position">
        <X>1.5</X>
        <Y>2.5</Y>
        <Z>3.5</Z>
      </Vector3>
      <Color3 name="Color">
        <R>0.2</R>
        <G>0.4</G>
        <B>0.6</B>
      </Color3>
"""
    )
    src = tmp_path / "in.rbxlx"
    src.write_text(xml, encoding="utf-8")
    out = tmp_path / "extracted"
    export.export(str(src), str(out))

    meta = json.loads((out / "TestPart" / ".robloxmeta.json").read_text())
    pos = meta["Properties"]["Position"]
    assert pos["type"] == "Vector3"
    assert pos["children"]["X"] == "1.5"
    assert pos["children"]["Y"] == "2.5"
    assert pos["children"]["Z"] == "3.5"

    color = meta["Properties"]["Color"]
    assert color["type"] == "Color3"
    assert color["children"]["R"] == "0.2"

    rebuilt = tmp_path / "out.rbxlx"
    build.build_rbxlx(str(out), str(rebuilt))
    tree = ET.parse(rebuilt)
    x = tree.find(".//Vector3[@name='Position']/X")
    assert x is not None and x.text == "1.5"
    r = tree.find(".//Color3[@name='Color']/R")
    assert r is not None and r.text == "0.2"


def test_coordinateframe(tmp_path: Path):
    xml = make_minimal_rbxlx(
        """      <CoordinateFrame name="CFrame">
        <X>10</X>
        <Y>20</Y>
        <Z>30</Z>
        <R00>1</R00>
        <R01>0</R01>
        <R02>0</R02>
        <R10>0</R10>
        <R11>1</R11>
        <R12>0</R12>
        <R20>0</R20>
        <R21>0</R21>
        <R22>1</R22>
      </CoordinateFrame>
"""
    )
    src = tmp_path / "in.rbxlx"
    src.write_text(xml, encoding="utf-8")
    out = tmp_path / "extracted"
    export.export(str(src), str(out))

    meta = json.loads((out / "TestPart" / ".robloxmeta.json").read_text())
    cf = meta["Properties"]["CFrame"]
    assert cf["type"] == "CoordinateFrame"
    assert cf["children"]["X"] == "10"
    assert cf["children"]["R00"] == "1"

    rebuilt = tmp_path / "out.rbxlx"
    build.build_rbxlx(str(out), str(rebuilt))
    tree = ET.parse(rebuilt)
    x = tree.find(".//CoordinateFrame[@name='CFrame']/X")
    assert x is not None and x.text == "10"
    r00 = tree.find(".//CoordinateFrame[@name='CFrame']/R00")
    assert r00 is not None and r00.text == "1"


def test_numbersequence(tmp_path: Path):
    xml = make_minimal_rbxlx(
        """      <NumberSequence name="Transparency">
        <Keypoints>
          <NumberSequenceKeypoint>
            <Time>0</Time>
            <Value>0</Value>
            <Envelope>0</Envelope>
          </NumberSequenceKeypoint>
          <NumberSequenceKeypoint>
            <Time>1</Time>
            <Value>1</Value>
            <Envelope>0</Envelope>
          </NumberSequenceKeypoint>
        </Keypoints>
      </NumberSequence>
"""
    )
    src = tmp_path / "in.rbxlx"
    src.write_text(xml, encoding="utf-8")
    out = tmp_path / "extracted"
    export.export(str(src), str(out))

    meta = json.loads((out / "TestPart" / ".robloxmeta.json").read_text())
    seq = meta["Properties"]["Transparency"]
    assert seq["type"] == "NumberSequence"
    assert "children" in seq

    rebuilt = tmp_path / "out.rbxlx"
    build.build_rbxlx(str(out), str(rebuilt))
    tree = ET.parse(rebuilt)
    ns = tree.find(".//NumberSequence[@name='Transparency']")
    assert ns is not None


def test_tags_binarystring(tmp_path: Path):
    tags = ["Hello", "from", "Verde"]
    raw = b"\0".join(t.encode("utf-8") for t in tags)
    b64 = base64.b64encode(raw).decode("ascii")
    xml = make_minimal_rbxlx(f'      <BinaryString name="Tags">{b64}</BinaryString>\n')
    src = tmp_path / "in.rbxlx"
    src.write_text(xml, encoding="utf-8")
    out = tmp_path / "extracted"
    export.export(str(src), str(out))

    meta = json.loads((out / "TestPart" / ".robloxmeta.json").read_text())
    assert meta["Tags"] == tags

    rebuilt = tmp_path / "out.rbxlx"
    build.build_rbxlx(str(out), str(rebuilt))
    tree = ET.parse(rebuilt)
    tag_el = tree.find(".//BinaryString[@name='Tags']")
    assert tag_el is not None
    decoded = base64.b64decode(tag_el.text or "")
    assert decoded.split(b"\0") == [t.encode() for t in tags]


def test_empty_tags(tmp_path: Path):
    xml = make_minimal_rbxlx('      <BinaryString name="Tags"></BinaryString>\n')
    src = tmp_path / "in.rbxlx"
    src.write_text(xml, encoding="utf-8")
    out = tmp_path / "extracted"
    export.export(str(src), str(out))

    meta = json.loads((out / "TestPart" / ".robloxmeta.json").read_text())
    assert meta["Tags"] == []

    rebuilt = tmp_path / "out.rbxlx"
    build.build_rbxlx(str(out), str(rebuilt))
    tree = ET.parse(rebuilt)
    assert tree.find(".//Item[@name='TestPart']") is not None


def test_script_source_extracted(tmp_path: Path):
    xml = """<?xml version="1.0" encoding="utf-8"?>
<roblox version="4">
  <Item class="ModuleScript" name="MyModule">
    <Properties>
      <ProtectedString name="Source">return 42</ProtectedString>
    </Properties>
  </Item>
</roblox>
"""
    src = tmp_path / "in.rbxlx"
    src.write_text(xml, encoding="utf-8")
    out = tmp_path / "extracted"
    export.export(str(src), str(out))

    script_file = out / "MyModule.module.lua"
    assert script_file.is_file()
    assert script_file.read_text() == "return 42"

    meta = json.loads((out / "MyModule.module.robloxmeta.json").read_text())
    assert meta["ClassName"] == "ModuleScript"
    assert "Source" not in meta.get("Properties", {})

    rebuilt = tmp_path / "out.rbxlx"
    build.build_rbxlx(str(out), str(rebuilt))
    tree = ET.parse(rebuilt)
    source = tree.find(".//ProtectedString[@name='Source']")
    assert source is not None and source.text == "return 42"


def test_interesting_props_override(tmp_path: Path):
    """Only the supplied interesting set should be flattened."""
    xml = make_minimal_rbxlx(
        '      <string name="SoundId">rbxassetid://999</string>\n'
        '      <string name="Texture">rbxassetid://111</string>\n'
        '      <bool name="Anchored">false</bool>\n'
    )
    src = tmp_path / "in.rbxlx"
    src.write_text(xml, encoding="utf-8")
    out = tmp_path / "extracted"
    export.export(str(src), str(out), interesting={"SoundId"})

    meta = json.loads((out / "TestPart" / ".robloxmeta.json").read_text())
    assert meta.get("SoundId") == "rbxassetid://999"
    assert "Texture" not in meta or isinstance(meta.get("Texture"), dict)
    assert "Anchored" not in meta or isinstance(meta.get("Anchored"), dict)
    assert meta["Properties"]["Texture"]["value"] == "rbxassetid://111"
    assert meta["Properties"]["Anchored"]["value"] == "false"


def test_load_interesting_props_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("VERDE_INTERESTING_PROPS", "Foo,Bar , Baz")
    from interesting import load_interesting_props
    props = load_interesting_props()
    assert props == {"Foo", "Bar", "Baz"}


def test_nested_hierarchy(tmp_path: Path):
    xml = """<?xml version="1.0" encoding="utf-8"?>
<roblox version="4">
  <Item class="Folder" name="RootFolder">
    <Properties>
      <string name="Name">RootFolder</string>
    </Properties>
    <Item class="Part" name="ChildPart">
      <Properties>
        <string name="SoundId">rbxassetid://42</string>
        <bool name="Anchored">true</bool>
      </Properties>
    </Item>
  </Item>
</roblox>
"""
    src = tmp_path / "in.rbxlx"
    src.write_text(xml, encoding="utf-8")
    out = tmp_path / "extracted"
    export.export(str(src), str(out))

    assert (out / "RootFolder" / ".robloxmeta.json").is_file()
    assert (out / "RootFolder" / "ChildPart" / ".robloxmeta.json").is_file()
    child_meta = json.loads((out / "RootFolder" / "ChildPart" / ".robloxmeta.json").read_text())
    assert child_meta["ClassName"] == "Part"
    assert child_meta.get("SoundId") == "rbxassetid://42"

    rebuilt = tmp_path / "out.rbxlx"
    build.build_rbxlx(str(out), str(rebuilt))
    tree = ET.parse(rebuilt)
    child = tree.find(".//Item[@name='ChildPart']")
    assert child is not None
    assert child.get("class") == "Part"
    sound = child.find(".//string[@name='SoundId']")
    assert sound is not None and sound.text == "rbxassetid://42"


def test_script_with_tags(tmp_path: Path):
    tags = ["Interactable", "Quest"]
    raw = b"\0".join(t.encode("utf-8") for t in tags)
    b64 = base64.b64encode(raw).decode("ascii")
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<roblox version="4">
  <Item class="LocalScript" name="Handler">
    <Properties>
      <ProtectedString name="Source">print("hi")</ProtectedString>
      <BinaryString name="Tags">{b64}</BinaryString>
    </Properties>
  </Item>
</roblox>
"""
    src = tmp_path / "in.rbxlx"
    src.write_text(xml, encoding="utf-8")
    out = tmp_path / "extracted"
    export.export(str(src), str(out))

    script_file = out / "Handler.local.lua"
    assert script_file.is_file()
    assert script_file.read_text() == 'print("hi")'

    meta = json.loads((out / "Handler.local.robloxmeta.json").read_text())
    assert meta["Tags"] == tags
    assert meta["ClassName"] == "LocalScript"

    rebuilt = tmp_path / "out.rbxlx"
    build.build_rbxlx(str(out), str(rebuilt))
    tree = ET.parse(rebuilt)
    tag_el = tree.find(".//BinaryString[@name='Tags']")
    assert tag_el is not None
    decoded = base64.b64decode(tag_el.text or "")
    assert decoded.split(b"\0") == [t.encode() for t in tags]


def test_name_from_property_only(tmp_path: Path):
    """Real Studio .rbxlx has no Item@name attribute; Name is only a property.

    This is the format that previously produced cascades of Unnamed folders.
    """
    xml = """<?xml version="1.0" encoding="utf-8"?>
<roblox version="4">
  <Item class="Folder" referent="RBX1">
    <Properties>
      <string name="Name">Workspace</string>
    </Properties>
    <Item class="Part" referent="RBX2">
      <Properties>
        <string name="Name">Baseplate</string>
        <bool name="Anchored">true</bool>
      </Properties>
    </Item>
    <Item class="Script" referent="RBX3">
      <Properties>
        <string name="Name">Main</string>
        <ProtectedString name="Source">print("ok")</ProtectedString>
      </Properties>
    </Item>
  </Item>
</roblox>
"""
    src = tmp_path / "in.rbxlx"
    src.write_text(xml, encoding="utf-8")
    out = tmp_path / "extracted"
    export.export(str(src), str(out))

    # Filesystem must use the real Names, not Unnamed
    assert (out / "Workspace" / ".robloxmeta.json").is_file()
    assert (out / "Workspace" / "Baseplate" / ".robloxmeta.json").is_file()
    assert (out / "Workspace" / "Main.lua").is_file()

    ws_meta = json.loads((out / "Workspace" / ".robloxmeta.json").read_text())
    assert ws_meta["Name"] == "Workspace"
    assert ws_meta["ClassName"] == "Folder"

    base_meta = json.loads((out / "Workspace" / "Baseplate" / ".robloxmeta.json").read_text())
    assert base_meta["Name"] == "Baseplate"
    assert base_meta.get("Anchored") == "true"

    script_meta = json.loads((out / "Workspace" / "Main.robloxmeta.json").read_text())
    assert script_meta["Name"] == "Main"
    assert script_meta["ClassName"] == "Script"
    assert (out / "Workspace" / "Main.lua").read_text() == 'print("ok")'

    # Round-trip still works
    rebuilt = tmp_path / "out.rbxlx"
    build.build_rbxlx(str(out), str(rebuilt))
    tree = ET.parse(rebuilt)
    assert tree.find(".//Item[@name='Workspace']") is not None
    assert tree.find(".//Item[@name='Baseplate']") is not None
    assert tree.find(".//Item[@name='Main']") is not None


def test_scripts_only_prunes_non_script_leaves(tmp_path: Path):
    """--scripts-only removes pure non-script subtrees and cascades upward.

    Keeps ancestor folders of scripts (with their meta) and the scripts themselves.
    """
    xml = """<?xml version="1.0" encoding="utf-8"?>
<roblox version="4">
  <Item class="Folder" referent="RBX1">
    <Properties>
      <string name="Name">Workspace</string>
    </Properties>
    <Item class="Part" referent="RBX2">
      <Properties>
        <string name="Name">Baseplate</string>
        <bool name="Anchored">true</bool>
      </Properties>
    </Item>
    <Item class="Folder" referent="RBX3">
      <Properties>
        <string name="Name">Systems</string>
      </Properties>
      <Item class="Folder" referent="RBX4">
        <Properties>
          <string name="Name">OnlyGeometry</string>
        </Properties>
        <Item class="Part" referent="RBX5">
          <Properties>
            <string name="Name">Decoration</string>
          </Properties>
        </Item>
      </Item>
      <Item class="Script" referent="RBX6">
        <Properties>
          <string name="Name">Bootstrap</string>
          <ProtectedString name="Source">print("boot")</ProtectedString>
        </Properties>
      </Item>
    </Item>
  </Item>
</roblox>
"""
    src = tmp_path / "in.rbxlx"
    src.write_text(xml, encoding="utf-8")

    # Full export still has everything
    full = tmp_path / "full"
    export.export(str(src), str(full), scripts_only=False)
    assert (full / "Workspace" / "Baseplate" / ".robloxmeta.json").is_file()
    assert (full / "Workspace" / "Systems" / "OnlyGeometry" / "Decoration" / ".robloxmeta.json").is_file()
    assert (full / "Workspace" / "Systems" / "Bootstrap.lua").is_file()

    # scripts-only: pure geometry gone; script path retained
    code = tmp_path / "code"
    export.export(str(src), str(code), scripts_only=True)

    assert (code / "Workspace" / ".robloxmeta.json").is_file()
    assert (code / "Workspace" / "Systems" / ".robloxmeta.json").is_file()
    assert (code / "Workspace" / "Systems" / "Bootstrap.lua").is_file()
    assert (code / "Workspace" / "Systems" / "Bootstrap.robloxmeta.json").is_file()

    # These must have been pruned
    assert not (code / "Workspace" / "Baseplate").exists()
    assert not (code / "Workspace" / "Systems" / "OnlyGeometry").exists()

    # Script content intact
    assert (code / "Workspace" / "Systems" / "Bootstrap.lua").read_text() == 'print("boot")'
