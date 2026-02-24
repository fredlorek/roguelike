"""Entry point — run with: python3 -m roguelike"""

import curses
import os
import pathlib
import pickle
import sys

from .ui import (setup_colors, show_character_creation, show_ship_screen,
                 show_nav_computer, show_run_summary)
from .world import make_sites
from .game import run_site, run_overland

# ── Save file path (cross-platform) ──────────────────────────────────────────
if sys.platform == 'win32':
    _base = pathlib.Path(os.environ.get('APPDATA', '~')).expanduser()
else:
    _base = pathlib.Path.home()
SAVE_PATH = _base / '.roguelike' / 'save.pkl'


# ── Save helpers ──────────────────────────────────────────────────────────────

def save_game(player, sites):
    """Atomically write game state to SAVE_PATH."""
    SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SAVE_PATH.with_suffix('.tmp')
    with open(tmp, 'wb') as f:
        pickle.dump({'player': player, 'sites': sites}, f)
    tmp.replace(SAVE_PATH)


def load_game():
    """Return (player, sites) from SAVE_PATH, or None if no valid save exists."""
    if not SAVE_PATH.exists():
        return None
    try:
        with open(SAVE_PATH, 'rb') as f:
            data = pickle.load(f)
        return data['player'], data['sites']
    except Exception:
        return None


def delete_save():
    """Remove the save file if it exists."""
    try:
        SAVE_PATH.unlink()
    except FileNotFoundError:
        pass


# ── Continue screen ───────────────────────────────────────────────────────────

def show_continue_screen(stdscr, player, sites):
    """Show startup menu when a save exists. Returns 'continue', 'new', or 'quit'."""
    erebus = next((s for s in sites if s.name == 'Erebus Station'), None)
    depth  = max(erebus.floors.keys()) if erebus and erebus.floors else 0
    suffix = f"  (Erebus fl.{depth})" if depth else ""

    while True:
        stdscr.clear()
        h, w = stdscr.getmaxyx()
        cx = max(0, (w - 46) // 2)
        cy = max(0, h // 2 - 4)

        try:
            stdscr.addstr(cy,     cx, "THE MERIDIAN")
            stdscr.addstr(cy + 1, cx, '\u2500' * 46)
            stdscr.addstr(cy + 3, cx,
                f"  [C]  Continue  \u2014 {player.name}  Lv {player.level}{suffix}")
            stdscr.addstr(cy + 4, cx, "  [N]  New Game")
            stdscr.addstr(cy + 5, cx, "  [Q]  Quit")
            stdscr.addstr(cy + 6, cx, '\u2500' * 46)
        except curses.error:
            pass

        stdscr.refresh()
        key = stdscr.getch()

        if key in (ord('c'), ord('C')):
            return 'continue'
        if key in (ord('n'), ord('N')):
            return 'new'
        if key in (ord('q'), ord('Q'), 27):
            return 'quit'


# ── Main ──────────────────────────────────────────────────────────────────────

def main(stdscr):
    curses.curs_set(0)
    stdscr.keypad(True)
    setup_colors()

    # Check for an existing save on startup
    preloaded = None
    saved = load_game()
    if saved:
        saved_player, saved_sites = saved
        choice = show_continue_screen(stdscr, saved_player, saved_sites)
        if choice == 'quit':
            return
        if choice == 'new':
            delete_save()
        if choice == 'continue':
            preloaded = (saved_player, saved_sites)

    while True:   # outer loop: new run on restart
        if preloaded:
            player, sites = preloaded
            preloaded = None
        else:
            player = show_character_creation(stdscr)
            sites  = make_sites()

        while True:   # inner loop: ship <-> site
            action = show_ship_screen(stdscr, player, sites)

            if action == 'quit':
                save_game(player, sites)
                return
            if action == 'restart':
                break   # break inner -> outer -> new character creation

            # action == 'nav'
            site = show_nav_computer(stdscr, player, sites)
            if site is None:
                continue   # player pressed Esc

            player.fuel -= max(0, site.fuel_cost - player.fuel_discount)
            result = run_overland(stdscr, site, player)

            if result == 'back_to_ship':
                save_game(player, sites)
            elif result == 'dead':
                delete_save()
                if show_run_summary(stdscr, player, site.name, outcome='dead'):
                    break   # new run
                else:
                    return  # quit
            elif result == 'restart':
                delete_save()
                if show_run_summary(stdscr, player, site.name, outcome='restart'):
                    break   # new run
                else:
                    return  # quit
            # result == 'back_to_ship': loop back to ship screen


if __name__ == '__main__':
    curses.wrapper(main)
