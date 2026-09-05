# Architecture

`savegame_editor` is a local desktop package with three responsibility layers.

- `config` serializes typed user settings as JSON under the operating-system
  configuration directory.
- `core` contains path derivation, save discovery, key derivation, SQLCipher,
  catalog resolution, and write-value validation. It does not import Qt widgets.
- `services.SaveService` owns the current database, all original verified SQL
  queries, write statements, and backup transactions.
- `ui` renders service tables with PySide6. It delegates scan and database work
  to background execution while qasync drives the combined Qt/asyncio loop.

The `GameData` directory is the only configured game installation path. The
SQLCipher plugin directory is deterministically derived from its parent to
match the original editor's layout convention.