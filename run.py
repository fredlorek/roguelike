"""PyInstaller entry point. To play normally use: python3 -m roguelike"""
import curses
from roguelike.__main__ import main
curses.wrapper(main)
