#!/bin/sh
pip install pyinstaller
pyinstaller --onefile --name "Meridian" run.py
echo "Build complete: dist/Meridian"
