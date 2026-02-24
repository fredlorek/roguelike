@echo off
pip install pyinstaller windows-curses
pyinstaller --onefile --name "The Meridian" run.py
echo Build complete: dist\The Meridian.exe
