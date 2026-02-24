"""PyInstaller entry point. To play normally use: python3 -m roguelike"""
import curses
from roguelike.__main__ import main, _prepare_terminal
_prepare_terminal()
curses.wrapper(main)
