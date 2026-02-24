"""Entry point — run with: python3 -m roguelike"""

import curses

from .ui import (setup_colors, show_character_creation, show_ship_screen,
                 show_nav_computer, show_run_summary)
from .world import make_sites
from .game import run_site


def main(stdscr):
    curses.curs_set(0)
    stdscr.keypad(True)
    setup_colors()

    while True:   # outer loop: new run on restart
        player = show_character_creation(stdscr)
        sites  = make_sites()

        while True:   # inner loop: ship <-> site
            action = show_ship_screen(stdscr, player, sites)

            if action == 'quit':
                return
            if action == 'restart':
                break   # break inner -> outer -> new character creation

            # action == 'nav'
            site = show_nav_computer(stdscr, player, sites)
            if site is None:
                continue   # player pressed Esc

            player.fuel -= max(0, site.fuel_cost - player.fuel_discount)
            result = run_site(stdscr, site, player)

            if result == 'dead':
                if show_run_summary(stdscr, player, site.name, outcome='dead'):
                    break   # new run
                else:
                    return  # quit

            if result == 'restart':
                if show_run_summary(stdscr, player, site.name, outcome='restart'):
                    break   # new run
                else:
                    return  # quit
            # result == 'escaped': loop back to ship screen


if __name__ == '__main__':
    curses.wrapper(main)
