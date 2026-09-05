@echo off
setlocal
cd /d "%~dp0"

uv sync --locked --group build
if errorlevel 1 exit /b %errorlevel%
uv run --group build pyinstaller --noconfirm --clean --windowed --onefile --name SaveGameEditor --distpath dist --workpath build/pyinstaller --specpath build/pyinstaller --icon "%CD%\data\256x256.ico" --add-data "%CD%\data\256x256.ico;data" --add-data "%CD%\vendor\gamedata.pyc;vendor" SaveGameEditor.py
exit /b %errorlevel%
