# Building A Windows Executable

The application can be built as a local, one-file Windows executable with
PyInstaller. The build process packages Python, PySide6, qasync, the editor
code, and the existing `vendor/gamedata.pyc` catalog parser into `dist/`.

It does not package game data, `sqlcipher.dll`, save databases, Steam IDs,
save keys, backups, or user settings. Users select their installed GameData
directory from **File > Settings...** after launching the executable.

## Prerequisites

- Windows with Python 3.12 or later.
- [uv](https://docs.astral.sh/uv/).
- A local checkout of this repository.

## Build Options

From the repository root, run:

```powershell
uv sync --locked --group build
./BuildExecuteable.ps1
```

This creates `dist/SaveGameEditor.exe`. It embeds Python, Qt, and the required
application resources into one executable and extracts them to a temporary
directory while it runs.

The same build is available from Command Prompt:

```bat
BuildExecuteable.bat
```

`build/` and `dist/` are generated, ignored directories and can be deleted
between builds.

## Distribution

Distribute `dist/SaveGameEditor.exe` as one file. Do not add game DLLs,
GameData files, real save files, decrypted databases, Steam IDs, save keys, or
local application configuration to either distribution or to source control.

The executable reads the embedded parser after extraction. When running from
source, it uses `vendor/gamedata.pyc` at the repository root.
