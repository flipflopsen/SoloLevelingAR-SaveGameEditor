"""Read-only forensic inspector for Solo Leveling: ARISE OVERDRIVE local saves.

Standard-library only. Accepts either

* a decrypted SQL dump (``.sql``), loaded into an in-memory SQLite database, or
* an encrypted SQLCipher ``.db`` save, opened through the game's bundled
  ``sqlcipher.dll`` via ``ctypes`` (Windows only).

It never writes to its input. Encrypted saves are copied to a scratch
directory before being opened, so SQLCipher journal/WAL side files can never
touch the original artifact.

Reported per source:

* schema summary (tables / indexes / triggers, optional full DDL)
* distinct values of every account/profile and row-role discriminator column
* the main-player row and active stat block discovered with the *dynamic*
  query (no literal account ID, row ID, slot index or catalog ID)
* row counts per key table

Examples::

    python tools/inspect_saves.py OldDevelopingFiles/Dumped/LocalSave_MySave.db.sql
    python tools/inspect_saves.py save.db --steam-id 7656119... --dll-dir "...\\Plugins\\x86_64"
    python tools/inspect_saves.py save.db --key "base64key==" --dll-dir ... --json out.json
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import json
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from ctypes import byref, c_char_p, c_double, c_int, c_int64, c_void_p
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# Obfuscated schema names this tool understands.
# --------------------------------------------------------------------------
LEVELS_TABLE = "tb_13c52bbaa8"  # main character + unit roster, one row per unit
STATS_TABLE = "tb_957a223c9b"  # per-character stat presets (5 slots)
WALLET_TABLE = "tb_e973c32e29"  # one row per account (account column is the PK)

ACCOUNT_COLUMN = "c_3536de9619"  # account/profile ID; PK of the wallet table
RECORD_TYPE_COLUMN = "c_d79538c3b8"  # roster record type; 0 == main character
CATALOG_ID_COLUMN = "c_9398111a4b"  # unit catalog ID (NOT a slot/ordinal)
CHARACTER_ID_COLUMN = "c_d4f6740b9b"  # PK of the levels table / FK on the stats table
LEVEL_COLUMN = "c_e3aa3bf474"
STATS_ROW_ID_COLUMN = "c_fc7ba2e8c9"
PRESET_SLOT_COLUMN = "c_1692f32794"  # 0..4, progression/user dependent
ACTIVE_PRESET_COLUMN = "c_bc37480bfc"  # exactly one row == 1 per character

KEY_TABLES = {
    LEVELS_TABLE: "characters and unit roster",
    STATS_TABLE: "stat presets",
    WALLET_TABLE: "wallet",
    "tb_d40f87183c": "inventory",
    "tb_adfb9b0bf5": "owned artifacts",
    "tb_16b100425f": "owned relic weapons",
    "tb_bc88081733": "owned hunter weapons",
    "tb_ab102d50ba": "owned blessing stones",
    "tb_4b5c76b06a": "cosmetics",
    "tb_cc2254ea5d": "titles",
    "tb_3352b063a3": "achievements",
    "tb_bf41c3a26c": "story difficulty",
}

# --------------------------------------------------------------------------
# Save-key derivation (Rijndael-256, mirrors the game's implementation).
# --------------------------------------------------------------------------
DERIVATION_KEY = b"levelup321" + (b"\x00" * 22)


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


_SBOX = [
    (_gf_power(v, 254) if v else 0)
    ^ _rotate_byte(_gf_power(v, 254) if v else 0, 1)
    ^ _rotate_byte(_gf_power(v, 254) if v else 0, 2)
    ^ _rotate_byte(_gf_power(v, 254) if v else 0, 3)
    ^ _rotate_byte(_gf_power(v, 254) if v else 0, 4)
    ^ 0x63
    for v in range(256)
]


def derive_save_key(steam_id: str) -> str:
    """Derive the SQLCipher key from a 17-digit SteamID64."""
    if not steam_id.isascii() or not steam_id.isdecimal() or len(steam_id) != 17:
        raise ValueError("Steam ID must be a 17-digit SteamID64.")
    words = [list(DERIVATION_KEY[i : i + 4]) for i in range(0, 32, 4)]
    rcon = 1
    while len(words) < 120:
        temporary = words[-1].copy()
        if len(words) % 8 == 0:
            temporary = [_SBOX[v] for v in temporary[1:] + temporary[:1]]
            temporary[0] ^= rcon
            rcon = _gf_multiply(rcon, 2)
        elif len(words) % 8 == 4:
            temporary = [_SBOX[v] for v in temporary]
        words.append([words[-8][i] ^ temporary[i] for i in range(4)])

    def encrypt(block: bytes) -> bytes:
        state = list(block)
        for round_index in range(15):
            if round_index:
                state = [_SBOX[v] for v in state]
                for row, shift in enumerate((0, 1, 3, 4)):
                    values = [state[row + 4 * column] for column in range(8)]
                    values = values[shift:] + values[:shift]
                    for column, value in enumerate(values):
                        state[row + 4 * column] = value
                if round_index != 14:
                    for column in range(8):
                        offset = column * 4
                        a, b, c, d = state[offset : offset + 4]
                        state[offset : offset + 4] = [
                            _gf_multiply(a, 2) ^ _gf_multiply(b, 3) ^ c ^ d,
                            a ^ _gf_multiply(b, 2) ^ _gf_multiply(c, 3) ^ d,
                            a ^ b ^ _gf_multiply(c, 2) ^ _gf_multiply(d, 3),
                            _gf_multiply(a, 3) ^ b ^ c ^ _gf_multiply(d, 2),
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
            bytes(x ^ y for x, y in zip(padded[offset : offset + 32], previous, strict=True))
        )
        ciphertext.extend(previous)
    return base64.b64encode(ciphertext).decode("ascii")


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------
Query = Callable[[str], list[tuple[Any, ...]]]

SQLITE_DONE, SQLITE_OK, SQLITE_ROW = 101, 0, 100
SQLITE_INTEGER, SQLITE_FLOAT, SQLITE_TEXT, SQLITE_NULL = 1, 2, 3, 5


class SqlCipherReader:
    """Minimal read-only ctypes wrapper around the game's sqlcipher.dll."""

    def __init__(self, path: Path, key: str, dll_directory: Path) -> None:
        dll_path = dll_directory / "sqlcipher.dll"
        if not dll_path.is_file():
            raise FileNotFoundError(f"sqlcipher.dll not found in: {dll_directory}")
        if not hasattr(ctypes, "windll"):
            raise RuntimeError("The bundled SQLCipher DLL requires Windows.")
        ctypes.windll.kernel32.SetDllDirectoryW(str(dll_directory))
        self._library = ctypes.CDLL(str(dll_path))
        self._connection = c_void_p()
        self._configure()
        if self._library.sqlite3_open(str(path).encode("utf-8"), byref(self._connection)):
            raise RuntimeError(f"Could not open {path}: {self._error()}")
        key_bytes = key.encode("ascii")
        if self._library.sqlite3_key(self._connection, key_bytes, len(key_bytes)):
            raise RuntimeError(f"Could not apply the save key: {self._error()}")
        for pragma in (
            "PRAGMA cipher_compatibility = 4",
            "PRAGMA kdf_iter = 256000",
            "PRAGMA cipher_page_size = 4096",
            "PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512",
            "PRAGMA cipher_hmac_algorithm = HMAC_SHA512",
        ):
            self.query(pragma)
        self.query("SELECT count(*) FROM sqlite_master")

    def _configure(self) -> None:
        lib = self._library
        lib.sqlite3_open.argtypes = [c_char_p, ctypes.POINTER(c_void_p)]
        lib.sqlite3_open.restype = c_int
        lib.sqlite3_close.argtypes = [c_void_p]
        lib.sqlite3_close.restype = c_int
        lib.sqlite3_key.argtypes = [c_void_p, c_void_p, c_int]
        lib.sqlite3_key.restype = c_int
        lib.sqlite3_errmsg.argtypes = [c_void_p]
        lib.sqlite3_errmsg.restype = c_char_p
        lib.sqlite3_prepare_v2.argtypes = [
            c_void_p,
            c_char_p,
            c_int,
            ctypes.POINTER(c_void_p),
            c_void_p,
        ]
        lib.sqlite3_prepare_v2.restype = c_int
        lib.sqlite3_step.argtypes = [c_void_p]
        lib.sqlite3_step.restype = c_int
        lib.sqlite3_finalize.argtypes = [c_void_p]
        lib.sqlite3_finalize.restype = c_int
        lib.sqlite3_column_count.argtypes = [c_void_p]
        lib.sqlite3_column_count.restype = c_int
        lib.sqlite3_column_type.argtypes = [c_void_p, c_int]
        lib.sqlite3_column_type.restype = c_int
        lib.sqlite3_column_int64.argtypes = [c_void_p, c_int]
        lib.sqlite3_column_int64.restype = c_int64
        lib.sqlite3_column_double.argtypes = [c_void_p, c_int]
        lib.sqlite3_column_double.restype = c_double
        lib.sqlite3_column_blob.argtypes = [c_void_p, c_int]
        lib.sqlite3_column_blob.restype = c_void_p
        lib.sqlite3_column_bytes.argtypes = [c_void_p, c_int]
        lib.sqlite3_column_bytes.restype = c_int

    def _error(self) -> str:
        message = self._library.sqlite3_errmsg(self._connection)
        return message.decode("utf-8", "replace") if message else "unknown SQLCipher error"

    def query(self, sql: str) -> list[tuple[Any, ...]]:
        statement = c_void_p()
        if self._library.sqlite3_prepare_v2(
            self._connection, sql.encode("utf-8"), -1, byref(statement), None
        ):
            raise RuntimeError(f"Query failed: {self._error()}\n  {sql}")
        rows: list[tuple[Any, ...]] = []
        try:
            count = self._library.sqlite3_column_count(statement)
            while (status := self._library.sqlite3_step(statement)) == SQLITE_ROW:
                rows.append(tuple(self._value(statement, i) for i in range(count)))
            if status != SQLITE_DONE:
                raise RuntimeError(f"Query failed: {self._error()}\n  {sql}")
            return rows
        finally:
            self._library.sqlite3_finalize(statement)

    def _value(self, statement: c_void_p, index: int) -> Any:
        kind = self._library.sqlite3_column_type(statement, index)
        if kind == SQLITE_NULL:
            return None
        if kind == SQLITE_INTEGER:
            return self._library.sqlite3_column_int64(statement, index)
        if kind == SQLITE_FLOAT:
            return self._library.sqlite3_column_double(statement, index)
        pointer = self._library.sqlite3_column_blob(statement, index)
        length = self._library.sqlite3_column_bytes(statement, index)
        raw = ctypes.string_at(pointer, length) if pointer and length else b""
        return raw.decode("utf-8", "replace") if kind == SQLITE_TEXT else raw

    def close(self) -> None:
        if self._connection.value:
            self._library.sqlite3_close(self._connection)
            self._connection = c_void_p()


