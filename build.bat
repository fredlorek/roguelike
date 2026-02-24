@echo off
pip install pyinstaller windows-curses
pyinstaller --onefile --name "Meridian" run.py
echo Build complete: dist\Meridian.exe
