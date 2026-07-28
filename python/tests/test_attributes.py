"""Unit tests for Instance.AttributesSerialize decode / encode and export/build round-trip."""

from __future__ import annotations

import base64
import json
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import export
import build
from attributes import decode_attributes, encode_attributes, encode_attributes_b64


def _make_attrs_binary(entries: list[tuple[str, int, bytes]]) -> bytes:
    """Build a minimal AttributesSerialize payload for testing.

    entries: list of (name, type_id, value_bytes)
    """
    buf = bytearray()
    buf.extend(struct.pack("<I", len(entries)))
    for name, type_id, value_bytes in entries:
        name_b = name.encode("utf-8")
        buf.extend(struct.pack("<I", len(name_b)))
        buf.extend(name_b)
        buf.append(type_id)
        buf.extend(value_bytes)
    return bytes(buf)


def test_decode_empty():
    assert decode_attributes("") == {}
    assert decode_attributes(b"") == {}
    assert decode_attributes(base64.b64encode(b"").decode()) == {}


def test_decode_string_bool_number():
    # String "hello"
    string_val = struct.pack("<I", 5) + b"hello"
    # Bool true
    bool_val = b"\x01"
    # Int32 42
    int_val = struct.pack("<i", 42)
    # Float64 3.14
    float_val = struct.pack("<d", 3.14)

    raw = _make_attrs_binary(
        [
            ("MyString", 2, string_val),
            ("MyBool", 3, bool_val),
            ("MyInt", 4, int_val),
            ("MyFloat", 6, float_val),
        ]
    )
    attrs = decode_attributes(raw)
    assert attrs["MyString"] == "hello"
    assert attrs["MyBool"] is True
    assert attrs["MyInt"] == 42
    assert abs(attrs["MyFloat"] - 3.14) < 1e-9


def test_decode_vector3_color3():
    vec_bytes = struct.pack("<fff", 1.0, 2.0, 3.0)
    color_bytes = struct.pack("<fff", 0.2, 0.4, 0.6)
    raw = _make_attrs_binary(
        [
            ("Pos", 17, vec_bytes),
            ("Col", 15, color_bytes),
        ]
    )
    attrs = decode_attributes(raw)
    assert attrs["Pos"]["__type"] == "Vector3"
    assert attrs["Pos"]["X"] == 1.0
    assert attrs["Pos"]["Y"] == 2.0
    assert attrs["Pos"]["Z"] == 3.0
    assert attrs["Col"]["__type"] == "Color3"
    assert abs(attrs["Col"]["R"] - 0.2) < 1e-6


def test_encode_roundtrip_scalars():
    original = {
        "s": "hello",
        "b": True,
        "i": 99,
        "f": 2.5,
    }
    encoded = encode_attributes(original)
    decoded = decode_attributes(encoded)
    assert decoded["s"] == "hello"
    assert decoded["b"] is True
    assert decoded["i"] == 99
    assert abs(decoded["f"] - 2.5) < 1e-9


def test_encode_roundtrip_vector3_color3():
    original = {
        "v": {"__type": "Vector3", "X": 10.0, "Y": 20.0, "Z": 30.0},
        "c": {"__type": "Color3", "R": 0.1, "G": 0.2, "B": 0.3},
    }
    encoded = encode_attributes(original)
    decoded = decode_attributes(encoded)
    assert decoded["v"]["__type"] == "Vector3"
    assert decoded["v"]["X"] == 10.0
    assert decoded["c"]["__type"] == "Color3"
    assert abs(decoded["c"]["R"] - 0.1) < 1e-6


def test_extract_build_attributes_roundtrip(tmp_path: Path):
    """Full export → meta["Attributes"] → build → AttributesSerialize present."""
    # Build a small AttributesSerialize payload (string + bool)
    string_val = struct.pack("<I", 5) + b"hello"
    bool_val = b"\x01"
    raw = _make_attrs_binary(
        [
            ("Greeting", 2, string_val),
            ("Enabled", 3, bool_val),
        ]
    )
    b64 = base64.b64encode(raw).decode("ascii")

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<roblox version="4">
  <Item class="Part" name="AttrPart">
    <Properties>
      <string name="Name">AttrPart</string>
      <BinaryString name="AttributesSerialize">{b64}</BinaryString>
      <bool name="Anchored">true</bool>
    </Properties>
  </Item>
</roblox>
"""
    src = tmp_path / "in.rbxlx"
    src.write_text(xml, encoding="utf-8")
    out = tmp_path / "extracted"
    export.export(str(src), str(out), scripts_only=False)

    meta = json.loads((out / "AttrPart" / ".robloxmeta.json").read_text())
    assert "Attributes" in meta
    assert meta["Attributes"]["Greeting"] == "hello"
    assert meta["Attributes"]["Enabled"] is True
    # Opaque BinaryString must not remain in Properties
    assert "AttributesSerialize" not in meta.get("Properties", {})

    rebuilt = tmp_path / "out.rbxlx"
    build.build_rbxlx(str(out), str(rebuilt))
    tree = ET.parse(rebuilt)
    attr_el = tree.find(".//BinaryString[@name='AttributesSerialize']")
    assert attr_el is not None
    assert attr_el.text
    # Re-decode the emitted payload
    roundtripped = decode_attributes(attr_el.text)
    assert roundtripped["Greeting"] == "hello"
    assert roundtripped["Enabled"] is True


def test_empty_attributes_omitted(tmp_path: Path):
    """No AttributesSerialize → no meta["Attributes"] key."""
    xml = """<?xml version="1.0" encoding="utf-8"?>
<roblox version="4">
  <Item class="Part" name="Plain">
    <Properties>
      <string name="Name">Plain</string>
      <bool name="Anchored">false</bool>
    </Properties>
  </Item>
</roblox>
"""
    src = tmp_path / "in.rbxlx"
    src.write_text(xml, encoding="utf-8")
    out = tmp_path / "extracted"
    export.export(str(src), str(out), scripts_only=False)

    meta = json.loads((out / "Plain" / ".robloxmeta.json").read_text())
    assert "Attributes" not in meta
