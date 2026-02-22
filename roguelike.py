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
    Item('Vibro-Knife',    'weapon', atk=1, char='/'),
    Item('Pulse Pistol',   'weapon', atk=3, char='/'),
    Item('Arc Rifle',      'weapon', atk=5, char='/'),
    Item('Ballistic Weave','armor',  dfn=1, char=']'),
    Item('Combat Exosuit', 'armor',  dfn=3, char=']'),
    Item('Aegis Plate',    'armor',  dfn=5, char=']'),
]

STATS            = ('body', 'reflex', 'mind', 'tech', 'presence')
STAT_LABELS      = ('Body', 'Reflex', 'Mind', 'Tech', 'Presence')
STAT_BASE        = 5
STAT_MIN         = 1
STAT_MAX         = 15
POINT_BUY_POINTS = 10

RACES = {
    'Human':   {'desc': 'Adaptable and resourceful. Bonuses across all stats.',
                'mods': {'body': 1, 'reflex': 1, 'mind': 1, 'tech': 1, 'presence': 1}},
    'Synth':   {'desc': 'Android intelligence. High Tech and Mind; weak social presence.',
                'mods': {'body': -1, 'reflex': 0, 'mind': 2, 'tech': 3, 'presence': -3}},
    'Voryn':   {'desc': 'Alien predator. High Reflex and Body; struggles with technology.',
                'mods': {'body': 2, 'reflex': 3, 'mind': -2, 'tech': -2, 'presence': 0}},
    'Augment': {'desc': 'Cybernetically enhanced human. Strong and technical; inhuman.',
                'mods': {'body': 2, 'reflex': 1, 'mind': -2, 'tech': 2, 'presence': -3}},
}

CLASSES = {
    'Soldier':  {'desc': 'Combat specialist. Excels in physical confrontation.',
                 'mods': {'body': 3, 'reflex': 2, 'mind': -1, 'tech': -1, 'presence': -1}},
    'Engineer': {'desc': 'Tech expert. Builds, repairs, and improvises solutions.',
                 'mods': {'body': -1, 'reflex': -1, 'mind': 2, 'tech': 3, 'presence': -1}},
    'Medic':    {'desc': 'Field medic and negotiator. Keeps the team alive.',
                 'mods': {'body': -2, 'reflex': -1, 'mind': 2, 'tech': 1, 'presence': 3}},
    'Hacker':   {'desc': 'Systems infiltrator. Exploits technology and environments.',
                 'mods': {'body': -2, 'reflex': 2, 'mind': 1, 'tech': 3, 'presence': -2}},
}


