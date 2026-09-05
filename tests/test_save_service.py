"""Regression tests for dynamic account/player discovery and name mapping.

These tests exercise :mod:`savegame_editor.services.save_service` against a
plain in-memory SQLite connection (wrapped to satisfy the small ``query``/
``execute`` protocol the service expects from ``SqlCipherDatabase``) so they
run without the game's SQLCipher DLL. The obfuscated table/column names and
SQL text produced by the service are ordinary SQLite, so this is a faithful
substitute for the encrypted database at the SQL level.

Two of the fixtures reproduce the exact structural shape (dynamic account
id, and an "active" stats row that is *not* at slot 0) found in the
already-decrypted real save dumps in
``OldDevelopingFiles/Dumped/LocalSave_AllUnlocked.db.sql`` -- the fixture
that reproduced "The verified player rows were not found for account ID 1."
before this fix. Original saves and dumps are never opened or modified by
these tests.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from savegame_editor.config.models import EditorSettings
from savegame_editor.core.encryption import SaveEditorError
from savegame_editor.core.entity_overrides import EntityOverrideStore, MappingKey
from savegame_editor.core.naming import NameResolver
from savegame_editor.services import save_service as save_service_module
from savegame_editor.services.save_service import MappingRef, SaveService

SCHEMA = """
CREATE TABLE tb_13c52bbaa8 (
    c_d4f6740b9b INTEGER, c_3536de9619 INTEGER, c_d79538c3b8 INTEGER,
    c_9398111a4b INTEGER, c_e3aa3bf474 INTEGER, c_8ef3c1757a INTEGER
);
CREATE TABLE tb_957a223c9b (
    c_fc7ba2e8c9 INTEGER, c_3536de9619 INTEGER, c_d4f6740b9b INTEGER,
    c_1692f32794 INTEGER, c_bc37480bfc INTEGER, c_c982c144a0 INTEGER,
    c_7e92e023a5 INTEGER, c_1c77e26632 INTEGER, c_b91b1c4561 INTEGER,
    c_3cd914b873 INTEGER, c_795582f14f INTEGER
);
CREATE TABLE tb_e973c32e29 (
    c_3536de9619 INTEGER, c_d1f333420b INTEGER, c_418025e253 INTEGER,
    c_ac7e41767f INTEGER, c_a9d19edb77 INTEGER
);
CREATE TABLE tb_d40f87183c (
    c_20bfd7b86b INTEGER, c_3536de9619 INTEGER, c_4ec2cde1a1 INTEGER,
    c_29b96fe9bd INTEGER, c_8eb30bb564 INTEGER
);
CREATE TABLE tb_adfb9b0bf5 (c_3536de9619 INTEGER, c_20bfd7b86b INTEGER, c_4ec2cde1a1 INTEGER);
CREATE TABLE tb_16b100425f (c_3536de9619 INTEGER, c_1535b8b416 INTEGER, c_9e0be258cc INTEGER);
CREATE TABLE tb_bc88081733 (c_3536de9619 INTEGER, c_9940549f1a INTEGER, c_f24809310e INTEGER);
CREATE TABLE tb_ab102d50ba (c_3536de9619 INTEGER, c_20bfd7b86b INTEGER, c_4ec2cde1a1 INTEGER);
CREATE TABLE tb_4b5c76b06a (
    c_3536de9619 INTEGER, c_7b24ba5e87 INTEGER, c_b266e40b3c INTEGER, c_eff552fd8d INTEGER
);
CREATE TABLE tb_cc2254ea5d (
    c_3536de9619 INTEGER, c_4ec2cde1a1 INTEGER, c_f80b15c453 INTEGER, c_ea247d8f96 INTEGER
);
CREATE TABLE tb_3352b063a3 (
    c_3536de9619 INTEGER, c_0cc7c09467 INTEGER, c_6dc52e9c30 INTEGER, c_e3bc20d6ba INTEGER
);
CREATE TABLE tb_bf41c3a26c (c_3536de9619 INTEGER, c_8401e00524 INTEGER);
"""


class SqliteBackedDatabase:
    """Adapt a plain ``sqlite3.Connection`` to the service's tiny DB protocol."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        connection.isolation_level = None  # let literal BEGIN/COMMIT/ROLLBACK pass through

    def query(self, sql: str) -> list[tuple[object, ...]]:
        return self._connection.execute(sql).fetchall()

    def execute(self, sql: str) -> None:
        try:
            self._connection.execute(sql)
        except sqlite3.Error as error:
            raise SaveEditorError(str(error)) from error

    def close(self) -> None:
        self._connection.close()


