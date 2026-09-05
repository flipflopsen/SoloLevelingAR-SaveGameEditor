#!/usr/bin/env python3
"""Standalone save-database inspection tool.

Opens a local, owner-provided ``LocalSave_*.db`` file with the game's
installed ``sqlcipher.dll`` and either lists its tables or runs a
read-only SQL query against it. This script is fully self-contained
(standard library ``ctypes`` only) and does not depend on the rest of the
SaveGameEditor package, so it can be copied and run on its own.

Windows only, because it loads the game's bundled SQLCipher DLL.

Usage:
    # Derive the key from a SteamID64 and list tables:
    python decrypt_save.py path\\to\\LocalSave_0.db --steam-id 7656119XXXXXXXXXX ^
        --game-data "C:\\...\\GameData"

    # Or supply an already-derived save key directly:
    python decrypt_save.py path\\to\\LocalSave_0.db --key <base64-key> ^
        --dll-dir "C:\\...\\Solo_Leveling_ARISE_OVERDRIVE_Data\\Plugins\\x86_64"

    # Run a read-only query instead of listing tables:
    python decrypt_save.py path\\to\\LocalSave_0.db --steam-id ... --game-data ... ^
        --query "SELECT * FROM PlayerData LIMIT 5"
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import sys
from ctypes import byref, c_char_p, c_double, c_int, c_int64, c_void_p
from pathlib import Path
from typing import Any

DERIVATION_KEY = b"levelup321" + (b"\x00" * 22)
GAME_INSTALL_DIRECTORY = "Solo_Leveling_ARISE_OVERDRIVE_Data"
SQLCIPHER_PLUGIN_SUBDIRECTORY = Path("Plugins") / "x86_64"

SQLITE_DONE = 101
SQLITE_FLOAT = 2
SQLITE_INTEGER = 1
SQLITE_NULL = 5
SQLITE_OK = 0
SQLITE_ROW = 100
SQLITE_TEXT = 3


class SaveEditorError(RuntimeError):
    """A recoverable error that can be shown as a concise message."""


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
    """Derive a base64-encoded save key from a conventional 17-digit SteamID64."""
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


def derive_dll_directory(game_data_path: Path) -> Path:
    """Derive the DLL location from a sibling ``GameData`` installation directory."""
    return game_data_path.parent / GAME_INSTALL_DIRECTORY / SQLCIPHER_PLUGIN_SUBDIRECTORY


class SqlCipherDatabase:
    """Connection wrapper for the game's bundled SQLCipher DLL."""

    def __init__(self, path: Path, key: str, dll_directory: Path) -> None:
        if not path.is_file():
            raise SaveEditorError(f"Save file not found: {path}")
        dll_path = dll_directory / "sqlcipher.dll"
        if not dll_path.is_file():
            raise SaveEditorError(f"sqlcipher.dll not found in: {dll_directory}")
        if not hasattr(ctypes, "windll"):
            raise SaveEditorError("The game SQLCipher DLL requires Windows.")

        ctypes.windll.kernel32.SetDllDirectoryW(str(dll_directory))
        self._library = ctypes.CDLL(str(dll_path))
        self._connection = c_void_p()
        self._configure_api()
        result = self._library.sqlite3_open(str(path).encode("utf-8"), byref(self._connection))
        if result != SQLITE_OK:
            raise SaveEditorError(f"Could not open the save ({result}): {self._error_message()}")
        key_bytes = key.encode("ascii")
        result = self._library.sqlite3_key(self._connection, key_bytes, len(key_bytes))
        if result != SQLITE_OK:
            self.close()
            raise SaveEditorError(
                f"Could not apply the save key ({result}): {self._error_message()}"
            )
        for pragma in (
            "PRAGMA cipher_compatibility = 4",
            "PRAGMA kdf_iter = 256000",
            "PRAGMA cipher_page_size = 4096",
            "PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512",
            "PRAGMA cipher_hmac_algorithm = HMAC_SHA512",
        ):
            self.execute(pragma)
        self.query("SELECT count(*) FROM sqlite_master")

    def _configure_api(self) -> None:
        library = self._library
        library.sqlite3_open.argtypes = [c_char_p, ctypes.POINTER(c_void_p)]
        library.sqlite3_open.restype = c_int
        library.sqlite3_close.argtypes = [c_void_p]
        library.sqlite3_close.restype = c_int
        library.sqlite3_key.argtypes = [c_void_p, c_void_p, c_int]
        library.sqlite3_key.restype = c_int
        library.sqlite3_errmsg.argtypes = [c_void_p]
        library.sqlite3_errmsg.restype = c_char_p
        library.sqlite3_exec.argtypes = [
            c_void_p,
            c_char_p,
            c_void_p,
            c_void_p,
            ctypes.POINTER(c_char_p),
        ]
        library.sqlite3_exec.restype = c_int
        library.sqlite3_prepare_v2.argtypes = [
            c_void_p,
            c_char_p,
            c_int,
            ctypes.POINTER(c_void_p),
            c_void_p,
        ]
        library.sqlite3_prepare_v2.restype = c_int
        library.sqlite3_step.argtypes = [c_void_p]
        library.sqlite3_step.restype = c_int
        library.sqlite3_finalize.argtypes = [c_void_p]
        library.sqlite3_finalize.restype = c_int
        library.sqlite3_column_count.argtypes = [c_void_p]
        library.sqlite3_column_count.restype = c_int
        library.sqlite3_column_type.argtypes = [c_void_p, c_int]
        library.sqlite3_column_type.restype = c_int
        library.sqlite3_column_int64.argtypes = [c_void_p, c_int]
        library.sqlite3_column_int64.restype = c_int64
        library.sqlite3_column_double.argtypes = [c_void_p, c_int]
        library.sqlite3_column_double.restype = c_double
        library.sqlite3_column_blob.argtypes = [c_void_p, c_int]
        library.sqlite3_column_blob.restype = c_void_p
        library.sqlite3_column_bytes.argtypes = [c_void_p, c_int]
        library.sqlite3_column_bytes.restype = c_int

    def _error_message(self) -> str:
        message = self._library.sqlite3_errmsg(self._connection)
        return message.decode("utf-8", "replace") if message else "unknown SQLCipher error"

    def execute(self, sql: str) -> None:
        error = c_char_p()
        result = self._library.sqlite3_exec(
            self._connection, sql.encode("utf-8"), None, None, byref(error)
        )
        if result != SQLITE_OK:
            message = (
                error.value.decode("utf-8", "replace") if error.value else self._error_message()
            )
            raise SaveEditorError(f"SQLCipher rejected the change: {message}")

    def query(self, sql: str) -> list[tuple[Any, ...]]:
        statement = c_void_p()
        result = self._library.sqlite3_prepare_v2(
            self._connection, sql.encode("utf-8"), -1, byref(statement), None
        )
        if result != SQLITE_OK:
            raise SaveEditorError(f"SQLCipher query failed: {self._error_message()}")
        rows: list[tuple[Any, ...]] = []
        try:
            column_count = self._library.sqlite3_column_count(statement)
            while (result := self._library.sqlite3_step(statement)) == SQLITE_ROW:
                rows.append(
                    tuple(self._column_value(statement, index) for index in range(column_count))
                )
            if result != SQLITE_DONE:
                raise SaveEditorError(f"SQLCipher query failed: {self._error_message()}")
            return rows
        finally:
            self._library.sqlite3_finalize(statement)

    def _column_value(self, statement: c_void_p, index: int) -> Any:
        value_type = self._library.sqlite3_column_type(statement, index)
        if value_type == SQLITE_NULL:
            return None
        if value_type == SQLITE_INTEGER:
            return self._library.sqlite3_column_int64(statement, index)
        if value_type == SQLITE_FLOAT:
            return self._library.sqlite3_column_double(statement, index)
        pointer = self._library.sqlite3_column_blob(statement, index)
        length = self._library.sqlite3_column_bytes(statement, index)
        raw = ctypes.string_at(pointer, length) if pointer and length else b""
        return raw.decode("utf-8", "replace") if value_type == SQLITE_TEXT else raw

    def close(self) -> None:
        if self._connection.value:
            self._library.sqlite3_close(self._connection)
            self._connection = c_void_p()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open a local save database and list tables or run a read-only query.",
    )
    parser.add_argument("database", type=Path, help="Path to the LocalSave_*.db file.")
    key_group = parser.add_mutually_exclusive_group(required=True)
    key_group.add_argument("--steam-id", help="17-digit SteamID64 used to derive the save key.")
    key_group.add_argument("--key", help="An already-derived base64 save key.")
    dll_group = parser.add_mutually_exclusive_group(required=True)
    dll_group.add_argument(
        "--game-data",
        type=Path,
        help="Path to the installed GameData directory (used to derive the DLL directory).",
    )
    dll_group.add_argument(
        "--dll-dir",
        type=Path,
        help="Explicit directory containing sqlcipher.dll.",
    )
    parser.add_argument(
        "--query",
        help="Read-only SQL query to run instead of listing tables (e.g. 'SELECT * FROM T').",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        key = args.key or derive_save_key(args.steam_id)
        dll_directory = args.dll_dir or derive_dll_directory(args.game_data)
        database = SqlCipherDatabase(args.database, key, dll_directory)
    except SaveEditorError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    try:
        if args.query:
            rows = database.query(args.query)
            for row in rows:
                print(row)
        else:
            tables = database.query(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
            for (name,) in tables:
                print(name)
    except SaveEditorError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