class Player:
    XP_PER_LEVEL = 100
    SLOTS = ('weapon', 'armor')

    def __init__(self, name='Unknown', race='Human', char_class='Soldier',
                 body=5, reflex=5, mind=5, tech=5, presence=5):
        self.name       = name
        self.race       = race
        self.char_class = char_class
        self.body       = body
        self.reflex     = reflex
        self.mind       = mind
        self.tech       = tech
        self.presence   = presence
        self.max_hp     = 20 + body * 2   # body=5 → 30 HP (matches old default)
        self.hp         = self.max_hp
        self.level      = 1
        self.xp         = 0
        self.inventory  = []
        self.equipment  = {'weapon': None, 'armor': None}

    @property
    def atk(self):
        weapon_bonus = sum(i.atk for i in self.equipment.values() if i)
        return 1 + max(0, (self.body - 5) // 2) + weapon_bonus
        # body=5 → 1 (same as before); body=7 → 2; body=10 → 3

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


class Enemy:
    def __init__(self, name, char, hp, atk, dfn, xp_reward):
        self.name      = name
        self.char      = char
        self.hp        = hp
        self.max_hp    = hp
        self.atk       = atk
        self.dfn       = dfn
        self.xp_reward = xp_reward


ENEMY_TEMPLATES = [
    {'name': 'Drone',   'char': 'd', 'hp': 8,  'atk': 3, 'dfn': 0, 'xp': 10},
    {'name': 'Sentry',  'char': 'S', 'hp': 15, 'atk': 5, 'dfn': 2, 'xp': 25},
    {'name': 'Stalker', 'char': 'X', 'hp': 22, 'atk': 7, 'dfn': 1, 'xp': 40},
]


def scatter_enemies(tiles, floor_num, n, exclude=()):
    floors = [(x, y) for y in range(MAP_H) for x in range(MAP_W)
              if tiles[y][x] == FLOOR and (x, y) not in exclude]
    positions = random.sample(floors, min(n, len(floors)))
    scale = 1 + (floor_num - 1) * 0.2   # +20% stats per floor
    result = {}
    for pos in positions:
        t = random.choice(ENEMY_TEMPLATES)
        result[pos] = Enemy(
            name=t['name'], char=t['char'],
            hp=max(1, int(t['hp'] * scale)),
            atk=max(1, int(t['atk'] * scale)),
            dfn=int(t['dfn'] * scale),
            xp_reward=int(t['xp'] * scale),
        )
    return result


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
    stair_up    = start if floor_num > 1 else None
    exclude_set = {stair_up, stair_down, start} - {None}
    return {
        'tiles':      tiles,
        'start':      start,
        'stair_up':   stair_up,
        'stair_down': stair_down,
        'items':      scatter_items(tiles, exclude=exclude_set),
        'enemies':    scatter_enemies(tiles, floor_num, n=3 + floor_num * 2, exclude=exclude_set),
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
COLOR_ENEMY  = 9  # red — hostile units


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
    curses.init_pair(COLOR_ENEMY,  curses.COLOR_RED,     -1)


def draw_panel(stdscr, player, col, rows, current_floor):
    """Draw the character stats panel starting at column `col`."""
    panel_attr  = curses.color_pair(COLOR_PANEL)
    header_attr = panel_attr | curses.A_BOLD

    hp_attr = (curses.color_pair(COLOR_HP_LOW) | curses.A_BOLD
               if player.hp <= player.max_hp // 4
               else panel_attr)

    lines = [
        ("CHARACTER",                                       header_attr),
        (None, 0),                                          # blank
        (player.name[:PANEL_W - 1],                        panel_attr),
        (f"{player.race} {player.char_class}"[:PANEL_W-1], panel_attr),
        (None, 0),                                          # blank
        (f"Floor: {current_floor}",                        panel_attr),
        (f"HP:  {player.hp:>3} / {player.max_hp:<3}",     hp_attr),
        (f"LVL: {player.level}",                           panel_attr),
        (f"XP:  {player.xp:>3} / {player.xp_next:<3}",   panel_attr),
        (f"ATK: {player.atk}",                             panel_attr),
        (f"DEF: {player.dfn}",                             panel_attr),
        (None, 0),                                          # blank
        ("[I] Equipment",                                   panel_attr),
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
         stair_up, stair_down, current_floor, enemies=None, msg=''):
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
                elif enemies and (mx, my) in enemies:
                    ch   = enemies[(mx, my)].char
                    attr = curses.color_pair(COLOR_ENEMY) | curses.A_BOLD
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
    status_text = msg if msg else " WASD/Arrows:move  >/< stairs  I:equip  R:reset  Q:quit"
    divider = curses.ACS_HLINE
    try:
        for sx in range(term_w - 1):
            stdscr.addch(term_h - 2, sx, divider)
        stdscr.addstr(term_h - 1, 0, status_text[: term_w - 1])
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


def show_character_creation(stdscr):
    """Multi-step character creation wizard. Returns a fully configured Player."""
    panel_attr  = curses.color_pair(COLOR_PANEL)
    header_attr = panel_attr | curses.A_BOLD
    sel_attr    = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD

    race_names  = list(RACES.keys())
    class_names = list(CLASSES.keys())

    def clr():
        stdscr.erase()

    def safe_addstr(row, col, text, attr=0):
        try:
            stdscr.addstr(row, col, text, attr)
        except curses.error:
            pass

    def compute_base(race_name, class_name):
        """Apply race + class mods to STAT_BASE, clamped to STAT_MIN."""
        rmods = RACES[race_name]['mods']
        cmods = CLASSES[class_name]['mods']
        result = {}
        for s in STATS:
            val = STAT_BASE + rmods.get(s, 0) + cmods.get(s, 0)
            result[s] = max(STAT_MIN, val)
        return result

    def mod_str(mods):
        parts = []
        for s, label in zip(STATS, STAT_LABELS):
            v = mods.get(s, 0)
            if v != 0:
                parts.append(f"{label[0]}{v:+d}")
        return '  '.join(parts) if parts else '(no modifiers)'

    step       = 0
    name       = ''
    race_idx   = 0
    class_idx  = 0
    alloc      = {s: 0 for s in STATS}
    stat_cursor = 0  # index into STATS for point-buy step

    while True:
        term_h, term_w = stdscr.getmaxyx()
        clr()

        # ── Step 0: Name ────────────────────────────────────────────────────
        if step == 0:
            title = "CHARACTER CREATION — Name"
            safe_addstr(1, 2, title, header_attr)
            safe_addstr(3, 2, "Enter your character's name (max 20 chars):", panel_attr)
            cursor_name = name + '_'
            safe_addstr(5, 4, cursor_name[:term_w - 5], sel_attr)
            safe_addstr(7, 2, "Press Enter to continue.", panel_attr)
            stdscr.refresh()

            key = stdscr.getch()
            if key in (curses.KEY_ENTER, 10, 13):
                if name.strip():
                    step = 1
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                name = name[:-1]
            elif 32 <= key <= 126 and len(name) < 20:
                name += chr(key)

        # ── Step 1: Race ─────────────────────────────────────────────────────
        elif step == 1:
            title = "CHARACTER CREATION — Race"
            safe_addstr(1, 2, title, header_attr)
            safe_addstr(3, 2, "W/S: navigate   Enter: select   Esc: back", panel_attr)

            for i, rname in enumerate(race_names):
                row    = 5 + i * 3
                rdata  = RACES[rname]
                prefix = '> ' if i == race_idx else '  '
                attr   = sel_attr if i == race_idx else panel_attr
                safe_addstr(row,     2, f"{prefix}{rname}", attr)
                safe_addstr(row + 1, 4, rdata['desc'][:term_w - 6], panel_attr)
                safe_addstr(row + 2, 4, mod_str(rdata['mods']), panel_attr)

            stdscr.refresh()
            key = stdscr.getch()

            if key == 27:
                step = 0
            elif key in (curses.KEY_UP, ord('w'), ord('W')):
                race_idx = max(0, race_idx - 1)
            elif key in (curses.KEY_DOWN, ord('s'), ord('S')):
                race_idx = min(len(race_names) - 1, race_idx + 1)
            elif key in (curses.KEY_ENTER, 10, 13):
                alloc = {s: 0 for s in STATS}   # reset alloc on race change
                step  = 2

        # ── Step 2: Class ────────────────────────────────────────────────────
        elif step == 2:
            title = "CHARACTER CREATION — Class"
            safe_addstr(1, 2, title, header_attr)
            safe_addstr(3, 2, "W/S: navigate   Enter: select   Esc: back", panel_attr)

            for i, cname in enumerate(class_names):
                row    = 5 + i * 3
                cdata  = CLASSES[cname]
                prefix = '> ' if i == class_idx else '  '
                attr   = sel_attr if i == class_idx else panel_attr
                safe_addstr(row,     2, f"{prefix}{cname}", attr)
                safe_addstr(row + 1, 4, cdata['desc'][:term_w - 6], panel_attr)
                safe_addstr(row + 2, 4, mod_str(cdata['mods']), panel_attr)

            stdscr.refresh()
            key = stdscr.getch()

            if key == 27:
                step = 1
            elif key in (curses.KEY_UP, ord('w'), ord('W')):
                class_idx = max(0, class_idx - 1)
            elif key in (curses.KEY_DOWN, ord('s'), ord('S')):
                class_idx = min(len(class_names) - 1, class_idx + 1)
            elif key in (curses.KEY_ENTER, 10, 13):
                alloc = {s: 0 for s in STATS}   # reset alloc on class change
                step  = 3

        # ── Step 3: Point Buy ─────────────────────────────────────────────────
        elif step == 3:
            rname   = race_names[race_idx]
            cname   = class_names[class_idx]
            base    = compute_base(rname, cname)
            remain  = POINT_BUY_POINTS - sum(alloc.values())

            title = "CHARACTER CREATION — Distribute Points"
            safe_addstr(1, 2, title, header_attr)
            safe_addstr(3, 2,
                f"Points remaining: {remain}   "
                "W/S: select stat   A/D: add/remove   Enter: confirm   Esc: back",
                panel_attr)

            for i, (s, label) in enumerate(zip(STATS, STAT_LABELS)):
                row = 5 + i * 2
                val = base[s] + alloc[s]
                bar = '█' * val + '░' * (STAT_MAX - val)
                attr = sel_attr if i == stat_cursor else panel_attr
                safe_addstr(row,     2, f"{'> ' if i == stat_cursor else '  '}{label:<10} {val:>2}  {bar[:STAT_MAX]}", attr)

            safe_addstr(5 + len(STATS) * 2 + 1, 2,
                f"Max HP will be: {20 + (base['body'] + alloc['body']) * 2}",
                panel_attr)

            stdscr.refresh()
            key = stdscr.getch()

            if key == 27:
                step = 2
            elif key in (curses.KEY_UP, ord('w'), ord('W')):
                stat_cursor = max(0, stat_cursor - 1)
            elif key in (curses.KEY_DOWN, ord('s'), ord('S')):
                stat_cursor = min(len(STATS) - 1, stat_cursor + 1)
            elif key in (curses.KEY_RIGHT, ord('d'), ord('D')):
                s   = STATS[stat_cursor]
                val = base[s] + alloc[s]
                if remain > 0 and val < STAT_MAX:
                    alloc[s] += 1
            elif key in (curses.KEY_LEFT, ord('a'), ord('A')):
                s = STATS[stat_cursor]
                if alloc[s] > 0:
                    alloc[s] -= 1
            elif key in (curses.KEY_ENTER, 10, 13):
                step = 4

        # ── Step 4: Confirm ────────────────────────────────────────────────────
        elif step == 4:
            rname  = race_names[race_idx]
            cname  = class_names[class_idx]
            base   = compute_base(rname, cname)
            final  = {s: base[s] + alloc[s] for s in STATS}
            max_hp = 20 + final['body'] * 2

            title = "CHARACTER CREATION — Confirm"
            safe_addstr(1, 2, title, header_attr)
            safe_addstr(3, 2, f"Name:   {name}", panel_attr)
            safe_addstr(4, 2, f"Race:   {rname}", panel_attr)
            safe_addstr(5, 2, f"Class:  {cname}", panel_attr)
            safe_addstr(7, 2, "STATS", header_attr)

            for i, (s, label) in enumerate(zip(STATS, STAT_LABELS)):
                safe_addstr(8 + i, 4, f"{label:<10} {final[s]:>2}", panel_attr)

            safe_addstr(8 + len(STATS) + 1, 2, f"Max HP: {max_hp}", panel_attr)
            safe_addstr(8 + len(STATS) + 3, 2, "Enter: begin game   Esc: back", panel_attr)

            stdscr.refresh()
            key = stdscr.getch()

            if key == 27:
                step = 3
            elif key in (curses.KEY_ENTER, 10, 13):
                return Player(
                    name=name,
                    race=rname,
                    char_class=cname,
                    body=final['body'],
                    reflex=final['reflex'],
                    mind=final['mind'],
                    tech=final['tech'],
                    presence=final['presence'],
                )


def enemy_turn(enemies, tiles, px, py, visible, player):
    """Move and attack with every enemy. Returns list of combat message strings."""
    msgs = []
    for (ex, ey), enemy in list(enemies.items()):
        if (ex, ey) in visible:
            ddx = (1 if px > ex else -1) if px != ex else 0
            ddy = (1 if py > ey else -1) if py != ey else 0
            for ndx, ndy in [(ddx, ddy), (ddx, 0), (0, ddy)]:
                if ndx == 0 and ndy == 0:
                    continue
                nx, ny = ex + ndx, ey + ndy
                if (nx, ny) == (px, py):
                    dmg = max(1, enemy.atk - player.dfn)
                    player.hp -= dmg
                    msgs.append(f"{enemy.name} hits you for {dmg}!")
                    break
                if (0 <= nx < MAP_W and 0 <= ny < MAP_H
                        and tiles[ny][nx] == FLOOR
                        and (nx, ny) not in enemies):
                    enemies[(nx, ny)] = enemy
                    del enemies[(ex, ey)]
                    break
        else:
            dirs = [(0, 1), (0, -1), (1, 0), (-1, 0)]
            random.shuffle(dirs)
            for ndx, ndy in dirs:
                nx, ny = ex + ndx, ey + ndy
                if (0 <= nx < MAP_W and 0 <= ny < MAP_H
                        and tiles[ny][nx] == FLOOR
                        and (nx, ny) not in enemies
                        and (nx, ny) != (px, py)):
                    enemies[(nx, ny)] = enemy
                    del enemies[(ex, ey)]
                    break
    return msgs


def show_game_over(stdscr, player, floor_reached):
    """Show game-over screen. Returns True to restart, False to quit."""
    panel_attr  = curses.color_pair(COLOR_PANEL)
    header_attr = curses.color_pair(COLOR_HP_LOW) | curses.A_BOLD

    while True:
        term_h, term_w = stdscr.getmaxyx()
        stdscr.erase()

        lines = [
            ("* YOU DIED *",                         header_attr),
            ("",                                     0),
            (f"Name:   {player.name}",               panel_attr),
            (f"Race:   {player.race}",               panel_attr),
            (f"Class:  {player.char_class}",         panel_attr),
            ("",                                     0),
            (f"Floor reached: {floor_reached}",      panel_attr),
            (f"Level:         {player.level}",       panel_attr),
            ("",                                     0),
            ("R: new character    Q: quit",          panel_attr),
        ]

        start_row = max(0, (term_h - len(lines)) // 2)
        for i, (text, attr) in enumerate(lines):
            col = max(0, (term_w - len(text)) // 2)
            try:
                stdscr.addstr(start_row + i, col, text, attr)
            except curses.error:
                pass

        stdscr.refresh()
        key = stdscr.getch()

        if key in (ord('r'), ord('R')):
            return True
        if key in (ord('q'), ord('Q')):
            return False


def main(stdscr):
    curses.curs_set(0)
    stdscr.keypad(True)
    setup_colors()

    player = show_character_creation(stdscr)
    current_floor = 1
    floors        = {}
    floor_data    = make_floor(1)
    floors[1]     = floor_data
    tiles         = floor_data['tiles']
    px, py        = floor_data['start']
    items_on_map  = floor_data['items']
    enemies_on_map = floor_data['enemies']
    stair_up      = floor_data['stair_up']
    stair_down    = floor_data['stair_down']
    explored      = floor_data['explored']
    msg      = ''
    visible  = compute_fov(tiles, px, py)
    explored |= visible
    draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
         stair_up, stair_down, current_floor, enemies_on_map, msg)

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
            current_floor  = 1
            floors         = {}
            floor_data     = make_floor(1)
            floors[1]      = floor_data
            tiles          = floor_data['tiles']
            px, py         = floor_data['start']
            items_on_map   = floor_data['items']
            enemies_on_map = floor_data['enemies']
            stair_up       = floor_data['stair_up']
            stair_down     = floor_data['stair_down']
            explored       = floor_data['explored']
            msg            = ''

        if key in (ord('i'), ord('I')):
            show_equipment_screen(stdscr, player)

        if key in MOVE_KEYS:
            dx, dy = MOVE_KEYS[key]
            nx, ny = px + dx, py + dy
            if (nx, ny) in enemies_on_map:
                # Bump attack
                enemy = enemies_on_map[(nx, ny)]
                dmg = max(1, player.atk - enemy.dfn)
                enemy.hp -= dmg
                msg = f"You hit {enemy.name} for {dmg}."
                if enemy.hp <= 0:
                    del enemies_on_map[(nx, ny)]
                    player.gain_xp(enemy.xp_reward)
                    msg += f" {enemy.name} destroyed! +{enemy.xp_reward} XP"
                else:
                    edm = max(1, enemy.atk - player.dfn)
                    player.hp -= edm
                    msg += f" {enemy.name} hits back for {edm}."
            elif 0 <= nx < MAP_W and 0 <= ny < MAP_H and tiles[ny][nx] == FLOOR:
                px, py = nx, ny
                player.gain_xp(1)
                # Auto-pickup item on tile
                if (px, py) in items_on_map:
                    player.pickup(items_on_map.pop((px, py)))
                msg = ''

                # Stair traversal
                if (px, py) == stair_down:
                    current_floor += 1
                    if current_floor not in floors:
                        floors[current_floor] = make_floor(current_floor)
                    floor_data     = floors[current_floor]
                    tiles          = floor_data['tiles']
                    px, py         = floor_data['start']
                    items_on_map   = floor_data['items']
                    enemies_on_map = floor_data['enemies']
                    stair_up       = floor_data['stair_up']
                    stair_down     = floor_data['stair_down']
                    explored       = floor_data['explored']
                elif stair_up and (px, py) == stair_up:
                    current_floor -= 1
                    floor_data     = floors[current_floor]
                    tiles          = floor_data['tiles']
                    px, py         = floor_data['stair_down']
                    items_on_map   = floor_data['items']
                    enemies_on_map = floor_data['enemies']
                    stair_up       = floor_data['stair_up']
                    stair_down     = floor_data['stair_down']
                    explored       = floor_data['explored']

            # Enemy turn after any player action
            e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player)
            if e_msgs:
                suffix = '  ' + ' '.join(e_msgs)
                msg = (msg + suffix).strip() if msg else ' '.join(e_msgs)

        visible   = compute_fov(tiles, px, py)
        explored |= visible

        # Death check
        if player.hp <= 0:
            player.hp = 0
            draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
                 stair_up, stair_down, current_floor, enemies_on_map, msg)
            if show_game_over(stdscr, player, current_floor):
                player         = show_character_creation(stdscr)
                current_floor  = 1
                floors         = {}
                floor_data     = make_floor(1)
                floors[1]      = floor_data
                tiles          = floor_data['tiles']
                px, py         = floor_data['start']
                items_on_map   = floor_data['items']
                enemies_on_map = floor_data['enemies']
                stair_up       = floor_data['stair_up']
                stair_down     = floor_data['stair_down']
                explored       = floor_data['explored']
                msg            = ''
                visible        = compute_fov(tiles, px, py)
                explored      |= visible
            else:
                break

        draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
             stair_up, stair_down, current_floor, enemies_on_map, msg)


if __name__ == '__main__':
    curses.wrapper(main)
