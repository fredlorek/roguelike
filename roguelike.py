#!/usr/bin/env python3
"""Simple terminal roguelike using curses."""

import copy
import curses
import random

MAP_W   = 80
MAP_H   = 40
WALL    = '#'
FLOOR   = '.'
PLAYER  = '@'
PANEL_W = 20  # width of the right-hand stats panel (including border)


class Room:
    def __init__(self, x, y, w, h):
        self.x1, self.y1 = x, y
        self.x2, self.y2 = x + w, y + h

    def center(self):
        return (self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2

    def intersects(self, other, pad=1):
        return (self.x1 - pad < other.x2 and self.x2 + pad > other.x1 and
                self.y1 - pad < other.y2 and self.y2 + pad > other.y1)


class Item:
    def __init__(self, name, slot, atk=0, dfn=0, char='!'):
        self.name = name   # display name
        self.slot = slot   # 'weapon' or 'armor'
        self.atk  = atk
        self.dfn  = dfn
        self.char = char   # glyph on map

    def stat_str(self):
        parts = []
        if self.atk: parts.append(f'+{self.atk} ATK')
        if self.dfn: parts.append(f'+{self.dfn} DEF')
        return '  '.join(parts)


ITEM_TEMPLATES = [
    Item('Dagger',    'weapon', atk=1, char='/'),
    Item('Sword',     'weapon', atk=3, char='/'),
    Item('Axe',       'weapon', atk=5, char='/'),
    Item('Leather',   'armor',  dfn=1, char=']'),
    Item('Chainmail', 'armor',  dfn=3, char=']'),
    Item('Plate',     'armor',  dfn=5, char=']'),
]


class Player:
    XP_PER_LEVEL = 100
    SLOTS = ('weapon', 'armor')

    def __init__(self):
        self.hp        = 30
        self.max_hp    = 30
        self.level     = 1
        self.xp        = 0
        self.inventory = []
        self.equipment = {'weapon': None, 'armor': None}

    @property
    def atk(self):
        return 1 + sum(i.atk for i in self.equipment.values() if i)

    @property
    def dfn(self):
        return sum(i.dfn for i in self.equipment.values() if i)

    @property
    def xp_next(self):
        return self.XP_PER_LEVEL * self.level

    def gain_xp(self, amount):
        self.xp += amount
        while self.xp >= self.xp_next:
            self.xp -= self.xp_next
            self.level  += 1
            self.max_hp += 5
            self.hp      = self.max_hp  # full heal on level-up

    def pickup(self, item):
        self.inventory.append(item)

    def equip(self, item):           # item must be in inventory
        old = self.equipment[item.slot]
        self.equipment[item.slot] = item
        self.inventory.remove(item)
        if old:
            self.inventory.append(old)

    def unequip(self, slot):
        item = self.equipment[slot]
        if item:
            self.inventory.append(item)
            self.equipment[slot] = None


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

    return tiles, rooms


def scatter_items(tiles, n=6, exclude=()):
    floors = [(x, y) for y in range(MAP_H) for x in range(MAP_W)
              if tiles[y][x] == FLOOR and (x, y) not in exclude]
    positions = random.sample(floors, min(n, len(floors)))
    return {pos: copy.copy(random.choice(ITEM_TEMPLATES)) for pos in positions}


def make_floor(floor_num):
    tiles, rooms = generate_dungeon()
    if rooms:
        start      = rooms[0].center()
        stair_down = rooms[-1].center()
    else:
        start = stair_down = (MAP_W // 2, MAP_H // 2)
    stair_up = start if floor_num > 1 else None
    exclude  = {stair_up, stair_down} - {None}
    return {
        'tiles':      tiles,
        'start':      start,
        'stair_up':   stair_up,
        'stair_down': stair_down,
        'items':      scatter_items(tiles, exclude=exclude),
        'explored':   set(),
    }


FOV_RADIUS = 8


def _bresenham(x0, y0, x1, y1):
    """Yield each integer (x, y) on the line from (x0, y0) to (x1, y1)."""
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0  += sx
        if e2 < dx:
            err += dx
            y0  += sy


def compute_fov(tiles, px, py, radius=FOV_RADIUS):
    """Return the set of (x, y) tiles visible from (px, py)."""
    visible = set()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius:
                continue
            tx, ty = px + dx, py + dy
            if not (0 <= tx < MAP_W and 0 <= ty < MAP_H):
                continue
            for rx, ry in _bresenham(px, py, tx, ty):
                if not (0 <= rx < MAP_W and 0 <= ry < MAP_H):
                    break
                visible.add((rx, ry))
                if tiles[ry][rx] == WALL:
                    break  # wall is visible but blocks further sight
    return visible


# Color pair indices
COLOR_WALL   = 1
COLOR_FLOOR  = 2
COLOR_PLAYER = 3
COLOR_PANEL  = 4
COLOR_HP_LOW = 5
COLOR_DARK   = 6  # explored but not currently visible
COLOR_ITEM   = 7  # items on the map (green)
COLOR_STAIR  = 8  # stairs (magenta)


def setup_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(COLOR_WALL,   curses.COLOR_WHITE,  -1)
    curses.init_pair(COLOR_FLOOR,  curses.COLOR_BLACK,  -1)
    curses.init_pair(COLOR_PLAYER, curses.COLOR_YELLOW, -1)
    curses.init_pair(COLOR_PANEL,  curses.COLOR_CYAN,   -1)
    curses.init_pair(COLOR_HP_LOW, curses.COLOR_RED,    -1)
    curses.init_pair(COLOR_DARK,   curses.COLOR_WHITE,  -1)
    curses.init_pair(COLOR_ITEM,   curses.COLOR_GREEN,   -1)
    curses.init_pair(COLOR_STAIR,  curses.COLOR_MAGENTA, -1)


def draw_panel(stdscr, player, col, rows, current_floor):
    """Draw the character stats panel starting at column `col`."""
    panel_attr  = curses.color_pair(COLOR_PANEL)
    header_attr = panel_attr | curses.A_BOLD

    hp_attr = (curses.color_pair(COLOR_HP_LOW) | curses.A_BOLD
               if player.hp <= player.max_hp // 4
               else panel_attr)

    lines = [
        ("CHARACTER", header_attr),
        (None, 0),                                             # blank
        (f"Floor: {current_floor}", panel_attr),
        (f"HP:  {player.hp:>3} / {player.max_hp:<3}", hp_attr),
        (f"LVL: {player.level}", panel_attr),
        (f"XP:  {player.xp:>3} / {player.xp_next:<3}", panel_attr),
        (f"ATK: {player.atk}", panel_attr),
        (f"DEF: {player.dfn}", panel_attr),
        (None, 0),                                             # blank
        ("[I] Equipment", panel_attr),
    ]

    for row in range(rows):
        try:
            # Vertical divider
            stdscr.addch(row, col - 1, curses.ACS_VLINE, panel_attr)
        except curses.error:
            pass

        if row < len(lines):
            text, attr = lines[row]
            if text is None:
                continue
            try:
                stdscr.addstr(row, col, text[: PANEL_W - 1], attr)
            except curses.error:
                pass


def draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
         stair_up, stair_down, current_floor):
    term_h, term_w = stdscr.getmaxyx()
    view_h  = term_h - 2              # reserve two rows for the status bar
    map_w   = term_w - PANEL_W - 1   # columns available for the map

    # Center camera on player, clamped to map bounds
    cam_x = max(0, min(px - map_w  // 2, max(0, MAP_W - map_w)))
    cam_y = max(0, min(py - view_h // 2, max(0, MAP_H - view_h)))

    stdscr.erase()

    # --- Map area ---
    for sy in range(view_h):
        my = sy + cam_y
        if my >= MAP_H:
            break
        for sx in range(map_w):
            mx = sx + cam_x
            if mx >= MAP_W:
                break

            if (mx, my) not in explored:
                continue  # never seen — leave blank

            if mx == px and my == py:
                ch   = PLAYER
                attr = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD
            elif (mx, my) in visible:
                if tiles[my][mx] == WALL:
                    ch   = WALL
                    attr = curses.color_pair(COLOR_WALL)
                elif (mx, my) == stair_down:
                    ch   = '>'
                    attr = curses.color_pair(COLOR_STAIR) | curses.A_BOLD
                elif stair_up and (mx, my) == stair_up:
                    ch   = '<'
                    attr = curses.color_pair(COLOR_STAIR) | curses.A_BOLD
                elif (mx, my) in items_on_map:
                    ch   = items_on_map[(mx, my)].char
                    attr = curses.color_pair(COLOR_ITEM) | curses.A_BOLD
                else:
                    ch   = FLOOR
                    attr = curses.color_pair(COLOR_FLOOR) | curses.A_DIM
            else:
                # Explored but out of sight — show stairs as permanent features
                if (mx, my) == stair_down:
                    ch   = '>'
                    attr = curses.color_pair(COLOR_STAIR) | curses.A_DIM
                elif stair_up and (mx, my) == stair_up:
                    ch   = '<'
                    attr = curses.color_pair(COLOR_STAIR) | curses.A_DIM
                else:
                    ch   = tiles[my][mx]
                    attr = curses.color_pair(COLOR_DARK) | curses.A_DIM

            try:
                stdscr.addch(sy, sx, ch, attr)
            except curses.error:
                pass

    # --- Stats panel ---
    panel_col = term_w - PANEL_W
    draw_panel(stdscr, player, panel_col, view_h, current_floor)

    # --- Status bar ---
    status  = " WASD/Arrows: move  |  >/< : stairs  |  I: equipment  |  R: new dungeon  |  Q: quit "
    divider = curses.ACS_HLINE
    try:
        for sx in range(term_w - 1):
            stdscr.addch(term_h - 2, sx, divider)
        stdscr.addstr(term_h - 1, 0, status[: term_w - 1])
    except curses.error:
        pass

    stdscr.refresh()


def show_equipment_screen(stdscr, player):
    """Modal overlay for managing inventory and equipment."""
    BOX_W = 50

    while True:
        term_h, term_w = stdscr.getmaxyx()

        # Build selectable entries: each is (label, action_type, payload)
        # action_type: 'equip' (inventory item) or 'unequip' (slot name)
        entries = []

        for slot in Player.SLOTS:
            item = player.equipment[slot]
            if item:
                entries.append(('unequip', slot))
            else:
                entries.append(None)  # not selectable

        for item in player.inventory:
            entries.append(('equip', item))

        # Flatten: section headers are non-selectable, item rows are selectable
        # We track which flat row index corresponds to which entry index
        rows_content = []   # list of (text, selectable_idx_or_None)

        rows_content.append(("  EQUIPPED", None))
        rows_content.append(("", None))
        for i, slot in enumerate(Player.SLOTS):
            item = player.equipment[slot]
            if item:
                label = f"  {slot.capitalize():<8}: {item.name} ({item.stat_str()})"
                rows_content.append((label, i))
            else:
                label = f"  {slot.capitalize():<8}: (empty)"
                rows_content.append((label, None))
        rows_content.append(("", None))
        rows_content.append(("  INVENTORY", None))
        rows_content.append(("", None))

        base_inv = len(Player.SLOTS)  # offset into entries for inventory items
        if player.inventory:
            for j, item in enumerate(player.inventory):
                label = f"  {item.name} [{item.slot}] {item.stat_str()}"
                rows_content.append((label, base_inv + j))
        else:
            rows_content.append(("  (empty)", None))

        rows_content.append(("", None))
        rows_content.append(("  Enter: equip/unequip  |  Esc/I: close", None))

        # Collect selectable row indices (flat row positions that have an entry)
        selectable_rows = [i for i, (_, eidx) in enumerate(rows_content) if eidx is not None]

        # cur_sel is index into selectable_rows
        if not hasattr(show_equipment_screen, '_cursor'):
            show_equipment_screen._cursor = 0
        cur_sel = getattr(show_equipment_screen, '_cursor', 0)
        cur_sel = max(0, min(cur_sel, len(selectable_rows) - 1)) if selectable_rows else 0

        # Layout
        content_h = len(rows_content) + 2  # +2 for top/bottom border
        box_h     = content_h
        box_y     = max(0, (term_h - box_h) // 2)
        box_x     = max(0, (term_w - BOX_W) // 2)

        # Draw box background
        panel_attr = curses.color_pair(COLOR_PANEL)
        bold_attr  = panel_attr | curses.A_BOLD

        # Top border
        try:
            stdscr.addch(box_y, box_x, curses.ACS_ULCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(box_y, box_x + BOX_W - 1, curses.ACS_URCORNER, panel_attr)
        except curses.error:
            pass

        # Middle rows
        for ri, (text, eidx) in enumerate(rows_content):
            row = box_y + 1 + ri
            try:
                stdscr.addch(row, box_x, curses.ACS_VLINE, panel_attr)
                stdscr.addch(row, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
            except curses.error:
                pass

            # Clear interior
            inner_w = BOX_W - 2
            try:
                stdscr.addstr(row, box_x + 1, ' ' * inner_w)
            except curses.error:
                pass

            # Determine if this flat row is the selected selectable row
            is_selected = (selectable_rows and
                           ri == selectable_rows[cur_sel])

            if is_selected:
                display = ('> ' + text.lstrip())[:inner_w]
                attr = bold_attr
            else:
                display = text[:inner_w]
                attr = panel_attr

            try:
                stdscr.addstr(row, box_x + 1, display, attr)
            except curses.error:
                pass

        # Bottom border
        bot_row = box_y + 1 + len(rows_content)
        try:
            stdscr.addch(bot_row, box_x, curses.ACS_LLCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(bot_row, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(bot_row, box_x + BOX_W - 1, curses.ACS_LRCORNER, panel_attr)
        except curses.error:
            pass

        stdscr.refresh()

        key = stdscr.getch()

        if key in (27, ord('i'), ord('I')):          # Esc or I to close
            show_equipment_screen._cursor = cur_sel
            break

        if key in (curses.KEY_UP, ord('w'), ord('W')):
            if selectable_rows:
                cur_sel = max(0, cur_sel - 1)
            show_equipment_screen._cursor = cur_sel

        elif key in (curses.KEY_DOWN, ord('s'), ord('S')):
            if selectable_rows:
                cur_sel = min(len(selectable_rows) - 1, cur_sel + 1)
            show_equipment_screen._cursor = cur_sel

        elif key in (curses.KEY_ENTER, 10, 13):
            if selectable_rows:
                flat_row_idx = selectable_rows[cur_sel]
                _, eidx = rows_content[flat_row_idx]
                if eidx is not None:
                    action, payload = entries[eidx]
                    if action == 'equip':
                        player.equip(payload)
                    elif action == 'unequip':
                        player.unequip(payload)
                    # Reset cursor safely after inventory change
                    show_equipment_screen._cursor = 0


def main(stdscr):
    curses.curs_set(0)
    stdscr.keypad(True)
    setup_colors()

    player = Player()
    current_floor = 1
    floors        = {}
    floor_data    = make_floor(1)
    floors[1]     = floor_data
    tiles         = floor_data['tiles']
    px, py        = floor_data['start']
    items_on_map  = floor_data['items']
    stair_up      = floor_data['stair_up']
    stair_down    = floor_data['stair_down']
    explored      = floor_data['explored']
    visible  = compute_fov(tiles, px, py)
    explored |= visible
    draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
         stair_up, stair_down, current_floor)

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
            current_floor = 1
            floors        = {}
            floor_data    = make_floor(1)
            floors[1]     = floor_data
            tiles         = floor_data['tiles']
            px, py        = floor_data['start']
            items_on_map  = floor_data['items']
            stair_up      = floor_data['stair_up']
            stair_down    = floor_data['stair_down']
            explored      = floor_data['explored']

        if key in (ord('i'), ord('I')):
            show_equipment_screen(stdscr, player)

        if key in MOVE_KEYS:
            dx, dy = MOVE_KEYS[key]
            nx, ny = px + dx, py + dy
            if 0 <= nx < MAP_W and 0 <= ny < MAP_H and tiles[ny][nx] == FLOOR:
                px, py = nx, ny
                player.gain_xp(1)
                # Auto-pickup item on tile
                if (px, py) in items_on_map:
                    player.pickup(items_on_map.pop((px, py)))

                # Stair traversal
                if (px, py) == stair_down:
                    current_floor += 1
                    if current_floor not in floors:
                        floors[current_floor] = make_floor(current_floor)
                    floor_data   = floors[current_floor]
                    tiles        = floor_data['tiles']
                    px, py       = floor_data['start']
                    items_on_map = floor_data['items']
                    stair_up     = floor_data['stair_up']
                    stair_down   = floor_data['stair_down']
                    explored     = floor_data['explored']
                elif stair_up and (px, py) == stair_up:
                    current_floor -= 1
                    floor_data   = floors[current_floor]
                    tiles        = floor_data['tiles']
                    px, py       = floor_data['stair_down']
                    items_on_map = floor_data['items']
                    stair_up     = floor_data['stair_up']
                    stair_down   = floor_data['stair_down']
                    explored     = floor_data['explored']

        visible   = compute_fov(tiles, px, py)
        explored |= visible
        draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
             stair_up, stair_down, current_floor)


if __name__ == '__main__':
    curses.wrapper(main)
