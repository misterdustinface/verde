#!/usr/bin/env python3
"""
Decode / encode Roblox Instance.AttributesSerialize (BinaryString).

Binary layout (little-endian):

  u32  count
  for each attribute:
      String   name          (u32 length + UTF-8 bytes)
      u8       type_id
      <value>  according to type_id

Supported type IDs (from public rbx-dom / RobloxAPI specs):

  2   String
  3   Bool
  4   Int32
  5   Float32
  6   Float64 / Double
  9   UDim
 10   UDim2
 14   BrickColor
 15   Color3
 16   Vector2
 17   Vector3
 20   CFrame
 21   EnumItem          (0x15)
 23   NumberSequence    (0x17)
 25   ColorSequence     (0x19)
 27   NumberRange       (0x1B)
 28   Rect              (0x1C)
 33   Font              (0x21)

The resulting Python dict is stored at meta["Attributes"]:

  {
    "MyString": "hello",
    "MyBool": true,
    "MyNumber": 3.14,
    "MyVec": {"__type": "Vector3", "X": 1.0, "Y": 2.0, "Z": 3.0},
    "MyColor": {"__type": "Color3", "R": 0.2, "G": 0.4, "B": 0.6},
    ...
  }

Complex values use a "__type" discriminator so they round-trip cleanly.
Unknown type IDs are stored as a raw marker and cause further parsing of
that attribute list to stop (variable-length values cannot be skipped safely).
"""

from __future__ import annotations

import base64
import struct
from typing import Any


# ---------------------------------------------------------------------------
# Low-level readers / writers
# ---------------------------------------------------------------------------

def _read_u8(data: bytes, offset: int) -> tuple[int, int]:
    return data[offset], offset + 1


