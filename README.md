# Solo Leveling Save Editor

A Python-only, local Windows desktop editor for owner-provided
`LocalSave_*.db` files from Solo Leveling: ARISE OVERDRIVE. It uses PySide6,
qasync, and the game's locally installed `sqlcipher.dll`. The application has
no web interface, cloud service, telemetry, or network dependency.

## Safety

Close the game before opening a save. Every write first copies the selected
database and matching SQLite sidecar files into
`SaveEditorBackups/<timestamp>/` beside the save. This safeguard does not
guarantee that every modified save will be accepted by every game version.
Keep an untouched manual backup before editing.

Never commit a real save, decrypted database, Steam ID, save key, game DLL, or
application-local settings. Persistent settings are stored in the current
user's application configuration directory, outside this repository.

## Safety - For real

I've never had any problem opening a save while I was in the hub of the game, 
edited values to figure out which item ID is actually which item and so on.
Kinda used it like Cheat-Engine but without the changed value automatically glowing up, maybe I'll add that or someone else will.

## Quick and Easy
- You can download and run the prebuilt Binary from the Releases-Page. Works for Windows x64.

## Prerequisites

- Windows and Python 3.10 or later.
- [uv](https://docs.astral.sh/uv/).
- A local Solo Leveling: ARISE OVERDRIVE installation with `GameData` and its
  adjacent `Solo_Leveling_ARISE_OVERDRIVE_Data/Plugins/x86_64/sqlcipher.dll`.

## Install And Run

```powershell
uv venv
uv sync
uv run python -m savegame_editor
```

`uv venv` creates the project's `.venv` virtual environment (skip it if one
already exists — `uv sync` creates it automatically otherwise). If a stale or
broken `.venv` needs to be rebuilt, recreate it with:

```powershell
uv venv --clear
uv sync
```

## Editor workspace

The editor uses a compact dark technical layout with fixed table navigation,
a searchable and sortable save-data grid, column visibility controls, CSV
export, and an optional resizable row inspector. Edit supported numeric cells
inline, review the amber staged-change markers, then use **Save changes** to
create one full backup and atomically apply all staged edits. Undo and redo
operate only on staged changes and never write to the save file.

Settings includes four persisted accent themes: Sleek Purple, Sleek Green,
Sleek Blue, and Sleek Red, plus an optional custom `#RRGGBB` accent picker.
`run_editor.bat` runs the same module command. The first launch opens with no
user-specific values configured; choose **File > Settings...** to configure
the editor.

For a distributable Windows executable, see
[docs/BUILD_WINDOWS_EXECUTABLE.md](docs/BUILD_WINDOWS_EXECUTABLE.md).

## Settings And Discovery

The Settings dialog stores these values locally:

- **GameData directory:** selected with the native directory picker and
  validated as a directory. The SQLCipher location is derived only from this
  value using the existing installation convention:
  `<GameData parent>/Solo_Leveling_ARISE_OVERDRIVE_Data/Plugins/x86_64`.
- **Steam ID64 or save key:** stored as the string field `steam_id`. A standard
  17-digit SteamID64 derives the SQLCipher key and is used to discover saves.
- **Discovered local saves:** choose the active encrypted database from the
  Slot1-3 candidate list.

For a conventional 17-digit SteamID64, **Rescan** checks all of these local
directories and orders candidates by Slot1–Slot3, then newest modification
time:

```text
%USERPROFILE%/AppData/LocalLow/NetmarbleNeo/Solo_Leveling_ARISE_OVERDRIVE/<SteamID64>/SaveFolder/Slot{1,2,3}/LocalSave_*.db
```

The user name is resolved from the operating-system home directory; it is not
embedded in source. The selected discovered database path persists locally.

## Development

```powershell
uv venv
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

The project uses a `src/` layout. `core` contains local path, cryptography,
database, and validation primitives; `services` owns save read/write behavior;
and `ui` contains PySide6 models and widgets. Qt work and local file/database
work are separated by a single background worker while qasync runs the Qt and
asyncio event loop.

## Supported Editor Surface

- Player stats, gold, and player/weapon/special skill scrolls.
- Existing hunter levels and inventory counts.
- Story difficulty values 2 (Normal), 3 (Hard), and 4 (New Game+).
- Views for owned items, cosmetics, titles, and achievements. (Some read only, some not)
- Adding rows was kinda tough to implement, because I literally did this on the side over a span of 2 days.

Only verified save fields have write actions. See [dev_docs](dev_docs) for the
research record and evidence boundaries. `data/entity_map.json` remains the
evidence-scoped map, and the existing local `vendor/gamedata.pyc` parser is
used only to resolve installed game-data names.
The gamedata.pyc was extracted from [All-in-One Save Editor](https://www.nexusmods.com/sololevelingariseoverdrive/mods/4) from Nexusmods.

## Standalone Tools

The [tools](tools) folder contains single-file, standard-library-only
copies of the save-key derivation, save-discovery, and save-database
inspection logic. They have their own CLI entry points and can be copied
and run independently of the rest of this project — no `uv sync` needed.
See [tools/README.md](tools/README.md) for usage.


## LICENSE

Do whatever you want to do with it, this is from the community, for the community. 