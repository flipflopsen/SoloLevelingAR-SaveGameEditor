"""Pure-stdlib decoder for Solo Leveling: ARISE OVERDRIVE ``GameData/*.byte`` tables.

Read-only analysis helper produced by the ``gamedata-decoder`` research pass.

Format (Confirmed -- see ``analysis/decoding_report.md``):

* The whole file is Rijndael-256 in CBC mode (block size 32 bytes, key size 32
  bytes, 14 rounds) with ``key == iv == b"levelup321" + b"\\x00" * 22``.
  Only ``len(data) - len(data) % 32`` bytes are decrypted; no padding is
  stripped, so up to 32 bytes of trailing filler may remain after the last
  column.
* The plaintext is a typed column-store:

  ``<u8 name_len><ascii table_name><i32 column_count><i32 row_count>``
  then, per column,
  ``<u8 name_len><ascii column_name><u8 type_byte><u32 meta>``
  followed by ``row_count`` values encoded according to ``type_byte``.

  String values use a .NET ``BinaryWriter`` 7-bit-encoded (base-128 varint)
  length prefix followed by UTF-8 bytes.

This module deliberately mirrors the semantics of ``vendor/gamedata.pyc``'s
``parse_typed`` (including its error conditions) so that the two can be diffed;
it does NOT import or execute that file, so it works on Python 3.12+ where the
3.10 bytecode in ``vendor/gamedata.pyc`` cannot be unmarshalled.
"""

from __future__ import annotations

import struct
from pathlib import Path

KEY = b"levelup321" + b"\x00" * 22
BLOCK_SIZE = 32

# Column ``type_byte`` -> value encoding. Taken verbatim from the vendor parser's
# _TYPED_* sets and independently confirmed by full-corpus round-trip equality.
TYPED_STR = frozenset({0, 9, 10, 11})
TYPED_I32 = frozenset({1, 2})
TYPED_I16 = frozenset({3})
TYPED_I64 = frozenset({5})
TYPED_F32 = frozenset({7})
TYPED_F64 = frozenset({6, 18})

_NAME_EXTRA_CHARS = (95, 46, 45, 32)  # _ . - space


def _build_sbox() -> tuple[bytes, bytes]:
    p = q = 1
    sbox = bytearray(256)
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        value = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6))
        value ^= ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        sbox[p] = (value ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    inv = bytearray(256)
    for i, s in enumerate(sbox):
        inv[s] = i
    return bytes(sbox), bytes(inv)


SBOX, INV_SBOX = _build_sbox()
RCON = (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36, 0x6C, 0xD8, 0xAB, 0x4D)


def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x1B) & 0xFF if a & 0x100 else a


def _gmul(a: int, b: int) -> int:
    result = 0
    for _ in range(8):
        if b & 1:
            result ^= a
        b >>= 1
        a = _xtime(a)
    return result


_MUL = {c: bytes(_gmul(x, c) for x in range(256)) for c in (9, 11, 13, 14)}


