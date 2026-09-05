# Runtime SQLCipher Tracing

This guide records the SQL text the local game submits to its own SQLCipher
library. It is intended to identify table and field use for offline save
research. It does not change saves, bypass authentication, or send data over
the network.

Use this only with a local copy of the game and save files you own. Keep the
game offline where possible, do not use this against multiplayer services, and
follow the game's terms of service.

## What You Need

- A backup of the save folder before each session.
- Python 3.10 or later.
- The game installed at any path, in my case I've copied it from the steamapps dir to a seperate dir to mess with it `H:\Games\SL`.
- [trace_sqlcipher.js](trace_sqlcipher.js) from this folder.
- Frida Tools installed for the same Python interpreter used in the commands.

Install Frida Tools once:

```powershell
& python.exe -m pip install --user frida-tools
frida --version
```

The installation should provide the `frida` command. If PowerShell cannot find
it, run `py -m frida_tools` only after checking the installed package's console
script location, or add the Python Scripts directory to `PATH`.

## Session Preparation

1. Close the game completely.
2. Copy the entire active save folder, including any sidecar files, to a dated
   backup directory. Never trace against the only copy of a save.
3. Create a new trace folder and an action log:

```powershell
New-Item -ItemType Directory -Force .\Saves\Dumped\traces\inventory-open | Out-Null
Set-Content .\Saves\Dumped\traces\inventory-open\notes.txt 'Start game, open inventory, inspect one artifact, then exit.'
```

4. Start the game normally and wait until the main menu has finished loading.

## Attach the SQL Trace

From the `SaveEditor` directory, run:

```powershell
frida -n Solo_Leveling_ARISE_OVERDRIVE.exe -l .\Saves\Dumped\trace_sqlcipher.js -o .\Saves\Dumped\traces\inventory-open\sqlcipher.log
```

The helper waits for `sqlcipher.dll`, then hooks database opening, prepared SQL,
bind calls, `sqlite3_step`, and `sqlite3_exec`. Its output is JSON Lines: a
`prepare` event associates a statement address with SQL text, bind events are
collected in memory, and each `step` emits the SQL with its current bindings.
It intentionally does not hook or log `sqlite3_key`, so the save passphrase is
not written to the trace. Blob values are represented only by their byte length;
text values are capped at 512 bytes.

Wait for lines such as:

```text
{"event":"installed","export":"sqlite3_prepare_v2"}
```

If no `installed` lines appear, make sure the process name in the command
matches Task Manager exactly. You can list local processes that Frida sees with:

```powershell
frida-ps -l | Select-String 'Solo|Leveling'
```

Stop Frida with `Ctrl+C` after each focused test. This detaches the hooks; it
does not terminate the game.

## Run Focused Tests

Perform one interaction group per trace. Avoid changing save state while
capturing a menu-read trace.

Good first groups:

- Open the inventory, then inspect one material, artifact, relic weapon, and
  hunter weapon.
- Open the hunter roster and one hunter's skills, stats, loadout, and shadow
  details.
- Open cosmetics, titles, profile customization, and the emote wheel.
- Open achievements and one individual achievement category.
- Open each progression screen: quests, chapters, gates, dungeons, workshop,
  collections, and codex.

For a write-focused trace, work on a disposable copied save. Make exactly one
normal in-game change, wait for the save indicator to finish, then exit. Add the
action, visible before/after value, and timestamp to `notes.txt`.

Examples:

```text
14:03:10 Opened Hunter > Cha Hae-In > Equipment.
14:03:32 Equipped the shown artifact in the Chestplate slot.
14:03:39 Save indicator finished.
```

## Export and Correlate the Save

After a write test, close the game, make another backup, and export the save:

```powershell
& python.exe .\dump_save_db.py <save.db> <derived-key> --output .\Saves\Dumped\traces\inventory-open\after.db.sql
```

Run the offline analyzer against the new dump:

```powershell
& python.exe .\Saves\Dumped\analyze_save_semantics.py --dump .\Saves\Dumped\traces\inventory-open\after.db.sql --output .\Saves\Dumped\traces\inventory-open\semantics.json
```

The analyzer resolves values against every installed `GameData/*.byte` catalog
and localizes `StringName`, `Name`, and similar fields through `TextData.byte`.
It also reports probable relationships where a column's values are contained in
another table's primary-key values.

Compare a trace with its SQL dump as follows:

1. Locate a `prepare`, `step`, or `exec` event mentioning a `tb_*` table or
  `c_*` field. A `step` after an `UPDATE`, `INSERT`, or `DELETE` is the most
  useful write evidence because it contains the current bound values.
2. Find that table and column in `semantics.json`.
3. Use the reported catalog match examples to translate IDs into game labels.
4. Treat a label as verified only if the UI action, SQL trace, and catalog match
   all agree.
5. Add the result to the entity map with the trace filename as evidence.

Use PowerShell to isolate a table quickly:

```powershell
Select-String -Path .\Saves\Dumped\traces\inventory-open\sqlcipher.log -Pattern 'tb_adfb9b0bf5|tb_995a0666e4'
```

## Static IL2CPP Follow-Up

Runtime traces show what the game accesses. IL2CPP analysis can sometimes reveal
the original model names and call sites responsible for the SQL.

The required local files are already available:

```text
H:\Games\SL\GameAssembly.dll
H:\Games\SL\Solo_Leveling_ARISE_OVERDRIVE_Data\il2cpp_data\Metadata\global-metadata.dat
```

Open those files in a current IL2CPP analysis tool such as Cpp2IL. Export the
analysis to a separate working folder, then search the output for the exact
`tb_*` and `c_*` strings captured by the trace. Record the surrounding class,
method, and field names. Tool command lines vary by release, so use its current
documentation rather than relying on an old invocation copied from elsewhere.

This step is most useful after tracing: a specific table name is a precise search
target, whereas trying to map all generated SQL names from the full binary is
slow and produces many unrelated hits.

## Troubleshooting

- `unable to find process`: Start the game first and get its exact process name
  from `frida-ps -l`.
- No hook-install messages: `sqlcipher.dll` may not have loaded yet; enter a
  screen that reads a save and wait a few seconds. The script polls every 250 ms.
- Access violation or game instability: Detach immediately with `Ctrl+C`; do not
  continue that run. Capture a smaller menu-read scenario next time.
- Very large logs: Trace one menu at a time and stop Frida between scenarios.
- Key-like data in logs: Delete that trace and avoid broad memory hooks. The
  supplied helper records SQL only and never reads the key function arguments.

## Evidence Standard

Mark a map entry `verified` only with at least two independent signals, normally
one of these pairs:

- Runtime SQL trace plus a matching controlled before/after save delta.
- Runtime SQL trace plus GameData catalog-ID resolution and visible UI label.
- Editor bytecode operation plus trace confirmation.

Catalog-ID overlap alone is useful automation, but it remains a `candidate`.