def _make_service(overrides_path: Path) -> tuple[SaveService, sqlite3.Connection]:
    service = SaveService(Path("unused-parser.pyc"), EntityOverrideStore(overrides_path))
    connection = sqlite3.connect(":memory:")
    connection.executescript(SCHEMA)
    return service, connection


def _attach(service: SaveService, connection: sqlite3.Connection, account_id: int) -> None:
    """Discover the account id through the real code path and attach the DB."""
    database = SqliteBackedDatabase(connection)
    service._database = database  # noqa: SLF001 - direct attach avoids needing the SQLCipher DLL
    service._account_id = service._discover_account_id(database)  # noqa: SLF001
    assert service._account_id == account_id  # noqa: SLF001


def test_dynamic_discovery_supports_non_1_account_id(tmp_path: Path) -> None:
    service, connection = _make_service(tmp_path / "overrides.json")
    account_id = 42
    connection.execute(
        "INSERT INTO tb_13c52bbaa8 VALUES (100, ?, 0, 1, 10, 0)", (account_id,)
    )
    connection.execute(
        "INSERT INTO tb_957a223c9b VALUES (200, ?, 100, 0, 1, 5, 9, 9, 9, 9, 9)", (account_id,)
    )
    connection.execute("INSERT INTO tb_e973c32e29 VALUES (?, 999, 1, 2, 3)", (account_id,))

    _attach(service, connection, account_id)
    table = service.read_view("player")

    values_by_field = {row.values[0]: row.values[1] for row in table.rows}
    assert values_by_field["Gold"] == 999
    assert values_by_field["Main character level"] == 10


def test_progressed_save_active_stats_slot_not_zero_still_loads(tmp_path: Path) -> None:
    """Regression test for 'The verified player rows were not found for account ID 1.'

    Reproduces the exact structural shape observed in the decrypted
    LocalSave_AllUnlocked.db.sql dump: the active stats row
    (c_bc37480bfc=1) is NOT the row at slot index 0. The old query hard
    coded ``c_1692f32794=0 AND c_bc37480bfc=1``, which cannot match this
    save and raised the "verified player rows" error.
    """
    service, connection = _make_service(tmp_path / "overrides.json")
    connection.execute("INSERT INTO tb_13c52bbaa8 VALUES (100, 1, 0, 1, 56, 0)")
    # Five stat-block slots, mirroring the real dump: slot 0 is NOT active;
    # slot 1 is the active block.
    connection.execute("INSERT INTO tb_957a223c9b VALUES (1, 1, 100, 0, 0, 0, 0, 0, 0, 0, 0)")
    connection.execute("INSERT INTO tb_957a223c9b VALUES (2, 1, 100, 1, 1, 58, 143, 17, 59, 45, 47)")
    connection.execute("INSERT INTO tb_e973c32e29 VALUES (1, 10054, 69, 57, 10010)")

    _attach(service, connection, 1)
    table = service.read_view("player")

    values_by_field = {row.values[0]: row.values[1] for row in table.rows}
    assert values_by_field["Unspent stat points"] == 58
    assert values_by_field["Strength"] == 144  # stored 143, displayed +1