def _read_u16(data: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from("<H", data, offset)[0], offset + 2


def _read_u32(data: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from("<I", data, offset)[0], offset + 4


def _read_i32(data: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from("<i", data, offset)[0], offset + 4


def _read_f32(data: bytes, offset: int) -> tuple[float, int]:
    return struct.unpack_from("<f", data, offset)[0], offset + 4


def _read_f64(data: bytes, offset: int) -> tuple[float, int]:
    return struct.unpack_from("<d", data, offset)[0], offset + 8


def _read_string(data: bytes, offset: int) -> tuple[str, int]:
    length, offset = _read_u32(data, offset)
    raw = data[offset : offset + length]
    offset += length
    return raw.decode("utf-8", errors="replace"), offset


def _write_u8(buf: bytearray, value: int) -> None:
    buf.append(value & 0xFF)


def _write_u16(buf: bytearray, value: int) -> None:
    buf.extend(struct.pack("<H", value))


def _write_u32(buf: bytearray, value: int) -> None:
    buf.extend(struct.pack("<I", value))


def _write_i32(buf: bytearray, value: int) -> None:
    buf.extend(struct.pack("<i", value))


def _write_f32(buf: bytearray, value: float) -> None:
    buf.extend(struct.pack("<f", value))


def _write_f64(buf: bytearray, value: float) -> None:
    buf.extend(struct.pack("<d", value))


def _write_string(buf: bytearray, value: str) -> None:
    raw = value.encode("utf-8")
    _write_u32(buf, len(raw))
    buf.extend(raw)


# ---------------------------------------------------------------------------
# Decode helpers for compound types
# ---------------------------------------------------------------------------

def _decode_udim(data: bytes, offset: int) -> tuple[dict[str, Any], int]:
    scale, offset = _read_f32(data, offset)
    off, offset = _read_i32(data, offset)
    return {"__type": "UDim", "Scale": scale, "Offset": off}, offset


def _decode_vector2(data: bytes, offset: int) -> tuple[dict[str, Any], int]:
    x, offset = _read_f32(data, offset)
    y, offset = _read_f32(data, offset)
    return {"__type": "Vector2", "X": x, "Y": y}, offset


def _decode_vector3(data: bytes, offset: int) -> tuple[dict[str, Any], int]:
    x, offset = _read_f32(data, offset)
    y, offset = _read_f32(data, offset)
    z, offset = _read_f32(data, offset)
    return {"__type": "Vector3", "X": x, "Y": y, "Z": z}, offset


def _decode_color3(data: bytes, offset: int) -> tuple[dict[str, Any], int]:
    r, offset = _read_f32(data, offset)
    g, offset = _read_f32(data, offset)
    b, offset = _read_f32(data, offset)
    return {"__type": "Color3", "R": r, "G": g, "B": b}, offset


def _decode_cframe(data: bytes, offset: int) -> tuple[dict[str, Any], int]:
    pos, offset = _decode_vector3(data, offset)
    rot_id, offset = _read_u8(data, offset)
    result: dict[str, Any] = {
        "__type": "CFrame",
        "Position": {"X": pos["X"], "Y": pos["Y"], "Z": pos["Z"]},
        "RotationId": rot_id,
    }
    if rot_id == 0:
        # Arbitrary rotation matrix follows (9 × f32)
        matrix = []
        for _ in range(9):
            v, offset = _read_f32(data, offset)
            matrix.append(v)
        result["Rotation"] = matrix
    return result, offset


def _decode_number_sequence(data: bytes, offset: int) -> tuple[dict[str, Any], int]:
    count, offset = _read_u32(data, offset)
    keypoints = []
    for _ in range(count):
        envelope, offset = _read_f32(data, offset)
        time, offset = _read_f32(data, offset)
        value, offset = _read_f32(data, offset)
        keypoints.append({"Envelope": envelope, "Time": time, "Value": value})
    return {"__type": "NumberSequence", "Keypoints": keypoints}, offset


def _decode_color_sequence(data: bytes, offset: int) -> tuple[dict[str, Any], int]:
    count, offset = _read_u32(data, offset)
    keypoints = []
    for _ in range(count):
        envelope, offset = _read_f32(data, offset)
        time, offset = _read_f32(data, offset)
        color, offset = _decode_color3(data, offset)
        keypoints.append(
            {
                "Envelope": envelope,
                "Time": time,
                "Value": {"R": color["R"], "G": color["G"], "B": color["B"]},
            }
        )
    return {"__type": "ColorSequence", "Keypoints": keypoints}, offset


def _decode_font(data: bytes, offset: int) -> tuple[dict[str, Any], int]:
    weight, offset = _read_u16(data, offset)
    style, offset = _read_u8(data, offset)
    family, offset = _read_string(data, offset)
    cached, offset = _read_string(data, offset)
    return {
        "__type": "Font",
        "Weight": weight,
        "Style": style,
        "Family": family,
        "CachedFaceId": cached,
    }, offset


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------

def decode_attributes(raw: bytes | str) -> dict[str, Any]:
    """
    Decode an AttributesSerialize payload into a plain dict.

    Accepts either raw bytes or a Base64 string (as stored in the XML).
    Returns {} for empty / missing / invalid data.
    """
    if not raw:
        return {}

    if isinstance(raw, str):
        # Strip whitespace that sometimes appears in pretty-printed XML
        raw = raw.replace("\n", "").replace(" ", "").replace("\r", "")
        try:
            data = base64.b64decode(raw)
        except Exception:
            return {}
    else:
        data = raw

    if not data:
        return {}

    try:
        count, offset = _read_u32(data, 0)
    except Exception:
        return {}

    attrs: dict[str, Any] = {}

    for _ in range(count):
        if offset >= len(data):
            break
        try:
            name, offset = _read_string(data, offset)
            type_id, offset = _read_u8(data, offset)

            if type_id == 2:  # String
                value, offset = _read_string(data, offset)
            elif type_id == 3:  # Bool
                b, offset = _read_u8(data, offset)
                value = bool(b)
            elif type_id == 4:  # Int32
                value, offset = _read_i32(data, offset)
            elif type_id == 5:  # Float32
                value, offset = _read_f32(data, offset)
            elif type_id == 6:  # Float64
                value, offset = _read_f64(data, offset)
            elif type_id == 9:  # UDim
                value, offset = _decode_udim(data, offset)
            elif type_id == 10:  # UDim2
                x, offset = _decode_udim(data, offset)
                y, offset = _decode_udim(data, offset)
                value = {"__type": "UDim2", "X": x, "Y": y}
            elif type_id == 14:  # BrickColor
                value, offset = _read_u32(data, offset)
                value = {"__type": "BrickColor", "Number": value}
            elif type_id == 15:  # Color3
                value, offset = _decode_color3(data, offset)
            elif type_id == 16:  # Vector2
                value, offset = _decode_vector2(data, offset)
            elif type_id == 17:  # Vector3
                value, offset = _decode_vector3(data, offset)
            elif type_id == 20:  # CFrame
                value, offset = _decode_cframe(data, offset)
            elif type_id == 21:  # EnumItem (0x15)
                enum_name, offset = _read_string(data, offset)
                enum_value, offset = _read_u32(data, offset)
                value = {"__type": "EnumItem", "EnumType": enum_name, "Value": enum_value}
            elif type_id == 23:  # NumberSequence (0x17)
                value, offset = _decode_number_sequence(data, offset)
            elif type_id == 25:  # ColorSequence (0x19)
                value, offset = _decode_color_sequence(data, offset)
            elif type_id == 27:  # NumberRange (0x1B)
                mn, offset = _read_f32(data, offset)
                mx, offset = _read_f32(data, offset)
                value = {"__type": "NumberRange", "Min": mn, "Max": mx}
            elif type_id == 28:  # Rect (0x1C)
                mn, offset = _decode_vector2(data, offset)
                mx, offset = _decode_vector2(data, offset)
                value = {
                    "__type": "Rect",
                    "Min": {"X": mn["X"], "Y": mn["Y"]},
                    "Max": {"X": mx["X"], "Y": mx["Y"]},
                }
            elif type_id == 33:  # Font (0x21)
                value, offset = _decode_font(data, offset)
            else:
                # Unknown type – keep a marker and stop (cannot safely skip)
                value = {"__type": f"Unknown_{type_id}", "__raw_offset": offset}
                attrs[name] = value
                break

            attrs[name] = value
        except Exception:
            break

    return attrs


# ---------------------------------------------------------------------------
# Encode helpers for compound types
# ---------------------------------------------------------------------------

def _encode_udim(buf: bytearray, value: dict[str, Any]) -> None:
    _write_f32(buf, float(value.get("Scale", 0)))
    _write_i32(buf, int(value.get("Offset", 0)))


def _encode_vector2(buf: bytearray, value: dict[str, Any]) -> None:
    _write_f32(buf, float(value.get("X", 0)))
    _write_f32(buf, float(value.get("Y", 0)))


def _encode_vector3(buf: bytearray, value: dict[str, Any]) -> None:
    _write_f32(buf, float(value.get("X", 0)))
    _write_f32(buf, float(value.get("Y", 0)))
    _write_f32(buf, float(value.get("Z", 0)))


def _encode_color3(buf: bytearray, value: dict[str, Any]) -> None:
    _write_f32(buf, float(value.get("R", 0)))
    _write_f32(buf, float(value.get("G", 0)))
    _write_f32(buf, float(value.get("B", 0)))


def _encode_cframe(buf: bytearray, value: dict[str, Any]) -> None:
    pos = value.get("Position") or {}
    _encode_vector3(buf, pos if isinstance(pos, dict) else {})
    rot_id = int(value.get("RotationId", 0))
    _write_u8(buf, rot_id)
    if rot_id == 0:
        matrix = value.get("Rotation") or [0.0] * 9
        for v in matrix[:9]:
            _write_f32(buf, float(v))


def _encode_number_sequence(buf: bytearray, value: dict[str, Any]) -> None:
    keypoints = value.get("Keypoints") or []
    _write_u32(buf, len(keypoints))
    for kp in keypoints:
        _write_f32(buf, float(kp.get("Envelope", 0)))
        _write_f32(buf, float(kp.get("Time", 0)))
        _write_f32(buf, float(kp.get("Value", 0)))


def _encode_color_sequence(buf: bytearray, value: dict[str, Any]) -> None:
    keypoints = value.get("Keypoints") or []
    _write_u32(buf, len(keypoints))
    for kp in keypoints:
        _write_f32(buf, float(kp.get("Envelope", 0)))
        _write_f32(buf, float(kp.get("Time", 0)))
        color = kp.get("Value") or {}
        _encode_color3(buf, color if isinstance(color, dict) else {})


def _encode_font(buf: bytearray, value: dict[str, Any]) -> None:
    _write_u16(buf, int(value.get("Weight", 400)))
    _write_u8(buf, int(value.get("Style", 0)))
    _write_string(buf, str(value.get("Family", "")))
    _write_string(buf, str(value.get("CachedFaceId", "")))


# ---------------------------------------------------------------------------
# Encode
# ---------------------------------------------------------------------------

def encode_attributes(attrs: dict[str, Any] | None) -> bytes:
    """
    Encode a meta["Attributes"] dict back into the binary form
    that Roblox expects for AttributesSerialize.
    """
    if not attrs:
        return b""

    buf = bytearray()
    # We may skip some entries (unknown types); count is written at the end
    entries: list[tuple[str, Any]] = []

    for name, value in attrs.items():
        if isinstance(value, dict) and str(value.get("__type", "")).startswith("Unknown_"):
            continue  # cannot re-encode unknown types safely
        entries.append((str(name), value))

    _write_u32(buf, len(entries))

    for name, value in entries:
        _write_string(buf, name)

        if isinstance(value, dict) and "__type" in value:
            t = value["__type"]
            if t == "UDim":
                _write_u8(buf, 9)
                _encode_udim(buf, value)
            elif t == "UDim2":
                _write_u8(buf, 10)
                _encode_udim(buf, value.get("X") or {})
                _encode_udim(buf, value.get("Y") or {})
            elif t == "BrickColor":
                _write_u8(buf, 14)
                _write_u32(buf, int(value.get("Number", 0)))
            elif t == "Color3":
                _write_u8(buf, 15)
                _encode_color3(buf, value)
            elif t == "Vector2":
                _write_u8(buf, 16)
                _encode_vector2(buf, value)
            elif t == "Vector3":
                _write_u8(buf, 17)
                _encode_vector3(buf, value)
            elif t == "CFrame":
                _write_u8(buf, 20)
                _encode_cframe(buf, value)
            elif t == "EnumItem":
                _write_u8(buf, 21)
                _write_string(buf, str(value.get("EnumType", "")))
                _write_u32(buf, int(value.get("Value", 0)))
            elif t == "NumberSequence":
                _write_u8(buf, 23)
                _encode_number_sequence(buf, value)
            elif t == "ColorSequence":
                _write_u8(buf, 25)
                _encode_color_sequence(buf, value)
            elif t == "NumberRange":
                _write_u8(buf, 27)
                _write_f32(buf, float(value.get("Min", 0)))
                _write_f32(buf, float(value.get("Max", 0)))
            elif t == "Rect":
                _write_u8(buf, 28)
                _encode_vector2(buf, value.get("Min") or {})
                _encode_vector2(buf, value.get("Max") or {})
            elif t == "Font":
                _write_u8(buf, 33)
                _encode_font(buf, value)
            else:
                # Unknown structured type – skip
                continue
        elif isinstance(value, bool):
            _write_u8(buf, 3)
            _write_u8(buf, 1 if value else 0)
        elif isinstance(value, int):
            _write_u8(buf, 4)
            _write_i32(buf, value)
        elif isinstance(value, float):
            # Prefer Float64 for maximum precision
            _write_u8(buf, 6)
            _write_f64(buf, value)
        elif isinstance(value, str):
            _write_u8(buf, 2)
            _write_string(buf, value)
        else:
            # Fallback: stringify
            _write_u8(buf, 2)
            _write_string(buf, str(value))

    return bytes(buf)


def encode_attributes_b64(attrs: dict[str, Any] | None) -> str:
    """Convenience: return the Base64 string ready for the XML."""
    return base64.b64encode(encode_attributes(attrs)).decode("ascii")