class Rijndael:
    """Rijndael with a 32-byte block and 32-byte key (a.k.a. Rijndael-256/256)."""

    NB = 8
    NK = 8
    NR = 14
    # Row shift amounts for Nb == 8 (FIPS/Rijndael spec: C1=1, C2=3, C3=4).
    _SHIFTS = (0, 1, 3, 4)

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("key must be 32 bytes")
        self._round_keys = self._expand(key)

    @classmethod
    def _expand(cls, key: bytes) -> list[list[int]]:
        words = [list(key[4 * i : 4 * i + 4]) for i in range(cls.NK)]
        total = cls.NB * (cls.NR + 1)
        for i in range(cls.NK, total):
            temp = list(words[i - 1])
            if i % cls.NK == 0:
                temp = temp[1:] + temp[:1]
                temp = [SBOX[b] for b in temp]
                temp[0] ^= RCON[i // cls.NK]
            elif cls.NK > 6 and i % cls.NK == 4:
                temp = [SBOX[b] for b in temp]
            prev = words[i - cls.NK]
            words.append([prev[j] ^ temp[j] for j in range(4)])
        return words

    def _add_round_key(self, state: list[list[int]], rnd: int) -> None:
        base = rnd * self.NB
        for c in range(self.NB):
            word = self._round_keys[base + c]
            for r in range(4):
                state[r][c] ^= word[r]

    def _inv_shift_rows(self, state: list[list[int]]) -> None:
        nb = self.NB
        for r in range(1, 4):
            shift = self._SHIFTS[r]
            row = state[r]
            state[r] = [row[(c - shift) % nb] for c in range(nb)]

    @staticmethod
    def _inv_sub_bytes(state: list[list[int]]) -> None:
        for r in range(4):
            state[r] = [INV_SBOX[b] for b in state[r]]

    def _inv_mix_columns(self, state: list[list[int]]) -> None:
        m9, m11, m13, m14 = _MUL[9], _MUL[11], _MUL[13], _MUL[14]
        for c in range(self.NB):
            a0, a1, a2, a3 = state[0][c], state[1][c], state[2][c], state[3][c]
            state[0][c] = m14[a0] ^ m11[a1] ^ m13[a2] ^ m9[a3]
            state[1][c] = m9[a0] ^ m14[a1] ^ m11[a2] ^ m13[a3]
            state[2][c] = m13[a0] ^ m9[a1] ^ m14[a2] ^ m11[a3]
            state[3][c] = m11[a0] ^ m13[a1] ^ m9[a2] ^ m14[a3]

    def decrypt_block(self, block: bytes) -> bytes:
        if len(block) != 4 * self.NB:
            raise ValueError("bad block length")
        state = [[block[c * 4 + r] for c in range(self.NB)] for r in range(4)]
        self._add_round_key(state, self.NR)
        for rnd in range(self.NR - 1, 0, -1):
            self._inv_shift_rows(state)
            self._inv_sub_bytes(state)
            self._add_round_key(state, rnd)
            self._inv_mix_columns(state)
        self._inv_shift_rows(state)
        self._inv_sub_bytes(state)
        self._add_round_key(state, 0)
        return bytes(state[r][c] for c in range(self.NB) for r in range(4))


def _cbc_decrypt_numpy(key: bytes, iv: bytes, data: bytes):
    """Vectorised CBC decrypt; returns ``None`` when numpy is unavailable.

    CBC *decryption* is embarrassingly parallel, so every block is processed at
    once. Only used to make bulk analysis of the 96 MB TextData.byte tractable;
    the pure-Python path above is the reference implementation and the two are
    asserted equal in ``tools/inspect_gamedata.py --self-test``.
    """
    try:
        import numpy as np
    except ModuleNotFoundError:  # pragma: no cover - optional acceleration
        return None
    n_blocks = len(data) // BLOCK_SIZE
    if n_blocks == 0:
        return b""
    cipher = Rijndael(key)
    rk = np.frombuffer(
        bytes(b for word in cipher._round_keys for b in word), dtype=np.uint8
    ).reshape(cipher.NR + 1, 8, 4)
    inv_sbox = np.frombuffer(INV_SBOX, dtype=np.uint8)
    mul = {c: np.frombuffer(_MUL[c], dtype=np.uint8) for c in (9, 11, 13, 14)}
    ct = np.frombuffer(data[: n_blocks * BLOCK_SIZE], dtype=np.uint8).reshape(n_blocks, 8, 4)
    state = ct.copy()
    shift_idx = [np.arange(8) for _ in range(4)]
    for r in range(1, 4):
        shift_idx[r] = (np.arange(8) - Rijndael._SHIFTS[r]) % 8

    def inv_shift_rows(st):
        out = st.copy()
        for r in range(1, 4):
            out[:, :, r] = st[:, shift_idx[r], r]
        return out

    state = state ^ rk[cipher.NR]
    for rnd in range(cipher.NR - 1, 0, -1):
        state = inv_shift_rows(state)
        state = inv_sbox[state]
        state = state ^ rk[rnd]
        a0, a1, a2, a3 = state[:, :, 0], state[:, :, 1], state[:, :, 2], state[:, :, 3]
        state = np.stack(
            [
                mul[14][a0] ^ mul[11][a1] ^ mul[13][a2] ^ mul[9][a3],
                mul[9][a0] ^ mul[14][a1] ^ mul[11][a2] ^ mul[13][a3],
                mul[13][a0] ^ mul[9][a1] ^ mul[14][a2] ^ mul[11][a3],
                mul[11][a0] ^ mul[13][a1] ^ mul[9][a2] ^ mul[14][a3],
            ],
            axis=-1,
        )
    state = inv_shift_rows(state)
    state = inv_sbox[state]
    state = state ^ rk[0]
    prev = np.empty_like(ct)
    prev[0] = np.frombuffer(iv, dtype=np.uint8).reshape(8, 4)
    prev[1:] = ct[:-1]
    return (state ^ prev).tobytes()


def cbc_decrypt(key: bytes, iv: bytes, data: bytes, block_size: int = BLOCK_SIZE) -> bytes:
    if block_size == BLOCK_SIZE and len(data) >= 64 * BLOCK_SIZE:
        fast = _cbc_decrypt_numpy(key, iv, data)
        if fast is not None:
            return fast
    cipher = Rijndael(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), block_size):
        block = data[i : i + block_size]
        decrypted = cipher.decrypt_block(block)
        out.extend(x ^ y for x, y in zip(decrypted, prev, strict=False))
        prev = block
    return bytes(out)


def decrypt_bytes_file(data: bytes) -> bytes:
    """Decrypt a raw ``.byte`` payload to its plaintext table image."""
    usable = len(data) - len(data) % BLOCK_SIZE
    return cbc_decrypt(KEY, KEY, data[:usable], BLOCK_SIZE)


