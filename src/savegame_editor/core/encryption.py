"""Save-key derivation compatible with the game's Rijndael-256 implementation."""

from __future__ import annotations

import base64

DERIVATION_KEY = b"levelup321" + (b"\x00" * 22)


class SaveEditorError(RuntimeError):
    """A recoverable error that can be shown as a concise UI message."""


def _gf_multiply(left: int, right: int) -> int:
    result = 0
    while right:
        if right & 1:
            result ^= left
        left = ((left << 1) ^ (0x11B if left & 0x80 else 0)) & 0xFF
        right >>= 1
    return result


def _gf_power(value: int, exponent: int) -> int:
    result = 1
    while exponent:
        if exponent & 1:
            result = _gf_multiply(result, value)
        value = _gf_multiply(value, value)
        exponent >>= 1
    return result


def _rotate_byte(value: int, places: int) -> int:
    return ((value << places) | (value >> (8 - places))) & 0xFF


SBOX = [
    (_gf_power(value, 254) if value else 0)
    ^ _rotate_byte(_gf_power(value, 254) if value else 0, 1)
    ^ _rotate_byte(_gf_power(value, 254) if value else 0, 2)
    ^ _rotate_byte(_gf_power(value, 254) if value else 0, 3)
    ^ _rotate_byte(_gf_power(value, 254) if value else 0, 4)
    ^ 0x63
    for value in range(256)
]


def derive_save_key(steam_id: str) -> str:
    """Derive a save key from a conventional 17-digit SteamID64."""
    if not steam_id.isascii() or not steam_id.isdecimal() or len(steam_id) != 17:
        raise SaveEditorError("Steam ID must be a 17-digit SteamID64.")
    words = [list(DERIVATION_KEY[index : index + 4]) for index in range(0, 32, 4)]
    rcon = 1
    while len(words) < 120:
        temporary = words[-1].copy()
        if len(words) % 8 == 0:
            temporary = [SBOX[value] for value in temporary[1:] + temporary[:1]]
            temporary[0] ^= rcon
            rcon = _gf_multiply(rcon, 2)
        elif len(words) % 8 == 4:
            temporary = [SBOX[value] for value in temporary]
        words.append([words[-8][index] ^ temporary[index] for index in range(4)])

    def encrypt(block: bytes) -> bytes:
        state = list(block)
        for round_index in range(15):
            if round_index:
                state = [SBOX[value] for value in state]
                for row, shift in enumerate((0, 1, 3, 4)):
                    values = [state[row + 4 * column] for column in range(8)]
                    values = values[shift:] + values[:shift]
                    for column, value in enumerate(values):
                        state[row + 4 * column] = value
                if round_index != 14:
                    for column in range(8):
                        offset = column * 4
                        first, second, third, fourth = state[offset : offset + 4]
                        state[offset : offset + 4] = [
                            _gf_multiply(first, 2) ^ _gf_multiply(second, 3) ^ third ^ fourth,
                            first ^ _gf_multiply(second, 2) ^ _gf_multiply(third, 3) ^ fourth,
                            first ^ second ^ _gf_multiply(third, 2) ^ _gf_multiply(fourth, 3),
                            _gf_multiply(first, 3) ^ second ^ third ^ _gf_multiply(fourth, 2),
                        ]
            for column, word in enumerate(words[round_index * 8 : round_index * 8 + 8]):
                for row, value in enumerate(word):
                    state[row + 4 * column] ^= value
        return bytes(state)

    plaintext = steam_id.encode("ascii")
    padded = plaintext + bytes([32 - len(plaintext)]) * (32 - len(plaintext))
    previous = DERIVATION_KEY
    ciphertext = bytearray()
    for offset in range(0, len(padded), 32):
        previous = encrypt(
            bytes(
                left ^ right
                for left, right in zip(padded[offset : offset + 32], previous, strict=True)
            )
        )
        ciphertext.extend(previous)
    return base64.b64encode(ciphertext).decode("ascii")
