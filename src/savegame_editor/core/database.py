"""Minimal local ctypes wrapper for the game's bundled SQLCipher DLL."""

from __future__ import annotations

import ctypes
from ctypes import byref, c_char_p, c_double, c_int, c_int64, c_void_p
from pathlib import Path
from typing import Any

from .encryption import SaveEditorError

SQLITE_DONE = 101
SQLITE_FLOAT = 2
SQLITE_INTEGER = 1
SQLITE_NULL = 5
SQLITE_OK = 0
SQLITE_ROW = 100
SQLITE_TEXT = 3


class SqlCipherDatabase:
    """Connection wrapper limited to the SQL needed by the verified editor surface."""

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