def _read_7bit_len(pt: bytes, p: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        b = pt[p]
        p += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, p
        shift += 7


def _read_name(pt: bytes, o: int) -> tuple[str, int]:
    ln = pt[o]
    return pt[o + 1 : o + 1 + ln].decode("latin1"), o + 1 + ln


def _looks_like_name(pt: bytes, o: int) -> bool:
    if o >= len(pt):
        return False
    ln = pt[o]
    if not 1 <= ln <= 64 or o + 1 + ln > len(pt):
        return False
    return all(
        65 <= b <= 90 or 97 <= b <= 122 or 48 <= b <= 57 or b in _NAME_EXTRA_CHARS
        for b in pt[o + 1 : o + 1 + ln]
    )


def parse_plaintext(pt: bytes, label: str = "<buffer>") -> tuple[dict[str, list], int, str]:
    """Parse a decrypted table image into ``(columns, row_count, table_name)``."""
    table_name, o = _read_name(pt, 0)
    column_count = struct.unpack_from("<i", pt, o)[0]
    row_count = struct.unpack_from("<i", pt, o + 4)[0]
    o += 8
    columns: dict[str, list] = {}
    for c in range(column_count):
        if not _looks_like_name(pt, o):
            raise RuntimeError(f"typed: col {c} name unreadable at offset {o}")
        name, o2 = _read_name(pt, o)
        type_byte = pt[o2]
        meta = struct.unpack_from("<I", pt, o2 + 1)[0]
        o = o2 + 5
        if meta & 0x01000000 or type_byte in TYPED_STR:
            values: list = []
            for _ in range(row_count):
                ln, p2 = _read_7bit_len(pt, o)
                if p2 + ln > len(pt):
                    raise RuntimeError(f"typed: string overrun in col {name!r}")
                values.append(pt[p2 : p2 + ln].decode("utf-8", errors="replace"))
                o = p2 + ln
        elif type_byte in TYPED_I32:
            values = [struct.unpack_from("<i", pt, o + 4 * i)[0] for i in range(row_count)]
            o += 4 * row_count
        elif type_byte in TYPED_F32:
            values = [struct.unpack_from("<f", pt, o + 4 * i)[0] for i in range(row_count)]
            o += 4 * row_count
        elif type_byte in TYPED_I64:
            values = [struct.unpack_from("<q", pt, o + 8 * i)[0] for i in range(row_count)]
            o += 8 * row_count
        elif type_byte in TYPED_F64:
            values = [struct.unpack_from("<d", pt, o + 8 * i)[0] for i in range(row_count)]
            o += 8 * row_count
        elif type_byte in TYPED_I16:
            values = [struct.unpack_from("<h", pt, o + 2 * i)[0] for i in range(row_count)]
            o += 2 * row_count
        else:
            raise RuntimeError(
                f"typed: UNKNOWN column type byte {type_byte} "
                f"(col {name!r} #{c} of {column_count}, offset {o2}) in {label}"
            )
        if o > len(pt):
            raise RuntimeError(f"typed: overran buffer in col {name!r}")
        columns[name] = values
    if len(pt) - o >= 33:
        raise RuntimeError(f"typed: {len(pt) - o} bytes left over after last column")
    return columns, row_count, table_name


def parse_typed(path: str | Path) -> tuple[dict[str, list], int]:
    """Drop-in equivalent of ``vendor/gamedata.pyc``'s ``parse_typed``."""
    columns, row_count, _ = parse_file(path)
    return columns, row_count


def parse_file(path: str | Path) -> tuple[dict[str, list], int, str]:
    path = Path(path)
    plaintext = decrypt_bytes_file(path.read_bytes())
    return parse_plaintext(plaintext, path.name)


def column_types(path: str | Path) -> dict[str, int]:
    """Return ``{column_name: type_byte}`` without materialising values."""
    pt = decrypt_bytes_file(Path(path).read_bytes())
    _, o = _read_name(pt, 0)
    column_count = struct.unpack_from("<i", pt, o)[0]
    row_count = struct.unpack_from("<i", pt, o + 4)[0]
    o += 8
    out: dict[str, int] = {}
    for _c in range(column_count):
        name, o2 = _read_name(pt, o)
        type_byte = pt[o2]
        meta = struct.unpack_from("<I", pt, o2 + 1)[0]
        out[name] = type_byte
        o = o2 + 5
        if meta & 0x01000000 or type_byte in TYPED_STR:
            for _ in range(row_count):
                ln, p2 = _read_7bit_len(pt, o)
                o = p2 + ln
        elif type_byte in TYPED_I32 or type_byte in TYPED_F32:
            o += 4 * row_count
        elif type_byte in TYPED_I64 or type_byte in TYPED_F64:
            o += 8 * row_count
        elif type_byte in TYPED_I16:
            o += 2 * row_count
        else:
            break
    return out
