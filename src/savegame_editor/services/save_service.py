"""Save read/write operations, independent from Qt widgets."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from savegame_editor.config.models import EditorSettings
from savegame_editor.core.catalog import CatalogResolver
from savegame_editor.core.database import SqlCipherDatabase
from savegame_editor.core.encryption import SaveEditorError, derive_save_key
from savegame_editor.core.entity_overrides import EntityOverrideStore
from savegame_editor.core.naming import NameResolver
from savegame_editor.core.paths import derive_dll_directory
from savegame_editor.core.validation import validate_edit_value


@dataclass(frozen=True, slots=True)
class MappingRef:
    """A namespace-scoped entity identity backing one editable display-name cell."""

    namespace: str
    raw_id: int
    context: str | None = None


@dataclass(frozen=True, slots=True)
class SaveRow:
    values: tuple[Any, ...]
    action: str | None = None
    identifier: int | None = None
    # Column index -> the entity identity that column's editable display name maps to.
    mappings: tuple[tuple[int, MappingRef], ...] = field(default_factory=tuple)

    def mapping_for_column(self, column: int) -> MappingRef | None:
        for mapped_column, mapping in self.mappings:
            if mapped_column == column:
                return mapping
        return None


@dataclass(frozen=True, slots=True)
class SaveTable:
    columns: list[tuple[str, int]]
    rows: list[SaveRow]


class SaveService:
    """Own the currently open local save and preserve its verified mutation behavior."""

    # Account/profile-scope discriminator (obfuscated column c_3536de9619).
    _ACCOUNT_COLUMN = "c_3536de9619"
    # Row-role discriminator on tb_13c52bbaa8: 0 marks the single main-character
    # row, 1 marks a hunter-roster row. This is a structural flag, not a count.
    _IS_HUNTER_COLUMN = "c_d79538c3b8"
    # "Active" stat-block flag on tb_957a223c9b: exactly one row per character
    # is flagged active regardless of which stat-block slot it occupies, so the
    # slot index (c_1692f32794) must never be compared to a literal snapshot.
    _ACTIVE_STATS_COLUMN = "c_bc37480bfc"

    def __init__(
        self, parser_path: Path, overrides: EntityOverrideStore | None = None
    ) -> None:
        self._parser_path = parser_path
        self._database: SqlCipherDatabase | None = None
        self._save_path: Path | None = None
        self._catalog = CatalogResolver(parser_path)
        self._overrides = overrides or EntityOverrideStore()
        self._names = NameResolver(self._catalog, self._overrides)
        self._account_id: int | None = None

    @property
    def save_path(self) -> Path | None:
        return self._save_path

    def open(self, settings: EditorSettings) -> str | None:
        """Validate and open a candidate save, publishing state only on full success.

        The candidate database, discovered account scope, and catalog are all
        built off to the side. The currently active state is replaced only
        once every validation step has succeeded, so a failed candidate can
        never leave the service in a partially-open state.
        """
        if not settings.encrypted_db_path:
            raise SaveEditorError("Choose an encrypted LocalSave database first.")
        if not settings.steam_id:
            raise SaveEditorError("Enter a SteamID64 or previously derived save key first.")
        if not settings.default_game_data_path:
            raise SaveEditorError("Choose the installed GameData directory in Settings first.")
        key = (
            derive_save_key(settings.steam_id)
            if settings.steam_id.isdecimal()
            else settings.steam_id
        )
        candidate_database = SqlCipherDatabase(
            settings.encrypted_db_path, key, derive_dll_directory(settings.default_game_data_path)
        )
        try:
            candidate_account_id = self._discover_account_id(candidate_database)
        except Exception:
            candidate_database.close()
            raise
        candidate_catalog = CatalogResolver(self._parser_path)
        catalog_warning: str | None = None
        try:
            candidate_catalog.load(settings.default_game_data_path)
        except (OSError, ValueError, KeyError) as error:
            catalog_warning = f"Save opened, but catalog names are unavailable: {error}"

        # All validation succeeded: atomically publish the new active state.
        self.close()
        self._save_path = settings.encrypted_db_path
        self._database = candidate_database
        self._catalog = candidate_catalog
        self._names = NameResolver(self._catalog, self._overrides)
        self._account_id = candidate_account_id
        return catalog_warning

    def close(self) -> None:
        if self._database:
            self._database.close()
            self._database = None
        self._save_path = None
        self._account_id = None

    def _discover_account_id(self, database: SqlCipherDatabase) -> int:
        """Dynamically discover the single local account/profile scope.

        Every supplied save is a single-profile local file: every table's
        account/profile column carries exactly one distinct value. Rather
        than assuming that value is the literal ``1``, discover it and
        validate the invariant explicitly so genuinely inconsistent saves
        fail with a precise diagnostic instead of silently mis-scoping reads
        and writes.
        """
        distinct_accounts = database.query(
            f"SELECT DISTINCT {self._ACCOUNT_COLUMN} FROM tb_13c52bbaa8"
        )
        if not distinct_accounts:
            raise SaveEditorError(
                "This save's character/level table (tb_13c52bbaa8) is empty; "
                "no account/profile scope could be discovered."
            )
        if len(distinct_accounts) > 1:
            raise SaveEditorError(
                "This save contains more than one distinct account/profile ID "
                "in tb_13c52bbaa8; the editor supports exactly one local profile "
                "per save file and cannot resolve this ambiguity safely."
            )
        account_id = distinct_accounts[0][0]
        if not isinstance(account_id, int):
            raise SaveEditorError(
                "The discovered account/profile ID is not an integer; this save's "
                "schema does not match the structure the editor understands."
            )
        main_rows = database.query(
            f"SELECT count(*) FROM tb_13c52bbaa8 "
            f"WHERE {self._ACCOUNT_COLUMN}={account_id} AND {self._IS_HUNTER_COLUMN}=0"
        )
        main_row_count = main_rows[0][0] if main_rows else 0
        if main_row_count == 0:
            raise SaveEditorError(
                f"No main player row was found for account ID {account_id} "
                f"(no row with {self._IS_HUNTER_COLUMN}=0 in tb_13c52bbaa8)."
            )
        if main_row_count > 1:
            raise SaveEditorError(
                f"Found {main_row_count} ambiguous main player rows for account ID "
                f"{account_id}; expected exactly one."
            )
        return account_id

    def set_name_override(self, mapping: MappingRef, value: str) -> str:
        """Persist a user-defined display-name override for one mapped entity.

        This only writes editor-metadata storage; it never touches the
        encrypted save database or any internal identifier.
        """
        return self._names.set_override(mapping.namespace, mapping.raw_id, mapping.context, value)

    def read_view(self, view: str) -> SaveTable:
        database = self._require_database()
        methods = {
            "player": self._player_table,
            "hunters": self._hunters_table,
            "inventory": self._inventory_table,
            "owned": self._owned_table,
            "cosmetics": self._cosmetics_table,
            "titles": self._titles_table,
            "achievements": self._achievements_table,
            "difficulty": self._difficulty_table,
        }
        try:
            return methods[view](database)
        except KeyError as error:
            raise SaveEditorError(f"Unknown editor view: {view}") from error

    def apply_edit(self, row: SaveRow, value: int) -> Path:
        return self.apply_edits([(row, value)])

    def apply_edits(self, edits: list[tuple[SaveRow, int]]) -> Path:
        """Create one backup and atomically apply all staged mapped edits."""
        if not edits:
            raise SaveEditorError("There are no staged changes to save.")
        statements: list[str] = []
        for row, value in edits:
            if not row.action:
                raise SaveEditorError("This row is read-only.")
            validate_edit_value(row.action, value)
            statements.append(self._update_statement(row.action, value, row.identifier))
        return self._backup_and_write(statements)

    def _require_database(self) -> SqlCipherDatabase:
        if not self._database:
            raise SaveEditorError("Open an encrypted save first.")
        return self._database

    def _require_account_id(self) -> int:
        if self._account_id is None:
            raise SaveEditorError("Open an encrypted save first.")
        return self._account_id

    def _required_total_xp(self, level: int) -> int:
        """Look up the verified cumulative XP for ``level``, or refuse to write it.

        Total XP (``c_8ef3c1757a``) must always be kept consistent with level
        (``c_e3aa3bf474``): the game itself never produces a save where level
        is higher than the XP it was earned with. The legacy editor refused
        to write a level it could not pair with a verified curve value; this
        mirrors that behavior instead of silently leaving XP stale.
        """
        curve = self._catalog.level_curve
        if not curve:
            raise SaveEditorError(
                "Could not read the level curve (GameData/ChSJWLv.byte); "
                "refusing to set the level, as it would break in-game XP."
            )
        if level not in curve:
            raise SaveEditorError(
                f"Level {level} has no entry in the level curve; refusing to set it."
            )
        return curve[level]

    def _player_table(self, database: SqlCipherDatabase) -> SaveTable:
        account_id = self._require_account_id()
        main = database.query(
            "SELECT r.c_e3aa3bf474,p.c_c982c144a0,p.c_7e92e023a5+1,p.c_1c77e26632+1,"
            "p.c_b91b1c4561+1,p.c_3cd914b873+1,p.c_795582f14f+1 "
            "FROM tb_13c52bbaa8 r JOIN tb_957a223c9b p ON p.c_d4f6740b9b=r.c_d4f6740b9b "
            f"WHERE r.{self._ACCOUNT_COLUMN}={account_id} AND r.{self._IS_HUNTER_COLUMN}=0 "
            f"AND p.{self._ACCOUNT_COLUMN}={account_id} AND p.{self._ACTIVE_STATS_COLUMN}=1"
        )
        wallet = database.query(
            "SELECT c_d1f333420b,c_418025e253,c_ac7e41767f,c_a9d19edb77 "
            f"FROM tb_e973c32e29 WHERE {self._ACCOUNT_COLUMN}={account_id}"
        )
        if len(main) > 1:
            raise SaveEditorError(
                f"Found {len(main)} ambiguous active player/stats rows for account ID "
                f"{account_id}; expected exactly one."
            )
        if not main or not wallet:
            raise SaveEditorError(
                f"The verified player rows were not found for account ID {account_id}."
            )
        level, points, strength, vitality, agility, intelligence, perception = main[0]
        gold, player_scrolls, weapon_scrolls, special_scrolls = wallet[0]
        return SaveTable(
            [("Field", 250), ("Current value", 150), ("Storage", 320), ("Rule", 180)],
            [
                SaveRow(("Gold", gold, "tb_e973c32e29.c_d1f333420b", "Verified"), "gold"),
                SaveRow(
                    (
                        "Player skill scrolls",
                        player_scrolls,
                        "tb_e973c32e29.c_418025e253",
                        "Verified",
                    ),
                    "player_scrolls",
                ),
                SaveRow(
                    (
                        "Weapon skill scrolls",
                        weapon_scrolls,
                        "tb_e973c32e29.c_ac7e41767f",
                        "Verified",
                    ),
                    "weapon_scrolls",
                ),
                SaveRow(
                    (
                        "Special skill scrolls",
                        special_scrolls,
                        "tb_e973c32e29.c_a9d19edb77",
                        "Verified",
                    ),
                    "special_scrolls",
                ),
                SaveRow(
                    ("Main character level", level, "tb_13c52bbaa8.c_e3aa3bf474", "1 to 75"),
                    "main_level",
                ),
                SaveRow(
                    ("Unspent stat points", points, "tb_957a223c9b.c_c982c144a0", "Direct value"),
                    "points",
                ),
                SaveRow(
                    ("Strength", strength, "tb_957a223c9b.c_7e92e023a5", "Display value"),
                    "strength",
                ),
                SaveRow(
                    ("Vitality", vitality, "tb_957a223c9b.c_1c77e26632", "Display value"),
                    "vitality",
                ),
                SaveRow(
                    ("Agility", agility, "tb_957a223c9b.c_b91b1c4561", "Display value"), "agility"
                ),
                SaveRow(
                    ("Intelligence", intelligence, "tb_957a223c9b.c_3cd914b873", "Display value"),
                    "intelligence",
                ),
                SaveRow(
                    ("Perception", perception, "tb_957a223c9b.c_795582f14f", "Display value"),
                    "perception",
                ),
            ],
        )

    def _hunters_table(self, database: SqlCipherDatabase) -> SaveTable:
        account_id = self._require_account_id()
        # Every roster record type other than 0 (main character) belongs here.
        # The domain is {1,2,3,...} and grows with progression; only type 1
        # ("hunter") has a confirmed catalog/name mapping, so other types are
        # labelled by their raw record type and degrade to a namespaced
        # fallback name rather than being hidden or mislabelled.
        rows = database.query(
            "SELECT c_d4f6740b9b,c_d79538c3b8,c_9398111a4b,c_e3aa3bf474 FROM tb_13c52bbaa8 "
            f"WHERE {self._ACCOUNT_COLUMN}={account_id} AND {self._IS_HUNTER_COLUMN}<>0 "
            "ORDER BY c_d79538c3b8,c_9398111a4b"
        )
        return SaveTable(
            [
                ("Roster row ID", 220),
                ("Record type", 110),
                ("Unit ID", 130),
                ("Unit", 280),
                ("Level", 100),
            ],
            [
                SaveRow(
                    (
                        row_id,
                        record_type,
                        unit_id,
                        self._names.resolve(
                            "hunter" if record_type == 1 else f"roster_type_{record_type}",
                            unit_id,
                        ),
                        level,
                    ),
                    "hunter_level",
                    row_id,
                    (
                        (
                            3,
                            MappingRef(
                                "hunter" if record_type == 1 else f"roster_type_{record_type}",
                                unit_id,
                            ),
                        ),
                    ),
                )
                for row_id, record_type, unit_id, level in rows
            ],
        )

    def _inventory_table(self, database: SqlCipherDatabase) -> SaveTable:
        account_id = self._require_account_id()
        rows = database.query(
            "SELECT c_20bfd7b86b,c_4ec2cde1a1,c_29b96fe9bd,c_8eb30bb564 FROM tb_d40f87183c "
            f"WHERE {self._ACCOUNT_COLUMN}={account_id} ORDER BY c_4ec2cde1a1"
        )
        return SaveTable(
            [
                ("Inventory row ID", 220),
                ("Item ID", 120),
                ("Item", 360),
                ("Category", 100),
                ("Category Name", 200),
                ("Count", 110),
            ],
            [
                SaveRow(
                    (
                        row_id,
                        item_id,
                        self._names.resolve("item", item_id),
                        category,
                        self._names.resolve("inventory_category", category),
                        count,
                    ),
                    "inventory_count",
                    row_id,
                    (
                        (2, MappingRef("item", item_id)),
                        (4, MappingRef("inventory_category", category)),
                    ),
                )
                for row_id, item_id, category, count in rows
            ],
        )

    def _owned_table(self, database: SqlCipherDatabase) -> SaveTable:
        account_id = self._require_account_id()
        groups = (
            ("Artifact", "tb_adfb9b0bf5", "c_20bfd7b86b", "c_4ec2cde1a1", "owned_artifact"),
            ("Relic weapon", "tb_16b100425f", "c_1535b8b416", "c_9e0be258cc", "owned_relic_weapon"),
            ("Hunter weapon", "tb_bc88081733", "c_9940549f1a", "c_f24809310e", "owned_hunter_weapon"),
            ("Blessing stone", "tb_ab102d50ba", "c_20bfd7b86b", "c_4ec2cde1a1", "owned_blessing_stone"),
        )
        result: list[SaveRow] = []
        for kind, table, instance, catalog, namespace in groups:
            try:
                for item_id, catalog_id in database.query(
                    f"SELECT {instance},{catalog} FROM {table} "
                    f"WHERE {self._ACCOUNT_COLUMN}={account_id}"
                ):
                    result.append(
                        SaveRow(
                            (kind, item_id, catalog_id, self._names.resolve(namespace, catalog_id)),
                            None,
                            None,
                            ((3, MappingRef(namespace, catalog_id)),),
                        )
                    )
            except SaveEditorError:
                continue
        return SaveTable(
            [("Type", 160), ("Instance ID", 220), ("Catalog ID", 140), ("Resolved Name", 420)],
            result,
        )

    def _cosmetics_table(self, database: SqlCipherDatabase) -> SaveTable:
        account_id = self._require_account_id()
        rows = database.query(
            "SELECT c_7b24ba5e87,c_b266e40b3c,c_eff552fd8d FROM tb_4b5c76b06a "
            f"WHERE {self._ACCOUNT_COLUMN}={account_id} ORDER BY c_b266e40b3c,c_7b24ba5e87"
        )
        return SaveTable(
            [
                ("Catalog ID", 150),
                ("Resolved Name", 420),
                ("Category", 150),
                ("Category Name", 200),
                ("Unlocked", 120),
            ],
            [
                SaveRow(
                    (
                        item_id,
                        self._names.resolve("cosmetic", item_id),
                        category,
                        self._names.resolve("cosmetic_category", category),
                        unlocked,
                    ),
                    None,
                    None,
                    (
                        (1, MappingRef("cosmetic", item_id)),
                        (3, MappingRef("cosmetic_category", category)),
                    ),
                )
                for item_id, category, unlocked in rows
            ],
        )

    def _titles_table(self, database: SqlCipherDatabase) -> SaveTable:
        account_id = self._require_account_id()
        rows = database.query(
            "SELECT c_4ec2cde1a1,c_f80b15c453,c_ea247d8f96 FROM tb_cc2254ea5d "
            f"WHERE {self._ACCOUNT_COLUMN}={account_id} ORDER BY c_4ec2cde1a1"
        )
        return SaveTable(
            [
                ("Title ID", 150),
                ("Resolved Title", 420),
                ("Unlock flag", 130),
                ("Expiry timestamp", 220),
            ],
            [
                SaveRow(
                    (title_id, self._names.resolve("title", title_id), flag, expiry),
                    None,
                    None,
                    ((1, MappingRef("title", title_id)),),
                )
                for title_id, flag, expiry in rows
            ],
        )

    def _achievements_table(self, database: SqlCipherDatabase) -> SaveTable:
        account_id = self._require_account_id()
        rows = database.query(
            "SELECT c_0cc7c09467,c_6dc52e9c30,c_e3bc20d6ba FROM tb_3352b063a3 "
            f"WHERE {self._ACCOUNT_COLUMN}={account_id} ORDER BY c_0cc7c09467"
        )
        return SaveTable(
            [("Achievement ID", 160), ("Resolved Name", 420), ("Progress", 130), ("State", 130)],
            [
                SaveRow(
                    (achievement_id, self._names.resolve("achievement", achievement_id), progress, state),
                    None,
                    None,
                    ((1, MappingRef("achievement", achievement_id)),),
                )
                for achievement_id, progress, state in rows
            ],
        )

    def _difficulty_table(self, database: SqlCipherDatabase) -> SaveTable:
        account_id = self._require_account_id()
        rows = database.query(
            f"SELECT c_8401e00524 FROM tb_bf41c3a26c WHERE {self._ACCOUNT_COLUMN}={account_id}"
        )
        value = rows[0][0] if rows else None
        labels = {2: "Normal", 3: "Hard", 4: "Incapable of Evaluation (New Game+)"}
        label = (
            labels.get(value, "Unrecognized value")
            if isinstance(value, int)
            else "Unrecognized value"
        )
        return SaveTable(
            [("Setting", 280), ("Current value", 180), ("Meaning", 420)],
            [SaveRow(("Story difficulty", value, label, "difficulty"))],
        )

    def _backup_and_write(self, statements: list[str]) -> Path:
        database = self._require_database()
        if not self._save_path:
            raise SaveEditorError("No save path is available for backup.")
        backup = (
            self._save_path.parent
            / "SaveEditorBackups"
            / f"{self._save_path.stem}_{time.strftime('%Y%m%d-%H%M%S')}"
        )
        try:
            backup.mkdir(parents=True, exist_ok=False)
            files = [
                path
                for path in self._save_path.parent.glob(f"{self._save_path.name}*")
                if path.is_file()
            ]
            if self._save_path not in files:
                files.append(self._save_path)
            for source in files:
                shutil.copy2(source, backup / source.name)
        except OSError as error:
            raise SaveEditorError(f"Could not create the full save backup: {error}") from error
        try:
            database.execute("BEGIN IMMEDIATE")
            for statement in statements:
                database.execute(statement)
            database.execute("COMMIT")
        except Exception:
            try:
                database.execute("ROLLBACK")
            except SaveEditorError:
                pass
            raise
        return backup

    def _update_statement(self, action: str, value: int, identifier: int | None) -> str:
        account_id = self._require_account_id()
        if action == "main_level":
            # Total XP must move in lockstep with level (see _required_total_xp);
            # this is handled before the generic table so it is only ever
            # evaluated for this action, never eagerly for every write.
            total_xp = self._required_total_xp(value)
            return (
                f"UPDATE tb_13c52bbaa8 SET c_e3aa3bf474={value},c_8ef3c1757a={total_xp} "
                f"WHERE {self._ACCOUNT_COLUMN}={account_id} AND {self._IS_HUNTER_COLUMN}=0"
            )
        statements = {
            "gold": (
                f"UPDATE tb_e973c32e29 SET c_d1f333420b={value} "
                f"WHERE {self._ACCOUNT_COLUMN}={account_id}"
            ),
            "player_scrolls": (
                f"UPDATE tb_e973c32e29 SET c_418025e253={value} "
                f"WHERE {self._ACCOUNT_COLUMN}={account_id}"
            ),
            "weapon_scrolls": (
                f"UPDATE tb_e973c32e29 SET c_ac7e41767f={value} "
                f"WHERE {self._ACCOUNT_COLUMN}={account_id}"
            ),
            "special_scrolls": (
                f"UPDATE tb_e973c32e29 SET c_a9d19edb77={value} "
                f"WHERE {self._ACCOUNT_COLUMN}={account_id}"
            ),
            "points": (
                f"UPDATE tb_957a223c9b SET c_c982c144a0={value} "
                f"WHERE {self._ACCOUNT_COLUMN}={account_id} AND {self._ACTIVE_STATS_COLUMN}=1"
            ),
            "strength": (
                f"UPDATE tb_957a223c9b SET c_7e92e023a5={value - 1} "
                f"WHERE {self._ACCOUNT_COLUMN}={account_id} AND {self._ACTIVE_STATS_COLUMN}=1"
            ),
            "vitality": (
                f"UPDATE tb_957a223c9b SET c_1c77e26632={value - 1} "
                f"WHERE {self._ACCOUNT_COLUMN}={account_id} AND {self._ACTIVE_STATS_COLUMN}=1"
            ),
            "agility": (
                f"UPDATE tb_957a223c9b SET c_b91b1c4561={value - 1} "
                f"WHERE {self._ACCOUNT_COLUMN}={account_id} AND {self._ACTIVE_STATS_COLUMN}=1"
            ),
            "intelligence": (
                f"UPDATE tb_957a223c9b SET c_3cd914b873={value - 1} "
                f"WHERE {self._ACCOUNT_COLUMN}={account_id} AND {self._ACTIVE_STATS_COLUMN}=1"
            ),
            "perception": (
                f"UPDATE tb_957a223c9b SET c_795582f14f={value - 1} "
                f"WHERE {self._ACCOUNT_COLUMN}={account_id} AND {self._ACTIVE_STATS_COLUMN}=1"
            ),
            "difficulty": (
                f"UPDATE tb_bf41c3a26c SET c_8401e00524={value} "
                f"WHERE {self._ACCOUNT_COLUMN}={account_id}"
            ),
        }
        if action == "hunter_level":
            if identifier is None:
                raise SaveEditorError("The selected hunter row has no identifier.")
            return (
                f"UPDATE tb_13c52bbaa8 SET c_e3aa3bf474={value} "
                f"WHERE {self._ACCOUNT_COLUMN}={account_id} AND c_d4f6740b9b={identifier}"
            )
        if action == "inventory_count":
            if identifier is None:
                raise SaveEditorError("The selected inventory row has no identifier.")
            return (
                f"UPDATE tb_d40f87183c SET c_8eb30bb564={value} "
                f"WHERE {self._ACCOUNT_COLUMN}={account_id} AND c_20bfd7b86b={identifier}"
            )
        try:
            return statements[action]
        except KeyError as error:
            raise SaveEditorError(f"Unsupported write action: {action}") from error

