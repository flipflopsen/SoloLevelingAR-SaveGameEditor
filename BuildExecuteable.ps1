$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSCommandPath
Push-Location $projectRoot
try {
    uv sync --locked --group build
    uv run --group build pyinstaller --noconfirm --clean --windowed --onefile `
        --name SaveGameEditor --distpath dist --workpath build/pyinstaller `
        --specpath build/pyinstaller --icon "$projectRoot\data\256x256.ico" `
        --add-data "$projectRoot\data\256x256.ico;data" `
        --add-data "$projectRoot\vendor\gamedata.pyc;vendor" `
        SaveGameEditor.py
}
finally {
    Pop-Location
}