def test_no_main_player_row_raises_clear_diagnostic(tmp_path: Path) -> None:
    service, connection = _make_service(tmp_path / "overrides.json")
    connection.execute("INSERT INTO tb_13c52bbaa8 VALUES (100, 1, 1, 81, 5, 0)")  # only a hunter row

    database = SqliteBackedDatabase(connection)
    with pytest.raises(SaveEditorError, match="No main player row"):
        service._discover_account_id(database)  # noqa: SLF001


def test_ambiguous_main_player_rows_raise_clear_diagnostic(tmp_path: Path) -> None:
    service, connection = _make_service(tmp_path / "overrides.json")
    connection.execute("INSERT INTO tb_13c52bbaa8 VALUES (100, 1, 0, 1, 5, 0)")
    connection.execute("INSERT INTO tb_13c52bbaa8 VALUES (101, 1, 0, 1, 5, 0)")

    database = SqliteBackedDatabase(connection)
    with pytest.raises(SaveEditorError, match="ambiguous main player rows"):
        service._discover_account_id(database)  # noqa: SLF001


def test_multiple_distinct_accounts_are_rejected(tmp_path: Path) -> None:
    service, connection = _make_service(tmp_path / "overrides.json")
    connection.execute("INSERT INTO tb_13c52bbaa8 VALUES (100, 1, 0, 1, 5, 0)")
    connection.execute("INSERT INTO tb_13c52bbaa8 VALUES (101, 2, 0, 1, 5, 0)")

    database = SqliteBackedDatabase(connection)
    with pytest.raises(SaveEditorError, match="more than one distinct account"):
        service._discover_account_id(database)  # noqa: SLF001


def test_hunters_view_includes_every_nonzero_record_type_with_fallback_names(
    tmp_path: Path,
) -> None:
    """Regression test for F2: roster record types are not a fixed enumeration.

    The roster read must surface every ``c_d79538c3b8 <> 0`` row -- not just
    type 1 -- because types 2/3/... appear and grow with progression in real
    saves. Only type 1 ("hunter") has a confirmed name catalog; other types
    must degrade to a namespaced fallback rather than being hidden.
    """
    service, connection = _make_service(tmp_path / "overrides.json")
    connection.execute("INSERT INTO tb_13c52bbaa8 VALUES (100, 7, 0, 1, 56, 0)")  # main: excluded
    connection.execute("INSERT INTO tb_13c52bbaa8 VALUES (101, 7, 1, 999999, 12, 0)")  # hunter
    connection.execute("INSERT INTO tb_13c52bbaa8 VALUES (102, 7, 2, 100004, 30, 0)")  # unknown type

    _attach(service, connection, 7)
    table = service.read_view("hunters")

    assert len(table.rows) == 2
    row_id, record_type, unit_id, name, level = table.rows[0].values
    assert (row_id, record_type, unit_id, level) == (101, 1, 999999, 12)
    assert name == "hunter:999999"  # deterministic namespaced fallback, no catalog loaded

    row_id, record_type, unit_id, name, level = table.rows[1].values
    assert (row_id, record_type, unit_id, level) == (102, 2, 100004, 30)
    assert name == "roster_type_2:100004"  # unresolved record type: safe fallback, not hidden


def test_apply_edits_scopes_writes_to_the_discovered_account_id(tmp_path: Path) -> None:
    """Write statements must key off the *discovered* account id, not a literal 1.

    Each local save file holds exactly one profile (multi-account files are
    rejected by ``_discover_account_id``), so this proves the generated SQL
    is parameterized by whatever account id was actually discovered -- here
    a non-1 value -- rather than a hard-coded ``account ID 1`` literal.
    """
    service, connection = _make_service(tmp_path / "overrides.json")
    connection.execute("INSERT INTO tb_13c52bbaa8 VALUES (100, 3, 0, 1, 10, 0)")
    _attach(service, connection, 3)
    service._catalog.level_curve = {20: 12345}  # noqa: SLF001 - stand in for ChSJWLv.byte

    statement = service._update_statement("main_level", 20, None)  # noqa: SLF001
    assert "c_3536de9619=3" in statement
    assert "c_3536de9619=1" not in statement
    connection.execute(statement)

    level, total_xp = connection.execute(
        "SELECT c_e3aa3bf474,c_8ef3c1757a FROM tb_13c52bbaa8 WHERE c_d4f6740b9b=100"
    ).fetchone()
    assert level == 20
    assert total_xp == 12345  # F3 regression: XP is kept in lockstep with level


