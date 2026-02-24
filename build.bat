@echo off
pip install pyinstaller windows-curses
pyinstaller --onefile --name "The Meridian" roguelike/__main__.py
echo Build complete: dist\The Meridian.exe
