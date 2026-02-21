#!/usr/bin/env python3
"""Simple terminal roguelike using curses."""

import curses
import random

MAP_W = 80
MAP_H = 40
WALL  = '#'
FLOOR = '.'
PLAYER = '@'


class Room:
    def __init__(self, x, y, w, h):
        self.x1, self.y1 = x, y
        self.x2, self.y2 = x + w, y + h

    def center(self):
        return (self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2

    def intersects(self, other, pad=1):
        return (self.x1 - pad < other.x2 and self.x2 + pad > other.x1 and
                self.y1 - pad < other.y2 and self.y2 + pad > other.y1)


def generate_dungeon():
    tiles = [[WALL] * MAP_W for _ in range(MAP_H)]
    rooms = []

    for _ in range(30):
        w = random.randint(5, 12)
        h = random.randint(4, 9)
        x = random.randint(1, MAP_W - w - 1)
        y = random.randint(1, MAP_H - h - 1)
        room = Room(x, y, w, h)

        if any(room.intersects(r) for r in rooms):
            continue

        # Carve the room
        for ry in range(room.y1, room.y2):
            for rx in range(room.x1, room.x2):
                tiles[ry][rx] = FLOOR

        # Carve a corridor to the previous room
        if rooms:
            cx1, cy1 = room.center()
            cx2, cy2 = rooms[-1].center()
            if random.random() < 0.5:
                for rx in range(min(cx1, cx2), max(cx1, cx2) + 1):
                    tiles[cy1][rx] = FLOOR
                for ry in range(min(cy1, cy2), max(cy1, cy2) + 1):
                    tiles[ry][cx2] = FLOOR
            else:
                for ry in range(min(cy1, cy2), max(cy1, cy2) + 1):
                    tiles[ry][cx1] = FLOOR
                for rx in range(min(cx1, cx2), max(cx1, cx2) + 1):
                    tiles[cy2][rx] = FLOOR

        rooms.append(room)

    start = rooms[0].center() if rooms else (MAP_W // 2, MAP_H // 2)
    return tiles, start


# Color pair indices
COLOR_WALL   = 1
COLOR_FLOOR  = 2
COLOR_PLAYER = 3


def setup_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(COLOR_WALL,   curses.COLOR_WHITE,  -1)
    curses.init_pair(COLOR_FLOOR,  curses.COLOR_BLACK,  -1)
    curses.init_pair(COLOR_PLAYER, curses.COLOR_YELLOW, -1)


def draw(stdscr, tiles, px, py):
    term_h, term_w = stdscr.getmaxyx()
    view_h = term_h - 2  # reserve two rows for the status bar

    # Center camera on player, clamped to map bounds
    cam_x = max(0, min(px - term_w // 2, max(0, MAP_W - term_w)))
    cam_y = max(0, min(py - view_h // 2, max(0, MAP_H - view_h)))

    stdscr.erase()

    for sy in range(view_h):
        my = sy + cam_y
        if my >= MAP_H:
            break
        for sx in range(term_w):
            mx = sx + cam_x
            if mx >= MAP_W:
                break

            if mx == px and my == py:
                ch    = PLAYER
                attr  = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD
            elif tiles[my][mx] == WALL:
                ch    = WALL
                attr  = curses.color_pair(COLOR_WALL)
            else:
                ch    = FLOOR
                attr  = curses.color_pair(COLOR_FLOOR) | curses.A_DIM

            try:
                stdscr.addch(sy, sx, ch, attr)
            except curses.error:
                pass  # ignore write-to-corner error

    # Status bar
    status = " WASD / Arrows: move  |  R: new dungeon  |  Q: quit "
    divider = curses.ACS_HLINE
    try:
        for sx in range(term_w - 1):
            stdscr.addch(term_h - 2, sx, divider)
        stdscr.addstr(term_h - 1, 0, status[:term_w - 1])
    except curses.error:
        pass

    stdscr.refresh()


def main(stdscr):
    curses.curs_set(0)
    stdscr.keypad(True)
    setup_colors()

    tiles, (px, py) = generate_dungeon()
    draw(stdscr, tiles, px, py)

    MOVE_KEYS = {
        ord('w'):         ( 0, -1),
        ord('a'):         (-1,  0),
        ord('s'):         ( 0,  1),
        ord('d'):         ( 1,  0),
        curses.KEY_UP:    ( 0, -1),
        curses.KEY_LEFT:  (-1,  0),
        curses.KEY_DOWN:  ( 0,  1),
        curses.KEY_RIGHT: ( 1,  0),
    }

    while True:
        key = stdscr.getch()

        if key in (ord('q'), ord('Q')):
            break

        if key in (ord('r'), ord('R')):
            tiles, (px, py) = generate_dungeon()

        if key in MOVE_KEYS:
            dx, dy = MOVE_KEYS[key]
            nx, ny = px + dx, py + dy
            if 0 <= nx < MAP_W and 0 <= ny < MAP_H and tiles[ny][nx] == FLOOR:
                px, py = nx, ny

        draw(stdscr, tiles, px, py)


if __name__ == '__main__':
    curses.wrapper(main)