def test_main_level_write_refuses_without_a_verified_level_curve(tmp_path: Path) -> None:
    """Regression test for F3: never write a level without its paired XP.

    Writing level alone (leaving total XP stale) produces a save state the
    game itself never creates. If the level curve can't be read, the editor
    must refuse the write instead of silently leaving XP inconsistent.
    """
    from savegame_editor.services.save_service import SaveRow

    service, connection = _make_service(tmp_path / "overrides.json")
    connection.execute("INSERT INTO tb_13c52bbaa8 VALUES (100, 1, 0, 1, 10, 0)")
    _attach(service, connection, 1)  # service._catalog.level_curve is empty by default

    with pytest.raises(SaveEditorError, match="level curve"):
        service._update_statement("main_level", 20, None)  # noqa: SLF001

    main_level_row = SaveRow(("Main character level", 10, "tb_13c52bbaa8.c_e3aa3bf474", "1 to 75"), "main_level")
    with pytest.raises(SaveEditorError, match="level curve"):
        service.apply_edits([(main_level_row, 20)])


def test_owned_items_are_namespace_scoped_and_collision_safe(tmp_path: Path) -> None:
    service, connection = _make_service(tmp_path / "overrides.json")
    connection.execute("INSERT INTO tb_13c52bbaa8 VALUES (100, 1, 0, 1, 10, 0)")
    connection.execute("INSERT INTO tb_adfb9b0bf5 VALUES (1, 500, 7)")
    connection.execute("INSERT INTO tb_16b100425f VALUES (1, 501, 7)")  # same raw catalog id: 7
    _attach(service, connection, 1)

    overrides = EntityOverrideStore(tmp_path / "overrides.json")
    overrides.set(MappingKey("owned_artifact", 7), "Artifact Seven")
    service._names = NameResolver(service._catalog, overrides)  # noqa: SLF001

    table = service.read_view("owned")
    names = {row.values[0]: row.values[3] for row in table.rows}
    assert names["Artifact"] == "Artifact Seven"
    assert names["Relic weapon"] == "owned_relic_weapon:7"  # unaffected by the artifact override


