#!/bin/sh
pip install pyinstaller
pyinstaller --onefile --name "The Meridian" run.py
echo "Build complete: dist/The Meridian"
