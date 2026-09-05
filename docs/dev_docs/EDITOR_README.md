# Solo Leveling Save Editor

A standalone Windows desktop editor for local `LocalSave_*.db` files from Solo
Leveling: ARISE OVERDRIVE. It uses the installed game's `sqlcipher.dll` and
only Python standard-library modules, so `requirements.txt` has no pip package
requirements.

## Start

Double-click `run_editor.bat`, or run it through python. Python 3.10 was used and is recommended for usage of it.

Enter the full path to an encrypted `LocalSave_*.db`, plus either its owning
17-digit SteamID64 or a previously derived SQLCipher save key. A database path
alone cannot recover its key; the Steam ID supplies the derivation input.

The game-data and SQLCipher locations used for this installation were:

```text
H:\Games\SL\GameData
H:\Games\SL\Solo_Leveling_ARISE_OVERDRIVE_Data\Plugins\x86_64
```

Change the constants at the top of `save_editor.py` if the game is installed
elsewhere.

## Supported Screens

- **Player Stats:** Gold, player/weapon/special skill scrolls, main-character
  level, unspent points, and all five core stats.
- **Hunters:** Resolved hunter IDs and verified level editing.
- **Inventory:** Resolved material/item IDs and verified stack-count editing.
- **Owned Items:** Artifacts, relic weapons, hunter weapons, and blessing
  stones for inspection.
- **Cosmetics, Titles, Achievements:** Mapped read-only catalog views.
- **Difficulty:** Verified story-difficulty edit (2 Normal, 3 Hard, 4 New
  Game+; forcing New Game+ before the story permits it remains untested).

Each write runs in a transaction and snapshots the `.db` plus any matching
SQLite sidecar files into `SaveEditorBackups/<timestamp>/` next to the source
save. Close the game before opening or modifying a save, and keep a separate
untouched backup before every editing session.

## Included Data

`data/entity_map.json` holds the evidence-scoped database map. The embedded
`vendor/gamedata.pyc` parser reads the installed GameData catalogs to turn item
and unit IDs into names. Neither writes GameData files.
