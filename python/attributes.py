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
    """Encode Color3 channels. Accepts R/G/B or r/g/b keys, or a 3-list.

    Missing channels still default to 0 (black). Prefer uppercase keys from
    decode; lowercase is accepted so partial / hand-edited metas do not
    silently zero a channel that was present under a different case.
    """
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        r, g, b = float(value[0]), float(value[1]), float(value[2])
    else:
        r = value.get("R", value.get("r", 0))
        g = value.get("G", value.get("g", 0))
        b = value.get("B", value.get("b", 0))
        r = float(r) if r is not None else 0.0
        g = float(g) if g is not None else 0.0
        b = float(b) if b is not None else 0.0
    _write_f32(buf, r)
    _write_f32(buf, g)
    _write_f32(buf, b)


# Identity rotation matrix — used when Rotation is missing, incomplete, or
# all-zero. A zero matrix is singular; Roblox engine CFrame construction then
# places the instance at extreme Y (commonly ~0, -100000, 0) and orientation is
# lost. Identity at the encoded Position (or origin) is the safe fallback.
_IDENTITY_ROTATION = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]


def _encode_cframe(buf: bytearray, value: dict[str, Any]) -> None:
    """Encode CFrame from either native or Live Sync (Luau) shape.

    Native (decode output):
      {Position: {X,Y,Z}, RotationId: int, Rotation?: [9 floats]}
    Luau encodeValue (Live Sync experimental property sync):
      {components: [x,y,z, r00..r22]}  — 12 floats, treated as RotationId=0

    Guard: when Rotation is absent, incomplete, or the zero matrix, write the
    identity matrix instead. This prevents the engine sentinel position that
    appeared on corrupted assets (favourite chair / sub-models at Y≈-1e5).
    """
    components = value.get("components")
    if isinstance(components, (list, tuple)) and len(components) >= 12:
        # Luau shape → full matrix form
        pos = {
            "X": float(components[0]),
            "Y": float(components[1]),
            "Z": float(components[2]),
        }
        matrix = [float(v) for v in components[3:12]]
        # Still guard a zero/singular matrix that may arrive from Luau
        if all(abs(v) < 1e-12 for v in matrix):
            matrix = list(_IDENTITY_ROTATION)
        _encode_vector3(buf, pos)
        _write_u8(buf, 0)  # RotationId = 0 → arbitrary matrix follows
        for v in matrix:
            _write_f32(buf, v)
        return

    pos = value.get("Position") or {}
    _encode_vector3(buf, pos if isinstance(pos, dict) else {})
    rot_id = int(value.get("RotationId", 0))
    _write_u8(buf, rot_id)
    if rot_id == 0:
        matrix = value.get("Rotation")
        if (
            not matrix
            or not isinstance(matrix, (list, tuple))
            or len(matrix) < 9
            or all(abs(float(v)) < 1e-12 for v in matrix[:9])
        ):
            matrix = list(_IDENTITY_ROTATION)
        else:
            matrix = [float(v) for v in matrix[:9]]
        for v in matrix:
            _write_f32(buf, v)


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


# Known structured __type values that have an encoder path.
_KNOWN_STRUCTURED = frozenset({
    "UDim", "UDim2", "BrickColor", "Color3", "Vector2", "Vector3",
    "CFrame", "EnumItem", "NumberSequence", "ColorSequence",
    "NumberRange", "Rect", "Font",
})


def _is_encodable(value: Any) -> bool:
    """True if this attribute value can be written without leaving a hole."""
    if isinstance(value, dict) and "__type" in value:
        t = str(value.get("__type", ""))
        if t.startswith("Unknown_"):
            return False
        return t in _KNOWN_STRUCTURED
    return isinstance(value, (bool, int, float, str))


# ---------------------------------------------------------------------------
# Encode
# ---------------------------------------------------------------------------

def encode_attributes(attrs: dict[str, Any] | None) -> bytes:
    """
    Encode a meta["Attributes"] dict back into the binary form
    that Roblox expects for AttributesSerialize.

    Only entries that have a known encoder path are counted and written.
    Unknown structured types and Unknown_* markers are skipped entirely so
    the leading u32 count always matches the body (no desync / misalignment).

    Accepts both native shapes (from decode) and Live Sync Luau shapes for
    CFrame (components list) and EnumItem (Name instead of / in addition to Value).
    """
    if not attrs:
        return b""

    # Filter first so the count is exact — never write a name without a value.
    entries: list[tuple[str, Any]] = []
    for name, value in attrs.items():
        if _is_encodable(value):
            entries.append((str(name), value))

    buf = bytearray()
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
                # Luau shape carries Name; native shape carries Value (u32).
                # Binary format only has the numeric Value — default 0 when absent.
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
            # All other structured types were filtered by _is_encodable
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
            # Fallback: stringify (should be unreachable after _is_encodable)
            _write_u8(buf, 2)
            _write_string(buf, str(value))

    return bytes(buf)


def encode_attributes_b64(attrs: dict[str, Any] | None) -> str:
    """Convenience: return the Base64 string ready for the XML."""
    return base64.b64encode(encode_attributes(attrs)).decode("ascii")
