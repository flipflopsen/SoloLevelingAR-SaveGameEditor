# Important note
Basically most of this was created because I wanted to use Python 3.12+, but the gamedata.pyc, extracted from [All-in-One Save Editor](https://www.nexusmods.com/sololevelingariseoverdrive/mods/4) by Kraken092, is as far as the magic bytes told me in Python 3.10.
Thus I did migrate my whole Project from 3.12 -> 3.10, but I will leave the tooling and documentations here because maybe someone is interested.

# Standalone Tools

Self-contained, single-file scripts extracted from `src/savegame_editor/core`
so they can be copied and run independently of the rest of the editor. Each
script only needs the Python standard library — no `uv sync` or project
install required, just a Python 3.12+ interpreter.

| Script            | Purpose                                                        |
| ----------------- | --------------------------------------------------------------- |
| `save_key.py`     | Derive the local SQLCipher save key from a SteamID64.           |
| `find_saves.py`   | List locally installed `LocalSave_*.db` files for a SteamID64.  |
| `decrypt_save.py` | Open a save database and list its tables or run a read-only SQL query (Windows only, needs the game's `sqlcipher.dll`). |
| `inspect_saves.py` | Inventory and compare local save databases. |
| `gamedata_codec.py` | Reference decoder for `GameData/*.byte` (Rijndael-256-CBC + typed column store). Imported by the two scripts below; NumPy is used only as an optional fast path. |
| `inspect_gamedata.py` | Inventory every `.byte` file: size, SHA-256, table/column/row counts, parse status. |
| `decode_gamedata.py` | Dump one `.byte` table's parsed columns (optionally localized through `TextData.byte`) to JSON. |

## Usage

```powershell
# Derive a save key
python save_key.py 7656119XXXXXXXXXX

# Find local saves
python find_saves.py 7656119XXXXXXXXXX

# List tables in a save (deriving the key from the SteamID64)
python decrypt_save.py C:\path\to\LocalSave_0.db --steam-id 7656119XXXXXXXXXX --game-data "C:\...\GameData"

# Run a read-only query using an already-derived key and explicit DLL directory
python decrypt_save.py C:\path\to\LocalSave_0.db --key <base64-key> --dll-dir "C:\...\Plugins\x86_64" --query "SELECT * FROM PlayerData LIMIT 5"
```

Run any script with `-h`/`--help` for the full option list.

## GameData decoding

`gamedata_codec.py` documents and implements the `.byte` container format
(Rijndael-256-CBC, `key == iv == b"levelup321" + b"\x00" * 22`, followed by a
typed column store). Unlike `vendor/gamedata.pyc` — which is Python 3.10
bytecode and cannot be unmarshalled on Python 3.12 — it runs on the project's
supported interpreter. Its output was verified byte-for-byte against
`vendor/gamedata.pyc`'s `parse_typed` on all 483 shipped `.byte` files; see
`analysis/decoding_report.md`.

```powershell
# Inventory every .byte file (hashes, columns, parse status)
python inspect_gamedata.py --game-data "C:\...\GameData" --out ..\analysis\gamedata_inventory.json

# Check the optional NumPy fast path against the reference pure-Python decrypt
python inspect_gamedata.py --game-data "C:\...\GameData" --self-test

# List tables, then dump one with English names resolved
python decode_gamedata.py --game-data "C:\...\GameData" --list
python decode_gamedata.py --game-data "C:\...\GameData" --table ItemTitle `
    --columns ID StringTitle --localize StringTitle --records
```

`TextData.byte` is ~96 MB (3,003,033 cipher blocks); decoding it takes a while
without NumPy installed.

## Safety

These tools only read data by default (`decrypt_save.py` never writes
without an explicit `PRAGMA`/`UPDATE` in `--query`, and none of the built-in
commands modify a save). Still, always keep a backup of any save file before
experimenting on it. Never commit a real save, decrypted database, Steam ID,
save key, or game DLL to source control.
