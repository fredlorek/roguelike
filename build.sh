#!/bin/sh
pip install pyinstaller
pyinstaller --onefile --name "The Meridian" roguelike/__main__.py
echo "Build complete: dist/The Meridian"