def open_source(
    path: Path, key: str | None, dll_directory: Path | None, scratch: Path
) -> tuple[Query, Callable[[], None]]:
    """Open a dump or an encrypted save read-only and return (query, close)."""
    if path.suffix.lower() == ".sql":
        connection = sqlite3.connect(":memory:")
        connection.executescript(path.read_text(encoding="utf-8-sig"))
        return (lambda sql: connection.execute(sql).fetchall()), connection.close
    if not key or not dll_directory:
        raise SystemExit(
            f"{path.name} is an encrypted save: pass --steam-id or --key together with --dll-dir."
        )
    scratch.mkdir(parents=True, exist_ok=True)
    copy = scratch / path.name
    shutil.copy2(path, copy)
    reader = SqlCipherReader(copy, key, dll_directory)
    return reader.query, reader.close


# --------------------------------------------------------------------------
# Inspection
# --------------------------------------------------------------------------
def _scalar(query: Query, sql: str) -> Any:
    rows = query(sql)
    return rows[0][0] if rows else None


def _columns(query: Query, table: str) -> list[str]:
    return [row[1] for row in query(f"PRAGMA table_info('{table}')")]


def inspect(query: Query, *, full_ddl: bool = False) -> dict[str, Any]:
    report: dict[str, Any] = {}

    master = query("SELECT type,name,sql FROM sqlite_master ORDER BY type,name")
    tables = [name for kind, name, _ in master if kind == "table"]
    report["schema"] = {
        "tables": len(tables),
        "indexes": sum(1 for kind, _, _ in master if kind == "index"),
        "triggers": sum(1 for kind, _, _ in master if kind == "trigger"),
        "views": sum(1 for kind, _, _ in master if kind == "view"),
    }
    if full_ddl:
        report["ddl"] = {name: sql for kind, name, sql in master if kind == "table"}

    # ---- account/profile scope -------------------------------------------
    scoped_tables = [t for t in tables if ACCOUNT_COLUMN in _columns(query, t)]
    account_values: dict[str, list[Any]] = {}
    for table in scoped_tables:
        values = [r[0] for r in query(f"SELECT DISTINCT {ACCOUNT_COLUMN} FROM '{table}'")]
        if values:
            account_values[table] = sorted(values, key=lambda v: (v is None, v))
    all_accounts = sorted({v for values in account_values.values() for v in values})
    report["account_scope"] = {
        "column": ACCOUNT_COLUMN,
        "tables_carrying_column": len(scoped_tables),
        "tables_with_rows": len(account_values),
        "distinct_values_across_save": all_accounts,
        "per_table_distinct_values": account_values,
    }

    # ---- discriminator distributions -------------------------------------
    report["discriminators"] = {
        f"{LEVELS_TABLE}.{RECORD_TYPE_COLUMN}": query(
            f"SELECT {RECORD_TYPE_COLUMN},count(*) FROM {LEVELS_TABLE} GROUP BY 1 ORDER BY 1"
        ),
        f"{LEVELS_TABLE}.{CATALOG_ID_COLUMN}_range_per_record_type": query(
            f"SELECT {RECORD_TYPE_COLUMN},min({CATALOG_ID_COLUMN}),max({CATALOG_ID_COLUMN}),"
            f"count(DISTINCT {CATALOG_ID_COLUMN}),count(*) "
            f"FROM {LEVELS_TABLE} GROUP BY 1 ORDER BY 1"
        ),
        f"{STATS_TABLE}.{PRESET_SLOT_COLUMN}": query(
            f"SELECT {PRESET_SLOT_COLUMN},count(*) FROM {STATS_TABLE} GROUP BY 1 ORDER BY 1"
        ),
        f"{STATS_TABLE}.{ACTIVE_PRESET_COLUMN}": query(
            f"SELECT {ACTIVE_PRESET_COLUMN},count(*) FROM {STATS_TABLE} GROUP BY 1 ORDER BY 1"
        ),
    }

    # ---- dynamic discovery ------------------------------------------------
    discovery: dict[str, Any] = {}
    accounts = query(f"SELECT {ACCOUNT_COLUMN},count(*) FROM {LEVELS_TABLE} GROUP BY 1 ORDER BY 1")
    discovery["accounts_in_levels_table"] = accounts
    if len(accounts) != 1:
        discovery["status"] = (
            "AMBIGUOUS: expected exactly one account/profile in a local save, "
            f"found {len(accounts)}"
        )
    else:
        account = accounts[0][0]
        discovery["account_id"] = account
        main = query(
            f"SELECT {CHARACTER_ID_COLUMN},{CATALOG_ID_COLUMN},{LEVEL_COLUMN} "
            f"FROM {LEVELS_TABLE} "
            f"WHERE {ACCOUNT_COLUMN}={account} AND {RECORD_TYPE_COLUMN}=0"
        )
        discovery["main_player_rows"] = main
        if len(main) != 1:
            discovery["status"] = (
                f"AMBIGUOUS: expected exactly one main-character row "
                f"({RECORD_TYPE_COLUMN}=0), found {len(main)}"
            )
        else:
            character_id = main[0][0]
            discovery["main_character_id"] = character_id
            active = query(
                f"SELECT {STATS_ROW_ID_COLUMN},{PRESET_SLOT_COLUMN} FROM {STATS_TABLE} "
                f"WHERE {ACCOUNT_COLUMN}={account} AND {CHARACTER_ID_COLUMN}={character_id} "
                f"AND {ACTIVE_PRESET_COLUMN}=1"
            )
            discovery["active_stat_blocks"] = active
            discovery["active_preset_slot"] = active[0][1] if len(active) == 1 else None
            if len(active) != 1:
                discovery["status"] = (
                    f"AMBIGUOUS: expected exactly one active stat preset "
                    f"({ACTIVE_PRESET_COLUMN}=1), found {len(active)}"
                )
            else:
                discovery["status"] = "OK"
                discovery["player_view"] = query(
                    f"SELECT r.{LEVEL_COLUMN},p.c_c982c144a0,p.c_7e92e023a5+1,"
                    "p.c_1c77e26632+1,p.c_b91b1c4561+1,p.c_3cd914b873+1,p.c_795582f14f+1 "
                    f"FROM {LEVELS_TABLE} r JOIN {STATS_TABLE} p "
                    f"ON p.{CHARACTER_ID_COLUMN}=r.{CHARACTER_ID_COLUMN} "
                    f"AND p.{ACCOUNT_COLUMN}=r.{ACCOUNT_COLUMN} "
                    f"WHERE r.{ACCOUNT_COLUMN}={account} AND r.{RECORD_TYPE_COLUMN}=0 "
                    f"AND p.{ACTIVE_PRESET_COLUMN}=1"
                )
                discovery["roster_rows_per_record_type"] = query(
                    f"SELECT {RECORD_TYPE_COLUMN},count(*) FROM {LEVELS_TABLE} "
                    f"WHERE {ACCOUNT_COLUMN}={account} AND {RECORD_TYPE_COLUMN}<>0 "
                    "GROUP BY 1 ORDER BY 1"
                )
                discovery["legacy_literal_snapshot_query_rows"] = _scalar(
                    query,
                    f"SELECT count(*) FROM {LEVELS_TABLE} r JOIN {STATS_TABLE} p "
                    f"ON p.{CHARACTER_ID_COLUMN}=r.{CHARACTER_ID_COLUMN} "
                    f"WHERE r.{ACCOUNT_COLUMN}=1 AND r.{RECORD_TYPE_COLUMN}=0 "
                    f"AND r.{CATALOG_ID_COLUMN}=1 AND p.{ACCOUNT_COLUMN}=1 "
                    f"AND p.{PRESET_SLOT_COLUMN}=0 AND p.{ACTIVE_PRESET_COLUMN}=1",
                )
    report["dynamic_discovery"] = discovery

    # ---- row counts -------------------------------------------------------
    report["key_table_row_counts"] = {
        table: {
            "meaning": meaning,
            "rows": _scalar(query, f"SELECT count(*) FROM '{table}'") if table in tables else None,
        }
        for table, meaning in KEY_TABLES.items()
    }
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="+", type=Path, help="Save .db and/or dump .sql files.")
    parser.add_argument("--steam-id", help="17-digit SteamID64 used to derive the SQLCipher key.")
    parser.add_argument("--key", help="Pre-derived base64 SQLCipher key (overrides --steam-id).")
    parser.add_argument(
        "--dll-dir",
        type=Path,
        help="Directory containing the game's sqlcipher.dll (needed for encrypted saves).",
    )
    parser.add_argument(
        "--scratch",
        type=Path,
        help="Directory for disposable copies of encrypted saves (default: a temp directory).",
    )
    parser.add_argument("--full-ddl", action="store_true", help="Include full CREATE TABLE DDL.")
    parser.add_argument("--json", type=Path, help="Write the machine-readable report here.")
    parser.add_argument(
        "--all-row-counts", action="store_true", help="Report row counts for every table."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    key = arguments.key
    if not key and arguments.steam_id:
        key = derive_save_key(arguments.steam_id)

    scratch_context: tempfile.TemporaryDirectory[str] | None = None
    if arguments.scratch:
        scratch = arguments.scratch
    else:
        scratch_context = tempfile.TemporaryDirectory(prefix="inspect_saves_")
        scratch = Path(scratch_context.name)

    reports: dict[str, Any] = {}
    try:
        for path in arguments.paths:
            if not path.is_file():
                print(f"!! not a file: {path}", file=sys.stderr)
                continue
            query, close = open_source(path, key, arguments.dll_dir, scratch)
            try:
                report = inspect(query, full_ddl=arguments.full_ddl)
                if arguments.all_row_counts:
                    report["all_row_counts"] = {
                        name: _scalar(query, f"SELECT count(*) FROM '{name}'")
                        for (kind, name, _) in query(
                            "SELECT type,name,sql FROM sqlite_master WHERE type='table' "
                            "ORDER BY name"
                        )
                        if kind == "table"
                    }
            finally:
                close()
            reports[path.name] = report
            print(f"===== {path.name} =====")
            print(json.dumps(report, indent=2, default=str))
            print()
    finally:
        if scratch_context:
            scratch_context.cleanup()

    if arguments.json:
        arguments.json.parent.mkdir(parents=True, exist_ok=True)
        arguments.json.write_text(json.dumps(reports, indent=2, default=str), encoding="utf-8")
        print(f"wrote {arguments.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