def test_failed_open_does_not_disturb_a_previously_open_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test: SaveService.open() must be all-or-nothing.

    Opening save A succeeds; a subsequent attempt to open a broken save B
    must fail loudly without closing save A's connection or clearing any of
    the already-published state (``save_path``/``database``/``account_id``).
    This is the transactional-``open()`` fix: a candidate is only committed
    after every validation step succeeds.
    """
    good_connection = sqlite3.connect(":memory:")
    good_connection.executescript(SCHEMA)
    good_connection.execute("INSERT INTO tb_13c52bbaa8 VALUES (100, 1, 0, 1, 10, 0)")
    good_database = SqliteBackedDatabase(good_connection)
    good_database.closed = False
    real_close = good_database.close
    good_database.close = lambda: (setattr(good_database, "closed", True), real_close())  # type: ignore[method-assign]

    bad_connection = sqlite3.connect(":memory:")
    bad_connection.executescript(SCHEMA)  # no rows at all: fails account-scope discovery
    bad_database = SqliteBackedDatabase(bad_connection)

    databases_by_path = {
        Path("good.db"): good_database,
        Path("bad.db"): bad_database,
    }

    def fake_constructor(path: Path, key: str, dll_directory: Path) -> SqliteBackedDatabase:
        return databases_by_path[path]

    monkeypatch.setattr(save_service_module, "SqlCipherDatabase", fake_constructor)
    monkeypatch.setattr(save_service_module, "derive_save_key", lambda steam_id: "unused-key")

    service = SaveService(Path("unused-parser.pyc"), EntityOverrideStore(tmp_path / "overrides.json"))
    good_settings = EditorSettings(
        default_game_data_path=tmp_path, steam_id="1", encrypted_db_path=Path("good.db")
    )
    warning = service.open(good_settings)
    assert warning is not None  # catalog load fails against an empty tmp_path: non-fatal
    assert service.save_path == Path("good.db")
    published_database = service._database  # noqa: SLF001

    bad_settings = EditorSettings(
        default_game_data_path=tmp_path, steam_id="1", encrypted_db_path=Path("bad.db")
    )
    with pytest.raises(SaveEditorError, match="no account/profile scope"):
        service.open(bad_settings)

    # The previously published state must be completely untouched.
    assert service.save_path == Path("good.db")
    assert service._database is published_database  # noqa: SLF001
    assert not good_database.closed
    assert service.read_view("hunters").rows == []  # still fully functional


class TestEntityOverrideStore:
    def test_set_get_persist_and_restart(self, tmp_path: Path) -> None:
        path = tmp_path / "overrides.json"
        key = MappingKey("hunter", 51)
        EntityOverrideStore(path).set(key, "  Custom Hunter Name  ")

        reloaded = EntityOverrideStore(path)
        assert reloaded.get(key) == "Custom Hunter Name"

    def test_empty_override_restores_automatic_resolution(self, tmp_path: Path) -> None:
        path = tmp_path / "overrides.json"
        key = MappingKey("hunter", 51)
        store = EntityOverrideStore(path)
        store.set(key, "Custom Name")
        assert store.get(key) == "Custom Name"

        store.set(key, "")  # clearing restores automatic resolution
        assert store.get(key) is None

    def test_namespace_collision_safety(self, tmp_path: Path) -> None:
        path = tmp_path / "overrides.json"
        store = EntityOverrideStore(path)
        store.set(MappingKey("hunter", 51), "Hunter Fifty-One")
        store.set(MappingKey("item", 51), "Item Fifty-One")

        assert store.get(MappingKey("hunter", 51)) == "Hunter Fifty-One"
        assert store.get(MappingKey("item", 51)) == "Item Fifty-One"

    def test_context_disambiguates_identical_namespace_and_raw_id(self, tmp_path: Path) -> None:
        path = tmp_path / "overrides.json"
        store = EntityOverrideStore(path)
        store.set(MappingKey("inventory_category", 3, "weapons"), "Weapons")
        store.set(MappingKey("inventory_category", 3, "armor"), "Armor")

        assert store.get(MappingKey("inventory_category", 3, "weapons")) == "Weapons"
        assert store.get(MappingKey("inventory_category", 3, "armor")) == "Armor"


class TestNameResolver:
    def test_override_outranks_generated_name(self, tmp_path: Path) -> None:
        from savegame_editor.core.catalog import CatalogResolver

        catalog = CatalogResolver(Path("unused.pyc"))
        catalog.names_by_file["ChHunt"] = {51: "Generated Hunter"}
        overrides = EntityOverrideStore(tmp_path / "overrides.json")
        resolver = NameResolver(catalog, overrides)

        assert resolver.resolve("hunter", 51) == "Generated Hunter"
        resolver.set_override("hunter", 51, None, "User Hunter")
        assert resolver.resolve("hunter", 51) == "User Hunter"

    def test_deterministic_fallback_for_unknown_entity(self, tmp_path: Path) -> None:
        from savegame_editor.core.catalog import CatalogResolver

        catalog = CatalogResolver(Path("unused.pyc"))
        overrides = EntityOverrideStore(tmp_path / "overrides.json")
        resolver = NameResolver(catalog, overrides)

        assert resolver.resolve("achievement", 12345) == "achievement:12345"
