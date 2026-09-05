# Save Editor Developer Notes

This folder is the publishable, developer-facing record of the local save
research that led to this editor. It contains findings, evidence limits,
schemas, and repeatable validation steps, but deliberately does not redistribute
the original editor executable, its extracted files, decompiled output, save
dumps, or analysis scripts.

## Scope and Safety

The editor is for an owner working with a local `LocalSave_*.db` file. The save
uses SQLCipher, and the application opens it using the SQLCipher DLL already
installed with the game. Always close the game before inspecting a save. Every
write must have a full backup of the database and matching SQLite sidecar files.

The editor snapshots those files into `SaveEditorBackups/<timestamp>/` before a
transaction. This is a practical safeguard, not a guarantee that a modified
save will be accepted by every game version.

## Documentation Index

| File | Role |
| --- | --- |
| [EDITOR_README.md](EDITOR_README.md) | Current installation, startup, UI, and backup behavior. |
| [PLAYER_STATS_WALLET_SQL.md](PLAYER_STATS_WALLET_SQL.md) | Verified main-player, wallet, core-stat, and level operations with SQL examples. |
| [RUNTIME_TRACING_GUIDE.md](RUNTIME_TRACING_GUIDE.md) | Controlled runtime-observation workflow for verifying additional mappings. |
| [mappings/entity_map_baseline.json](mappings/entity_map_baseline.json) | Initial, evidence-scoped entity map for known tables and columns. |
| [mappings/entity_map_comparative.json](mappings/entity_map_comparative.json) | Full 410-table comparative schema map, preserving `verified`, `partial`, and `schema_only` confidence. |
| [reports/save_semantics_report.json](reports/save_semantics_report.json) | Offline catalog and relationship analysis: 410 tables, 482 catalog files, and localized identifiers. |

## Process Record

1. The original application was identified as a 64-bit PyInstaller package that
   embeds CPython 3.10 bytecode. The original executable and extracted content
   are not included here.
2. Local, owner-provided saves were opened with the game-installed SQLCipher
   library using SQLCipher 4-compatible settings: page size `4096`, `kdf_iter`
   `256000`, and PBKDF2/HMAC SHA-512 algorithms.
3. The save passphrase derivation was independently reproduced in the new
   editor: base64-encoded Rijndael-256-CBC with PKCS#7 padding, taking the
   ASCII SteamID64 as input. This uses a 32-byte Rijndael block and is not
   standard 16-byte-block AES. A known SteamID64 test vector validated the
   implementation byte-for-byte.
4. Encrypted save contents were exported only to local working copies for
   offline schema analysis. Two saves at different progression levels were
   compared without treating generated primary-key equality as identity.
5. Installed GameData catalogs and `TextData.byte` localization were parsed to
   turn catalog IDs into human-readable item, hunter, cosmetic, title, and
   achievement names.
6. Mappings were classified by evidence. Only the verified subset should power
   write actions. Catalog-value overlap and row-count deltas are useful leads,
   but do not establish a field's runtime meaning by themselves.

## Verified Editor Surface

The current editor supports conservative mutation of these fields only:

- Gold.
- Main-character level, constrained to `1` through `75`.
- Active-preset unspent points and Strength, Vitality, Agility, Intelligence,
  and Perception. Core stats store displayed value minus one.
- Existing hunter levels, constrained to `1` through `75`.
- Counts for existing inventory rows.
- Story difficulty values `2` (Normal), `3` (Hard), and `4` (New Game+). The
  New Game+ setting has not been tested before normal in-game unlock.

The current UI also exposes mapped read-only views for owned items, cosmetics,
titles, and achievements. It does not add or delete inventory, ownership, or
unlock rows because safe row construction and connected state updates have not
yet been established.

The player guide is authoritative for player-stat and scroll write semantics.
In particular, player, weapon, and special skill scrolls are per-preset values
in `tb_957a223c9b`; do not substitute similarly named wallet fields without a
new independent verification.

## Evidence Standard

Use these confidence labels exactly as the maps use them:

- `verified`: supported by at least two independent signals, usually a runtime
  trace or controlled save delta together with catalog or static operation
  evidence.
- `partial`: the table structure or a subset of fields is supported, while
  other meanings remain unconfirmed.
- `candidate`: an automated catalog or relationship correlation that needs a
  focused validation experiment.
- `schema_only`: table and SQL schema captured, with no asserted game meaning.

When extending the editor, follow the tracing guide with one user-visible
action per disposable copied save. Confirm a proposed mapping with a trace plus
a before/after delta or catalog-backed UI label before allowing writes.

## Explicit Exclusions

This folder intentionally contains no:

- Original `SoloLevelingSaveEditor.exe` file or its PyInstaller archive.
- Extracted Python bytecode, disassemblies, decompiled source, or GameData
  parser bytecode.
- Original editor helper scripts or runtime instrumentation code.
- Any encrypted `.db`, exported `.sql`, SteamID64, derived key, or raw
  save-record export.

The included JSON files are independently generated mapping and analysis
artifacts. Their provenance descriptions may mention the original application
as an evidence source; that source material is not included or redistributed.
They retain non-sensitive sample values such as the local database account
selector (`1`) where needed to explain a verified query or mapping.
