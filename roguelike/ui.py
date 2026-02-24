"""All curses rendering and UI functions."""

import collections
import copy
import curses
import random

from .constants import *
from .entities import Player, Terminal
from .world import apply_effect, compute_fov, make_floor, get_theme, _bresenham
from .data import ITEM_TEMPLATES, LORE_POOL, SHOP_STOCK, WIN_TERMINAL, RACES, CLASSES
from .lore_gen import generate_terminal


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
    curses.init_pair(COLOR_TARGET,   curses.COLOR_YELLOW,  -1)
    curses.init_pair(COLOR_TERMINAL, curses.COLOR_CYAN,    -1)
    curses.init_pair(COLOR_WALL_2,   curses.COLOR_YELLOW,  -1)
    curses.init_pair(COLOR_WALL_3,   curses.COLOR_RED,     -1)
    curses.init_pair(COLOR_WALL_4,   curses.COLOR_GREEN,   -1)
    curses.init_pair(COLOR_SPECIAL,      curses.COLOR_BLUE,    -1)
    curses.init_pair(COLOR_ENEMY_RANGE,  curses.COLOR_CYAN,    -1)
    curses.init_pair(COLOR_ENEMY_FAST,   curses.COLOR_YELLOW,  -1)
    curses.init_pair(COLOR_ENEMY_BRUTE,  curses.COLOR_WHITE,   -1)
    curses.init_pair(COLOR_ENEMY_EXPL,   curses.COLOR_MAGENTA, -1)
    curses.init_pair(COLOR_HAZARD,       curses.COLOR_RED,     -1)
    curses.init_pair(COLOR_OV_OPEN,      curses.COLOR_GREEN,   -1)
    curses.init_pair(COLOR_OV_FOREST,    curses.COLOR_GREEN,   -1)


def draw_panel(stdscr, player, col, rows, current_floor, max_floor=MAX_FLOOR, floor_name=None, corruption=0):
    """Draw the character stats panel starting at column `col`."""
    panel_attr  = curses.color_pair(COLOR_PANEL)
    header_attr = panel_attr | curses.A_BOLD

    hp_attr = (curses.color_pair(COLOR_HP_LOW) | curses.A_BOLD
               if player.hp <= player.max_hp // 4
               else panel_attr)

    if floor_name is None:
        floor_name = get_theme(current_floor)['name']

    lines = [
        ("CHARACTER",                                       header_attr),
        (None, 0),                                          # blank
        (player.name[:PANEL_W - 1],                        panel_attr),
        (f"{player.race} {player.char_class}"[:PANEL_W-1], panel_attr),
        (None, 0),                                          # blank
        (f"Floor: {current_floor}/{max_floor}",            panel_attr),
        (floor_name[:PANEL_W - 1],                         panel_attr),
        (f"HP:  {player.hp:>3} / {player.max_hp:<3}",     hp_attr),
        (f"LVL: {player.level}",                           panel_attr),
        (f"XP:  {player.xp:>3} / {player.xp_next:<3}",   panel_attr),
        (f"ATK: {player.atk}",                             panel_attr),
        (f"DEF: {player.dfn}",                             panel_attr),
        (f"DODGE: {player.dodge_chance}%",                 panel_attr),
        (f"CR:   {player.credits}",                        panel_attr),
        (f"Fuel: {player.fuel}",                           panel_attr),
        (None, 0),                                          # blank
        ("[I]Equip [K]Skills [X]Tool",                     panel_attr),
    ]

    if player.skill_points:
        lines.insert(-1, (f"SP:   {player.skill_points}",
                          curses.color_pair(COLOR_PLAYER) | curses.A_BOLD))

    tool = player.equipment.get('tool')
    if tool:
        tool_text = f"Tool: {tool.name} [{tool.charges}/{tool.max_charges}]"
        lines.insert(-1, (tool_text[:PANEL_W - 1], curses.color_pair(COLOR_ITEM)))

    if corruption > 0:
        bar_w  = 10
        filled = min(bar_w, int(bar_w * corruption / CORRUPTION_MAX))
        bar    = '\u2588' * filled + '\u2591' * (bar_w - filled)
        sig_cp = (COLOR_ITEM   if corruption < 25 else
                  COLOR_TARGET if corruption < 50 else
                  COLOR_HP_LOW if corruption < 75 else
                  COLOR_ENEMY)
        lines.insert(-1, (f"Sig:{bar}{corruption:3d}%",
                          curses.color_pair(sig_cp) | curses.A_BOLD))

    if player.active_effects:
        abbr = {'poison': 'Psn', 'burn': 'Brn', 'stun': 'Stn',
                'repair': 'Rep', 'stim': 'Stm'}
        parts = [f"{abbr.get(e, e)}({t}t)" for e, t in player.active_effects.items()]
        fx_text = ("FX: " + " ".join(parts))[:PANEL_W - 1]
        lines.insert(14, (fx_text, curses.color_pair(COLOR_HP_LOW) | curses.A_BOLD))

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
         stair_up, stair_down, current_floor, enemies=None, log=None,
         terminals=None, target_line=None, target_pos=None, special_rooms=None,
         max_floor=MAX_FLOOR, theme_override=None, hazards=None, smoke_tiles=None,
         corruption=0):
    term_h, term_w = stdscr.getmaxyx()
    view_h  = term_h - (LOG_LINES + 1)   # reserve log rows + divider
    map_w   = term_w - PANEL_W - 1   # columns available for the map

    # Center camera on player, clamped to map bounds
    cam_x = max(0, min(px - map_w  // 2, max(0, MAP_W - map_w)))
    cam_y = max(0, min(py - view_h // 2, max(0, MAP_H - view_h)))

    stdscr.erase()

    theme     = theme_override if theme_override is not None else get_theme(current_floor)
    wall_attr = curses.color_pair(theme['wall_cp'])

    special_tile_set = set()
    if special_rooms:
        for sr in special_rooms.values():
            special_tile_set |= sr['tiles']

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
                    attr = wall_attr
                elif (mx, my) == stair_down:
                    ch   = '>'
                    attr = curses.color_pair(COLOR_STAIR) | curses.A_BOLD
                elif stair_up and (mx, my) == stair_up:
                    ch   = '<'
                    attr = curses.color_pair(COLOR_STAIR) | curses.A_BOLD
                elif (mx, my) in items_on_map:
                    ch   = items_on_map[(mx, my)].char
                    attr = curses.color_pair(COLOR_ITEM) | curses.A_BOLD
                elif terminals and (mx, my) in terminals:
                    t    = terminals[(mx, my)]
                    ch   = 'T' if not t.read else 't'
                    attr = (curses.color_pair(COLOR_TERMINAL) | curses.A_BOLD
                            if not t.read
                            else curses.color_pair(COLOR_DARK) | curses.A_DIM)
                elif enemies and (mx, my) in enemies:
                    e  = enemies[(mx, my)]
                    ch = e.char
                    cp = {'ranged':   COLOR_ENEMY_RANGE,
                          'fast':     COLOR_ENEMY_FAST,
                          'brute':    COLOR_ENEMY_BRUTE,
                          'exploder': COLOR_ENEMY_EXPL,
                         }.get(e.behaviour, COLOR_ENEMY)
                    attr = curses.color_pair(cp) | curses.A_BOLD
                elif hazards and (mx, my) in hazards:
                    h = hazards[(mx, my)]
                    if player.skills.get('engineering', 0) >= 1 or h['revealed']:
                        ch   = h['char']
                        attr = curses.color_pair(COLOR_HAZARD) | curses.A_BOLD
                    else:
                        ch   = FLOOR
                        attr = (curses.color_pair(COLOR_SPECIAL) | curses.A_DIM
                                if (mx, my) in special_tile_set
                                else curses.color_pair(COLOR_FLOOR) | curses.A_DIM)
                elif smoke_tiles and (mx, my) in smoke_tiles:
                    ch   = '%'
                    attr = curses.color_pair(COLOR_DARK) | curses.A_DIM
                else:
                    ch   = FLOOR
                    if (mx, my) in special_tile_set:
                        attr = curses.color_pair(COLOR_SPECIAL) | curses.A_DIM
                    else:
                        attr = curses.color_pair(COLOR_FLOOR) | curses.A_DIM
            else:
                # Explored but out of sight — permanent fixtures stay visible
                if (mx, my) == stair_down:
                    ch   = '>'
                    attr = curses.color_pair(COLOR_STAIR) | curses.A_DIM
                elif stair_up and (mx, my) == stair_up:
                    ch   = '<'
                    attr = curses.color_pair(COLOR_STAIR) | curses.A_DIM
                elif terminals and (mx, my) in terminals:
                    ch   = 'T'
                    attr = curses.color_pair(COLOR_TERMINAL) | curses.A_DIM
                elif hazards and (mx, my) in hazards:
                    h = hazards[(mx, my)]
                    if player.skills.get('engineering', 0) >= 1 or h['revealed']:
                        ch   = h['char']
                        attr = curses.color_pair(COLOR_HAZARD) | curses.A_DIM
                    else:
                        ch   = tiles[my][mx]
                        attr = curses.color_pair(COLOR_DARK) | curses.A_DIM
                elif tiles[my][mx] == WALL:
                    ch   = WALL
                    attr = wall_attr | curses.A_DIM
                else:
                    ch   = tiles[my][mx]
                    attr = curses.color_pair(COLOR_DARK) | curses.A_DIM

            # Targeting overlay — drawn on top of everything else
            if target_line and (mx, my) in visible:
                if (mx, my) == target_pos:
                    ch   = 'X'
                    attr = curses.color_pair(COLOR_TARGET) | curses.A_BOLD
                elif (mx, my) in target_line and tiles[my][mx] == FLOOR:
                    ch   = '~'
                    attr = curses.color_pair(COLOR_STAIR)

            try:
                stdscr.addch(sy, sx, ch, attr)
            except curses.error:
                pass

    # --- Stats panel ---
    panel_col = term_w - PANEL_W
    draw_panel(stdscr, player, panel_col, view_h, current_floor,
               max_floor=max_floor, floor_name=theme['name'], corruption=corruption)

    # --- Message log ---
    HINT = " WASD/Arrows:move  F:fire  T:trade  >/< stairs  B:back  I:equip  K:skills  M:map  H:hack  E:disarm  U:use  X:tool  R:reset  Q:quit"
    divider_row = term_h - LOG_LINES - 1
    log_entries = list(log) if log else []   # index 0 = newest

    try:
        for sx in range(term_w - 1):
            stdscr.addch(divider_row, sx, curses.ACS_HLINE)
    except curses.error:
        pass

    for i in range(LOG_LINES):
        row = term_h - LOG_LINES + i
        if i == 0 and not log_entries:
            text, attr = HINT, 0
        elif i < len(log_entries):
            text = log_entries[i]
            attr = curses.A_BOLD if i == 0 else (0 if i == 1 else curses.A_DIM)
        else:
            text, attr = '', 0
        try:
            stdscr.addstr(row, 0, text[: term_w - 1], attr)
        except curses.error:
            pass

    stdscr.refresh()


def show_minimap(stdscr, tiles, px, py, player, visible, explored, items_on_map,
                 stair_up, stair_down, enemies_on_map, terminals_on_map,
                 hazards_on_map, special_rooms, current_floor, site_depth,
                 floor_name, current_theme, smoke_tiles=None):
    """Full-screen floor map overlay. WASD/arrows pan the view; M or Esc closes."""

    # Room-centroid glyphs: shown at the geometric centre of each explored special room
    ROOM_GLYPHS = {
        'shop':         ('$', COLOR_ITEM),
        'armory':       ('A', COLOR_ENEMY),
        'medbay':       ('+', COLOR_PANEL),
        'terminal_hub': ('H', COLOR_TERMINAL),
        'vault':        ('V', COLOR_STAIR),
    }
    room_label_map = {}   # (x, y) -> (char, color_pair_index)
    if special_rooms:
        for spec in special_rooms.values():
            rtype = spec.get('type', '')
            if rtype in ROOM_GLYPHS and any(t in explored for t in spec['tiles']):
                xs = [t[0] for t in spec['tiles']]
                ys = [t[1] for t in spec['tiles']]
                if xs and ys:
                    cx = (min(xs) + max(xs)) // 2
                    cy = (min(ys) + max(ys)) // 2
                    room_label_map[(cx, cy)] = ROOM_GLYPHS[rtype]

    # Exploration percentage
    total_floor    = sum(1 for y in range(MAP_H) for x in range(MAP_W)
                        if tiles[y][x] == FLOOR)
    explored_floor = sum(1 for (x, y) in explored
                        if 0 <= y < MAP_H and 0 <= x < MAP_W and tiles[y][x] == FLOOR)
    pct = int(100 * explored_floor / total_floor) if total_floor else 0

    wall_attr = curses.color_pair(current_theme['wall_cp']) | curses.A_DIM

    # Camera starts centred on player; WASD will pan it
    term_h, term_w = stdscr.getmaxyx()
    map_rows = max(1, term_h - 2)   # row 0 = header, bottom row = legend
    map_cols = term_w
    cam_x = max(0, min(px - map_cols // 2, max(0, MAP_W - map_cols)))
    cam_y = max(0, min(py - map_rows // 2, max(0, MAP_H - map_rows)))

    PAN_KEYS = {
        ord('w'): ( 0, -3), ord('a'): (-3,  0),
        ord('s'): ( 0,  3), ord('d'): ( 3,  0),
        curses.KEY_UP:   ( 0, -3), curses.KEY_LEFT:  (-3,  0),
        curses.KEY_DOWN: ( 0,  3), curses.KEY_RIGHT: ( 3,  0),
    }

    while True:
        term_h, term_w = stdscr.getmaxyx()
        map_rows = max(1, term_h - 2)
        map_cols = term_w
        cam_x = max(0, min(cam_x, max(0, MAP_W - map_cols)))
        cam_y = max(0, min(cam_y, max(0, MAP_H - map_rows)))

        stdscr.erase()

        # --- Header ---
        pct_cp = (COLOR_ITEM   if pct >= 80 else
                  COLOR_TARGET if pct >= 50 else COLOR_HP_LOW)
        title   = f" FLOOR MAP  {floor_name}  Floor {current_floor}/{site_depth}  "
        exp_str = f"Explored: {pct}%  "
        try:
            stdscr.addstr(0, 0, (title + exp_str)[:term_w - 1],
                          curses.color_pair(COLOR_PANEL) | curses.A_BOLD)
            stdscr.addstr(0, len(title), exp_str[:term_w - len(title) - 1],
                          curses.color_pair(pct_cp) | curses.A_BOLD)
        except curses.error:
            pass

        # --- Map tiles ---
        for sy in range(map_rows):
            my = sy + cam_y
            if my >= MAP_H:
                break
            for sx in range(map_cols):
                mx = sx + cam_x
                if mx >= MAP_W:
                    break
                if (mx, my) not in explored:
                    continue

                in_sight = (mx, my) in visible
                ch, attr = None, curses.A_DIM

                if mx == px and my == py:
                    ch   = '@'
                    attr = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD
                elif stair_down and (mx, my) == stair_down:
                    ch   = '>'
                    attr = curses.color_pair(COLOR_STAIR) | (curses.A_BOLD if in_sight else curses.A_DIM)
                elif stair_up and (mx, my) == stair_up:
                    ch   = '<'
                    attr = curses.color_pair(COLOR_STAIR) | (curses.A_BOLD if in_sight else curses.A_DIM)
                elif in_sight and enemies_on_map and (mx, my) in enemies_on_map:
                    e  = enemies_on_map[(mx, my)]
                    cp = {'ranged':   COLOR_ENEMY_RANGE,
                          'fast':     COLOR_ENEMY_FAST,
                          'brute':    COLOR_ENEMY_BRUTE,
                          'exploder': COLOR_ENEMY_EXPL,
                         }.get(e.behaviour, COLOR_ENEMY)
                    ch   = e.char
                    attr = curses.color_pair(cp) | curses.A_BOLD
                elif items_on_map and (mx, my) in items_on_map:
                    ch   = items_on_map[(mx, my)].char
                    attr = curses.color_pair(COLOR_ITEM) | (curses.A_BOLD if in_sight else curses.A_DIM)
                elif terminals_on_map and (mx, my) in terminals_on_map:
                    t    = terminals_on_map[(mx, my)]
                    ch   = 'T' if not t.read else 't'
                    attr = curses.color_pair(COLOR_TERMINAL) | (curses.A_BOLD if in_sight else curses.A_DIM)
                elif hazards_on_map and (mx, my) in hazards_on_map:
                    h = hazards_on_map[(mx, my)]
                    if player.skills.get('engineering', 0) >= 1 or h['revealed']:
                        ch   = h['char']
                        attr = curses.color_pair(COLOR_HAZARD) | (curses.A_BOLD if in_sight else curses.A_DIM)
                    else:
                        ch   = tiles[my][mx]
                        attr = curses.color_pair(COLOR_DARK) | curses.A_DIM
                elif smoke_tiles and (mx, my) in smoke_tiles:
                    ch   = '%'
                    attr = curses.color_pair(COLOR_DARK) | curses.A_DIM
                elif (mx, my) in room_label_map:
                    glyph_ch, glyph_cp = room_label_map[(mx, my)]
                    ch   = glyph_ch
                    attr = curses.color_pair(glyph_cp) | curses.A_BOLD
                elif tiles[my][mx] == WALL:
                    ch   = '#'
                    attr = wall_attr
                else:
                    ch   = '.'
                    attr = curses.color_pair(COLOR_DARK) | curses.A_DIM

                if ch is not None:
                    try:
                        stdscr.addch(sy + 1, sx, ch, attr)
                    except curses.error:
                        pass

        # --- Legend ---
        legend = ("[M/Esc]Close  [WASD]Pan   "
                  "@ You  # Wall  > Stair  ! Item  T Terminal  ^ Trap  % Smoke  "
                  "$ Shop  A Armory  + Medbay  H Hub  V Vault")
        try:
            stdscr.addstr(term_h - 1, 0, legend[:term_w - 1],
                          curses.color_pair(COLOR_DARK) | curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()

        key = stdscr.getch()
        if key in (ord('m'), ord('M'), 27):
            break
        if key in PAN_KEYS:
            dx, dy = PAN_KEYS[key]
            cam_x = max(0, min(cam_x + dx, max(0, MAP_W - map_cols)))
            cam_y = max(0, min(cam_y + dy, max(0, MAP_H - map_rows)))


def show_equipment_screen(stdscr, player, px=0, py=0, items_on_map=None):
    """Modal overlay for managing inventory and equipment."""
    BOX_W       = 58
    MAX_VISIBLE = 18   # max content rows shown at once (excluding borders/footer)

    cur_sel    = getattr(show_equipment_screen, '_cursor', 0)
    scroll_off = 0

    while True:
        term_h, term_w = stdscr.getmaxyx()

        # -- Build entry list and rows_content --
        entries      = []   # (action, payload)
        rows_content = []   # (text, entry_idx or None)

        # EQUIPPED section
        rows_content.append(("  EQUIPPED", None))
        rows_content.append(("", None))
        for slot in Player.SLOTS:
            item  = player.equipment[slot]
            label = Player.SLOT_LABELS[slot]
            if item:
                text = f"  {label:<8}: {item.name} ({item.stat_str()})"
                rows_content.append((text, len(entries)))
                entries.append(('unequip', slot))
            else:
                rows_content.append((f"  {label:<8}: (empty)", None))

        # INVENTORY section
        rows_content.append(("", None))
        rows_content.append((f"  INVENTORY  ({len(player.inventory)}/{MAX_INVENTORY})", None))
        rows_content.append(("", None))

        if player.inventory:
            for item in player.inventory:
                if not item.consumable:
                    # delta vs currently equipped in same slot
                    eq = player.equipment.get(item.slot)
                    if eq:
                        datk  = item.atk - eq.atk
                        ddfn  = item.dfn - eq.dfn
                        parts = []
                        if datk: parts.append(f"ATK{datk:+d}")
                        if ddfn: parts.append(f"DEF{ddfn:+d}")
                        cmp = f" [{', '.join(parts)}]" if parts else " [=]"
                    else:
                        cmp = ""
                    text = f"  {item.name} [{item.slot}] {item.stat_str()}{cmp}"
                else:
                    text = f"  {item.name} [use] {item.stat_str()}"
                rows_content.append((text, len(entries)))
                entries.append(('use' if item.consumable else 'equip', item))
        else:
            rows_content.append(("  (empty)", None))

        # -- Cursor clamping --
        selectable_rows = [i for i, (_, eidx) in enumerate(rows_content)
                           if eidx is not None]
        if selectable_rows:
            cur_sel = max(0, min(cur_sel, len(selectable_rows) - 1))
        else:
            cur_sel = 0

        # Scroll to keep selected row visible
        if selectable_rows:
            sel_flat = selectable_rows[cur_sel]
            if sel_flat < scroll_off:
                scroll_off = sel_flat
            elif sel_flat >= scroll_off + MAX_VISIBLE:
                scroll_off = sel_flat - MAX_VISIBLE + 1
        visible_rows = rows_content[scroll_off: scroll_off + MAX_VISIBLE]

        # -- Box geometry --
        content_h  = len(visible_rows)
        box_h      = content_h + 3   # top border + content + footer + bottom border
        box_y      = max(0, (term_h - box_h) // 2)
        box_x      = max(0, (term_w - BOX_W) // 2)
        panel_attr = curses.color_pair(COLOR_PANEL)
        bold_attr  = panel_attr | curses.A_BOLD

        # -- Top border with embedded title --
        title_str = f" EQUIPMENT  ({len(player.inventory)}/{MAX_INVENTORY}) "
        try:
            stdscr.addch(box_y, box_x, curses.ACS_ULCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, panel_attr)
            tx = box_x + (BOX_W - len(title_str)) // 2
            stdscr.addstr(box_y, tx, title_str, bold_attr)
            stdscr.addch(box_y, box_x + BOX_W - 1, curses.ACS_URCORNER, panel_attr)
        except curses.error:
            pass

        # -- Content rows --
        for ri, (text, eidx) in enumerate(visible_rows):
            row      = box_y + 1 + ri
            flat_idx = scroll_off + ri
            is_sel   = bool(selectable_rows and selectable_rows[cur_sel] == flat_idx)
            is_hdr   = (eidx is None and bool(text.strip()) and
                        text.strip().replace('/', '').replace('(', '').
                        replace(')', '').replace(' ', '').isdigit() is False and
                        text.strip()[0].isupper() and
                        all(c.isupper() or not c.isalpha() for c in text.strip()))

            try:
                stdscr.addch(row, box_x,           curses.ACS_VLINE, panel_attr)
                stdscr.addch(row, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
                stdscr.addstr(row, box_x + 1, ' ' * (BOX_W - 2))
            except curses.error:
                pass

            if is_sel:
                display = ('> ' + text.lstrip())[:BOX_W - 2]
                attr    = bold_attr
            elif is_hdr:
                display = text[:BOX_W - 2]
                attr    = bold_attr
            else:
                display = text[:BOX_W - 2]
                attr    = panel_attr

            try:
                stdscr.addstr(row, box_x + 1, display, attr)
            except curses.error:
                pass

        # -- Footer row --
        footer_row = box_y + 1 + content_h
        FOOTER     = "  Enter:equip/use  D:drop  Esc/I:close"
        try:
            stdscr.addch(footer_row, box_x,           curses.ACS_VLINE, panel_attr)
            stdscr.addch(footer_row, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
            stdscr.addstr(footer_row, box_x + 1, ' ' * (BOX_W - 2))
            stdscr.addstr(footer_row, box_x + 1, FOOTER[:BOX_W - 2],
                          panel_attr | curses.A_DIM)
        except curses.error:
            pass

        # -- Bottom border --
        bot_row = box_y + 2 + content_h
        try:
            stdscr.addch(bot_row, box_x, curses.ACS_LLCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(bot_row, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(bot_row, box_x + BOX_W - 1, curses.ACS_LRCORNER, panel_attr)
        except curses.error:
            pass

        stdscr.refresh()
        key = stdscr.getch()

        # -- Input --
        if key in (27, ord('i'), ord('I')):
            show_equipment_screen._cursor = cur_sel
            return ''

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
                flat_idx = selectable_rows[cur_sel]
                _, eidx  = rows_content[flat_idx]
                if eidx is not None:
                    action, payload = entries[eidx]
                    if action == 'equip':
                        player.equip(payload)
                        show_equipment_screen._cursor = cur_sel
                    elif action == 'unequip':
                        player.unequip(payload)
                    elif action == 'use':
                        result = payload.use(player)
                        player.inventory.remove(payload)
                        show_equipment_screen._cursor = max(0, cur_sel - 1)
                        return result

        elif key in (ord('d'), ord('D')):
            if selectable_rows and items_on_map is not None:
                flat_idx = selectable_rows[cur_sel]
                _, eidx  = rows_content[flat_idx]
                if eidx is not None:
                    action, payload = entries[eidx]
                    if action in ('equip', 'use'):   # inventory item, not a slot
                        player.inventory.remove(payload)
                        items_on_map[(px, py)] = payload
                        show_equipment_screen._cursor = max(0, cur_sel - 1)
                        return f"Dropped {payload.name}."


def show_shop_screen(stdscr, player, stock):
    """Modal shop screen for buying items. stock is mutated in-place. Returns message string."""
    BOX_W       = 58
    MAX_VISIBLE = 18
    cur_sel     = 0
    scroll_off  = 0

    while True:
        term_h, term_w = stdscr.getmaxyx()
        panel_attr = curses.color_pair(COLOR_PANEL)
        bold_attr  = panel_attr | curses.A_BOLD

        rows_content = []   # (text, stock_idx or None)
        rows_content.append(("  AVAILABLE ITEMS", None))
        rows_content.append(("", None))

        for idx, (item, base_price) in enumerate(stock):
            barter_discount = player.skills.get('barter', 0) * 0.05
            price = int(base_price * max(0.4, 1.0 - (player.presence - 5) * 0.05 - barter_discount))
            stat  = item.stat_str()
            text  = f"  {item.name:<20} [{item.slot:<6}] {stat:<14} {price:>3} cr"
            rows_content.append((text[:BOX_W - 2], idx))

        if not stock:
            rows_content.append(("  (out of stock)", None))

        selectable_rows = [i for i, (_, si) in enumerate(rows_content) if si is not None]
        if selectable_rows:
            cur_sel = max(0, min(cur_sel, len(selectable_rows) - 1))
        else:
            cur_sel = 0

        if selectable_rows:
            sel_flat = selectable_rows[cur_sel]
            if sel_flat < scroll_off:
                scroll_off = sel_flat
            elif sel_flat >= scroll_off + MAX_VISIBLE:
                scroll_off = sel_flat - MAX_VISIBLE + 1
        visible_rows = rows_content[scroll_off: scroll_off + MAX_VISIBLE]

        content_h = len(visible_rows)
        box_h     = content_h + 3
        box_y     = max(0, (term_h - box_h) // 2)
        box_x     = max(0, (term_w - BOX_W) // 2)

        title_str = f" SUPPLY DEPOT  [Credits: {player.credits}] "
        try:
            stdscr.addch(box_y, box_x, curses.ACS_ULCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, panel_attr)
            tx = box_x + (BOX_W - len(title_str)) // 2
            stdscr.addstr(box_y, tx, title_str, bold_attr)
            stdscr.addch(box_y, box_x + BOX_W - 1, curses.ACS_URCORNER, panel_attr)
        except curses.error:
            pass

        for ri, (text, sidx) in enumerate(visible_rows):
            row      = box_y + 1 + ri
            flat_idx = scroll_off + ri
            is_sel   = bool(selectable_rows and selectable_rows[cur_sel] == flat_idx)
            try:
                stdscr.addch(row, box_x,             curses.ACS_VLINE, panel_attr)
                stdscr.addch(row, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
                stdscr.addstr(row, box_x + 1, ' ' * (BOX_W - 2))
            except curses.error:
                pass
            if is_sel:
                display = ('> ' + text.lstrip())[:BOX_W - 2]
                attr    = bold_attr
            else:
                display = text[:BOX_W - 2]
                attr    = panel_attr
            try:
                stdscr.addstr(row, box_x + 1, display, attr)
            except curses.error:
                pass

        footer_row = box_y + 1 + content_h
        FOOTER     = "  Enter:buy   W/S:scroll   Esc:close"
        try:
            stdscr.addch(footer_row, box_x,             curses.ACS_VLINE, panel_attr)
            stdscr.addch(footer_row, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
            stdscr.addstr(footer_row, box_x + 1, ' ' * (BOX_W - 2))
            stdscr.addstr(footer_row, box_x + 1, FOOTER[:BOX_W - 2], panel_attr | curses.A_DIM)
        except curses.error:
            pass

        bot_row = box_y + 2 + content_h
        try:
            stdscr.addch(bot_row, box_x, curses.ACS_LLCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(bot_row, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(bot_row, box_x + BOX_W - 1, curses.ACS_LRCORNER, panel_attr)
        except curses.error:
            pass

        stdscr.refresh()
        key = stdscr.getch()

        if key in (27, ord('i'), ord('I'), ord('t'), ord('T')):
            return ''

        if key in (curses.KEY_UP, ord('w'), ord('W')):
            if selectable_rows:
                cur_sel = max(0, cur_sel - 1)
        elif key in (curses.KEY_DOWN, ord('s'), ord('S')):
            if selectable_rows:
                cur_sel = min(len(selectable_rows) - 1, cur_sel + 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            if selectable_rows and stock:
                flat_idx = selectable_rows[cur_sel]
                _, sidx  = rows_content[flat_idx]
                if sidx is not None:
                    item, base_price = stock[sidx]
                    barter_discount = player.skills.get('barter', 0) * 0.05
                    price = int(base_price * max(0.4, 1.0 - (player.presence - 5) * 0.05 - barter_discount))
                    if player.credits < price:
                        return f"Need {price} cr, have {player.credits} cr."
                    if len(player.inventory) >= MAX_INVENTORY:
                        return "Inventory full."
                    player.credits -= price
                    player.inventory.append(copy.copy(item))
                    stock.pop(sidx)
                    return f"Bought {item.name} for {price} cr."


def show_vault_prompt(stdscr, cost, player_credits):
    """Small centered modal asking to pay credits to unlock vault.
    Returns True (pay) or False (cancel)."""
    BOX_W      = 36
    panel_attr = curses.color_pair(COLOR_PANEL)
    bold_attr  = panel_attr | curses.A_BOLD

    content_lines = [
        ("  VAULT — LOCKED",                               bold_attr),
        (f"  Cost: {cost} cr  (have: {player_credits} cr)", panel_attr),
        ("",                                               0),
        ("  [Y] Unlock   [N] Cancel",                     panel_attr),
    ]

    while True:
        term_h, term_w = stdscr.getmaxyx()
        box_h = len(content_lines) + 2
        box_y = max(0, (term_h - box_h) // 2)
        box_x = max(0, (term_w - BOX_W) // 2)

        try:
            stdscr.addch(box_y, box_x, curses.ACS_ULCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(box_y, box_x + BOX_W - 1, curses.ACS_URCORNER, panel_attr)
        except curses.error:
            pass

        for ri, (text, attr) in enumerate(content_lines):
            row = box_y + 1 + ri
            try:
                stdscr.addch(row, box_x,             curses.ACS_VLINE, panel_attr)
                stdscr.addch(row, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
                stdscr.addstr(row, box_x + 1, ' ' * (BOX_W - 2))
                if text:
                    stdscr.addstr(row, box_x + 1, text[:BOX_W - 2], attr)
            except curses.error:
                pass

        bot_row = box_y + 1 + len(content_lines)
        try:
            stdscr.addch(bot_row, box_x, curses.ACS_LLCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(bot_row, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(bot_row, box_x + BOX_W - 1, curses.ACS_LRCORNER, panel_attr)
        except curses.error:
            pass

        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord('y'), ord('Y')):
            return True
        if key in (ord('n'), ord('N'), 27):
            return False


def show_terminal(stdscr, terminal):
    """Display terminal content in a modal overlay. Any key closes."""
    terminal.read = True
    BOX_W      = 62
    inner_w    = BOX_W - 4
    panel_attr = curses.color_pair(COLOR_TERMINAL)
    head_attr  = panel_attr | curses.A_BOLD

    # Word-wrap each line of content to inner_w
    wrapped = []
    for line in terminal.lines:
        if not line:
            wrapped.append('')
            continue
        words, current = line.split(), ''
        for word in words:
            if current and len(current) + 1 + len(word) > inner_w:
                wrapped.append(current)
                current = word
            else:
                current = (current + ' ' + word).strip()
        if current:
            wrapped.append(current)

    # rows_content: None = draw a divider line, str = draw text
    rows_content = (
        [terminal.title[:inner_w + 2], None, ''] +
        wrapped +
        ['', None, '[any key to close]'.center(inner_w + 2)]
    )

    term_h, term_w = stdscr.getmaxyx()
    box_h = len(rows_content) + 2   # +2 for top/bottom border
    box_y = max(0, (term_h - box_h) // 2)
    box_x = max(0, (term_w - BOX_W) // 2)

    # Top border
    try:
        stdscr.addch(box_y, box_x, curses.ACS_ULCORNER, panel_attr)
        for bx in range(1, BOX_W - 1):
            stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, panel_attr)
        stdscr.addch(box_y, box_x + BOX_W - 1, curses.ACS_URCORNER, panel_attr)
    except curses.error:
        pass

    for ri, text in enumerate(rows_content):
        row = box_y + 1 + ri
        try:
            stdscr.addch(row, box_x,           curses.ACS_VLINE, panel_attr)
            stdscr.addch(row, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
            stdscr.addstr(row, box_x + 1, ' ' * (BOX_W - 2))
        except curses.error:
            pass
        if text is None:
            try:
                for bx in range(1, BOX_W - 1):
                    stdscr.addch(row, box_x + bx, curses.ACS_HLINE, panel_attr)
            except curses.error:
                pass
        elif text:
            attr = head_attr if ri == 0 else panel_attr
            try:
                stdscr.addstr(row, box_x + 2, text[:inner_w + 2], attr)
            except curses.error:
                pass

    # Bottom border
    bot = box_y + 1 + len(rows_content)
    try:
        stdscr.addch(bot, box_x, curses.ACS_LLCORNER, panel_attr)
        for bx in range(1, BOX_W - 1):
            stdscr.addch(bot, box_x + bx, curses.ACS_HLINE, panel_attr)
        stdscr.addch(bot, box_x + BOX_W - 1, curses.ACS_LRCORNER, panel_attr)
    except curses.error:
        pass

    stdscr.refresh()
    stdscr.getch()


def show_targeting(stdscr, tiles, px, py, player, visible, explored,
                   items_on_map, stair_up, stair_down, current_floor,
                   enemies_on_map, log, terminals_on_map=None, hazards_on_map=None,
                   smoke_tiles=None, corruption=0):
    """Targeting cursor for ranged attack.
    Tab cycles targets. Enter fires. Esc/F cancels.
    Returns (target_pos, enemy) or (None, None)."""
    visible_enemies = sorted(
        [(pos, e) for pos, e in enemies_on_map.items() if pos in visible],
        key=lambda pe: abs(pe[0][0] - px) + abs(pe[0][1] - py),
    )
    if not visible_enemies:
        return None, None

    # Instruction shown as the newest log entry during targeting
    hint_log = collections.deque(
        ["TARGETING — Tab: next target   Enter: fire   Esc: cancel"],
        maxlen=LOG_LINES,
    )
    hint_log.extend(log)

    cur = 0
    while True:
        target_pos, target_enemy = visible_enemies[cur]
        tx, ty = target_pos

        # Trajectory from player to target — stop tracing at first wall
        line_tiles = set()
        for lx, ly in _bresenham(px, py, tx, ty):
            if (lx, ly) == (px, py):
                continue
            line_tiles.add((lx, ly))
            if tiles[ly][lx] == WALL:
                break

        draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
             stair_up, stair_down, current_floor, enemies_on_map, hint_log,
             terminals=terminals_on_map, target_line=line_tiles, target_pos=target_pos,
             hazards=hazards_on_map, smoke_tiles=smoke_tiles, corruption=corruption)

        key = stdscr.getch()

        if key in (27, ord('f'), ord('F')):      # Esc or F — cancel
            return None, None
        if key == 9:                              # Tab — next target
            cur = (cur + 1) % len(visible_enemies)
        if key in (curses.KEY_ENTER, 10, 13):    # Enter — fire
            return target_pos, target_enemy


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
        """Apply race + class mods to STAT_BASE, clamped to STAT_MIN.
        Also returns background skill allocations from the class."""
        rmods = RACES[race_name]['mods']
        cmods = CLASSES[class_name]['mods']
        result = {}
        for s in STATS:
            val = STAT_BASE + rmods.get(s, 0) + cmods.get(s, 0)
            result[s] = max(STAT_MIN, val)
        bg_skills = dict(CLASSES[class_name].get('skills', {}))
        return result, bg_skills

    def mod_str(mods):
        parts = []
        for s, label in zip(STATS, STAT_LABELS):
            v = mods.get(s, 0)
            if v != 0:
                parts.append(f"{label[0]}{v:+d}")
        return '  '.join(parts) if parts else '(no modifiers)'

    step        = 0
    name        = ''
    race_idx    = 0
    class_idx   = 0
    alloc       = {s: 0 for s in STATS}
    stat_cursor  = 0   # index into STATS for point-buy step
    skill_alloc  = {k: 0 for k in SKILL_ORDER}   # extra free points beyond background
    skill_cursor = 0   # index into SKILL_ORDER for skill allocation step

    while True:
        term_h, term_w = stdscr.getmaxyx()
        clr()

        # -- Step 0: Name --
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

        # -- Step 1: Race --
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

        # -- Step 2: Background --
        elif step == 2:
            title = "CHARACTER CREATION — Background"
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
                alloc       = {s: 0 for s in STATS}      # reset alloc on class change
                skill_alloc = {k: 0 for k in SKILL_ORDER}  # reset skill alloc
                step = 3

        # -- Step 3: Point Buy --
        elif step == 3:
            rname      = race_names[race_idx]
            cname      = class_names[class_idx]
            base, _bg  = compute_base(rname, cname)
            remain     = POINT_BUY_POINTS - sum(alloc.values())

            title = "CHARACTER CREATION — Distribute Points"
            safe_addstr(1, 2, title, header_attr)
            safe_addstr(3, 2,
                f"Points remaining: {remain}   "
                "W/S: select stat   A/D: add/remove   Enter: confirm   Esc: back",
                panel_attr)

            for i, (s, label) in enumerate(zip(STATS, STAT_LABELS)):
                row = 5 + i * 2
                val = base[s] + alloc[s]
                bar = '\u2588' * val + '\u2591' * (STAT_MAX - val)
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
                skill_alloc = {k: 0 for k in SKILL_ORDER}   # reset skill alloc entering step 4
                step = 4

        # -- Step 4: Skill Allocation --
        elif step == 4:
            rname      = race_names[race_idx]
            cname      = class_names[class_idx]
            _base, bg_skills = compute_base(rname, cname)
            remaining_sp = STARTING_SKILL_POINTS - sum(skill_alloc.values())

            title = "CHARACTER CREATION — Allocate Skills"
            safe_addstr(1, 2, title, header_attr)
            safe_addstr(3, 2,
                f"Free points: {remaining_sp}   "
                "W/S: select   D: add   A: remove (free only)   Enter: continue   Esc: back",
                panel_attr)

            # Group skills by category for display
            cur_cat = None
            row = 5
            for i, sk in enumerate(SKILL_ORDER):
                sdata = SKILLS[sk]
                cat   = sdata['cat']
                if cat != cur_cat:
                    safe_addstr(row, 2, cat.upper(), panel_attr | curses.A_BOLD)
                    row += 1
                    cur_cat = cat
                bg_lv    = bg_skills.get(sk, 0)
                extra_lv = skill_alloc.get(sk, 0)
                total_lv = bg_lv + extra_lv
                bar      = '\u2588' * total_lv + '\u2591' * (SKILL_MAX - total_lv)
                attr     = sel_attr if i == skill_cursor else panel_attr
                prefix   = '> ' if i == skill_cursor else '  '
                line = f"{prefix}{sdata['name']:<14} {bar}  {total_lv}/{SKILL_MAX}  {sdata['effect']}"
                safe_addstr(row, 2, line[:term_w - 4], attr)
                if bg_lv > 0:
                    safe_addstr(row, 2 + len(prefix) + 14 + 1 + bg_lv - 1, '',
                                panel_attr)  # background skills already filled by char
                row += 1

            stdscr.refresh()
            key = stdscr.getch()

            if key == 27:
                step = 3
            elif key in (curses.KEY_UP, ord('w'), ord('W')):
                skill_cursor = (skill_cursor - 1) % len(SKILL_ORDER)
            elif key in (curses.KEY_DOWN, ord('s'), ord('S')):
                skill_cursor = (skill_cursor + 1) % len(SKILL_ORDER)
            elif key in (curses.KEY_RIGHT, ord('d'), ord('D')):
                sk       = SKILL_ORDER[skill_cursor]
                bg_lv    = bg_skills.get(sk, 0)
                total_lv = bg_lv + skill_alloc.get(sk, 0)
                if remaining_sp > 0 and total_lv < SKILL_MAX:
                    skill_alloc[sk] = skill_alloc.get(sk, 0) + 1
            elif key in (curses.KEY_LEFT, ord('a'), ord('A')):
                sk = SKILL_ORDER[skill_cursor]
                if skill_alloc.get(sk, 0) > 0:
                    skill_alloc[sk] -= 1
            elif key in (curses.KEY_ENTER, 10, 13):
                step = 5

        # -- Step 5: Confirm --
        elif step == 5:
            rname      = race_names[race_idx]
            cname      = class_names[class_idx]
            base, bg_skills = compute_base(rname, cname)
            final  = {s: base[s] + alloc[s] for s in STATS}
            max_hp = 20 + final['body'] * 2
            # Build final skills: background + free allocations
            final_skills = {k: 0 for k in SKILL_ORDER}
            for k, v in bg_skills.items():
                final_skills[k] = final_skills.get(k, 0) + v
            for k, v in skill_alloc.items():
                final_skills[k] = final_skills.get(k, 0) + v

            title = "CHARACTER CREATION — Confirm"
            safe_addstr(1, 2, title, header_attr)
            safe_addstr(3, 2, f"Name:       {name}", panel_attr)
            safe_addstr(4, 2, f"Race:       {rname}", panel_attr)
            safe_addstr(5, 2, f"Background: {cname}", panel_attr)
            safe_addstr(7, 2, "STATS", header_attr)

            for i, (s, label) in enumerate(zip(STATS, STAT_LABELS)):
                safe_addstr(8 + i, 4, f"{label:<10} {final[s]:>2}", panel_attr)

            safe_addstr(8 + len(STATS) + 1, 2, f"Max HP: {max_hp}", panel_attr)

            # Show non-zero skills
            nz_skills = [(k, v) for k, v in final_skills.items() if v > 0]
            if nz_skills:
                safe_addstr(8 + len(STATS) + 3, 2, "SKILLS", header_attr)
                for si, (sk, lv) in enumerate(nz_skills):
                    safe_addstr(8 + len(STATS) + 4 + si, 4,
                                f"{SKILLS[sk]['name']:<14} {lv}", panel_attr)
                conf_row = 8 + len(STATS) + 5 + len(nz_skills)
            else:
                conf_row = 8 + len(STATS) + 3

            safe_addstr(conf_row, 2, "Enter: begin game   Esc: back", panel_attr)

            stdscr.refresh()
            key = stdscr.getch()

            if key == 27:
                step = 4
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
                    skills=final_skills,
                )


def show_skill_levelup_modal(stdscr, player, points=2):
    """Modal for spending skill points after levelling up.
    points: how many the player may spend now; any unspent are banked to player.skill_points."""
    BOX_W      = 56
    panel_attr = curses.color_pair(COLOR_PANEL)
    hi_attr    = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD
    head_attr  = panel_attr | curses.A_BOLD

    remaining  = points
    allocated  = {k: 0 for k in SKILL_ORDER}   # points spent THIS modal (removable)
    cursor     = 0

    while True:
        term_h, term_w = stdscr.getmaxyx()
        # BOX_H: title row + blank + 12 skill rows + blank + footer + borders = 18
        BOX_H  = 3 + len(SKILL_ORDER) + 3
        box_y  = max(0, (term_h - BOX_H) // 2)
        box_x  = max(0, (term_w - BOX_W) // 2)

        # Border
        try:
            stdscr.addch(box_y, box_x, curses.ACS_ULCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(box_y, box_x + BOX_W - 1, curses.ACS_URCORNER, panel_attr)
        except curses.error:
            pass
        for ry in range(1, BOX_H - 1):
            try:
                stdscr.addch(box_y + ry, box_x, curses.ACS_VLINE, panel_attr)
                stdscr.addch(box_y + ry, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
            except curses.error:
                pass
        try:
            stdscr.addch(box_y + BOX_H - 1, box_x, curses.ACS_LLCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(box_y + BOX_H - 1, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(box_y + BOX_H - 1, box_x + BOX_W - 1, curses.ACS_LRCORNER, panel_attr)
        except curses.error:
            pass

        # Title
        title = f"  SKILL POINTS — {remaining} to spend  "
        try:
            stdscr.addstr(box_y + 1, box_x + 1, title[:BOX_W - 2].center(BOX_W - 2), head_attr)
        except curses.error:
            pass

        # Skill rows
        for i, sk in enumerate(SKILL_ORDER):
            row      = box_y + 3 + i
            sdata    = SKILLS[sk]
            cur_lv   = player.skills.get(sk, 0) + allocated.get(sk, 0)
            bar      = '\u2588' * cur_lv + '\u2591' * (SKILL_MAX - cur_lv)
            prefix   = '>' if i == cursor else ' '
            attr     = hi_attr if i == cursor else panel_attr
            line     = f" {prefix} {sdata['name']:<14} {bar}  {cur_lv}/{SKILL_MAX}  {sdata['effect']}"
            try:
                stdscr.addstr(row, box_x + 1, line[:BOX_W - 2].ljust(BOX_W - 2), attr)
            except curses.error:
                pass

        # Footer
        footer = "  W/S:select  D:add  A:remove  Enter:done  "
        try:
            stdscr.addstr(box_y + BOX_H - 2, box_x + 1, footer[:BOX_W - 2].center(BOX_W - 2),
                          panel_attr)
        except curses.error:
            pass

        stdscr.refresh()
        key = stdscr.getch()

        if key in (ord('w'), ord('W'), curses.KEY_UP):
            cursor = (cursor - 1) % len(SKILL_ORDER)
        elif key in (ord('s'), ord('S'), curses.KEY_DOWN):
            cursor = (cursor + 1) % len(SKILL_ORDER)
        elif key in (ord('d'), ord('D'), curses.KEY_RIGHT):
            sk     = SKILL_ORDER[cursor]
            cur_lv = player.skills.get(sk, 0) + allocated.get(sk, 0)
            if remaining > 0 and cur_lv < SKILL_MAX:
                allocated[sk] = allocated.get(sk, 0) + 1
                remaining    -= 1
        elif key in (ord('a'), ord('A'), curses.KEY_LEFT):
            sk = SKILL_ORDER[cursor]
            if allocated.get(sk, 0) > 0:
                allocated[sk] -= 1
                remaining     += 1
        elif key in (ord('\n'), curses.KEY_ENTER, 10, 13, 27):
            # Apply allocations
            for sk, lv in allocated.items():
                player.skills[sk] = player.skills.get(sk, 0) + lv
            # Bank unspent points
            player.skill_points += remaining
            break


def show_skills_screen(stdscr, player):
    """Read-only skills overview; allows spending banked skill_points if any."""
    BOX_W      = 58
    panel_attr = curses.color_pair(COLOR_PANEL)
    hi_attr    = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD
    head_attr  = panel_attr | curses.A_BOLD

    cursor  = 0
    can_spend = player.skill_points > 0

    while True:
        term_h, term_w = stdscr.getmaxyx()

        # Count rows needed: category headers + skill rows
        rows_content = []   # (text, attr, skill_key_or_None)
        cur_cat = None
        for sk in SKILL_ORDER:
            sdata = SKILLS[sk]
            cat   = sdata['cat']
            if cat != cur_cat:
                rows_content.append((cat.upper(), head_attr, None))
                cur_cat = cat
            lv   = player.skills.get(sk, 0)
            bar  = '\u2588' * lv + '\u2591' * (SKILL_MAX - lv)
            eff  = sdata['effect'] if lv > 0 else '—'
            line = f"  {sdata['name']:<14} {bar}  {lv}/{SKILL_MAX}   {eff}"
            attr = hi_attr if (can_spend and SKILL_ORDER.index(sk) == cursor) else panel_attr
            rows_content.append((line, attr, sk))

        BOX_H  = len(rows_content) + 4   # title + content + blank + footer + borders
        box_y  = max(0, (term_h - BOX_H) // 2)
        box_x  = max(0, (term_w - BOX_W) // 2)

        # Border
        try:
            stdscr.addch(box_y, box_x, curses.ACS_ULCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(box_y, box_x + BOX_W - 1, curses.ACS_URCORNER, panel_attr)
        except curses.error:
            pass
        for ry in range(1, BOX_H - 1):
            try:
                stdscr.addch(box_y + ry, box_x, curses.ACS_VLINE, panel_attr)
                stdscr.addch(box_y + ry, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
            except curses.error:
                pass
        try:
            stdscr.addch(box_y + BOX_H - 1, box_x, curses.ACS_LLCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(box_y + BOX_H - 1, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(box_y + BOX_H - 1, box_x + BOX_W - 1, curses.ACS_LRCORNER, panel_attr)
        except curses.error:
            pass

        # Title with SP count
        sp_str = f"[SP: {player.skill_points} unspent]" if player.skill_points else ""
        title  = f"  SKILLS  {sp_str}"
        try:
            stdscr.addstr(box_y + 1, box_x + 1, title[:BOX_W - 2].ljust(BOX_W - 2), head_attr)
        except curses.error:
            pass

        # Content rows
        for ri, (text, attr, sk) in enumerate(rows_content):
            row = box_y + 2 + ri
            try:
                stdscr.addstr(row, box_x + 1, ' ' * (BOX_W - 2))
                stdscr.addstr(row, box_x + 1, text[:BOX_W - 2], attr)
            except curses.error:
                pass

        # Footer
        if can_spend:
            footer = "  W/S:select  D:spend point  K/Esc:close  "
        else:
            footer = "  K/Esc:close  "
        try:
            stdscr.addstr(box_y + BOX_H - 2, box_x + 1, footer[:BOX_W - 2].center(BOX_W - 2),
                          panel_attr | curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()
        key = stdscr.getch()

        if key in (27, ord('k'), ord('K')):
            break
        if can_spend:
            if key in (ord('w'), ord('W'), curses.KEY_UP):
                # Navigate only to skill rows
                sk_indices = [i for i, (_, _, s) in enumerate(rows_content) if s is not None]
                cur_sk_pos = next((p for p, idx in enumerate(sk_indices)
                                   if SKILL_ORDER.index(rows_content[idx][2]) == cursor), 0)
                if cur_sk_pos > 0:
                    cursor = SKILL_ORDER.index(rows_content[sk_indices[cur_sk_pos - 1]][2])
            elif key in (ord('s'), ord('S'), curses.KEY_DOWN):
                sk_indices = [i for i, (_, _, s) in enumerate(rows_content) if s is not None]
                cur_sk_pos = next((p for p, idx in enumerate(sk_indices)
                                   if SKILL_ORDER.index(rows_content[idx][2]) == cursor), 0)
                if cur_sk_pos < len(sk_indices) - 1:
                    cursor = SKILL_ORDER.index(rows_content[sk_indices[cur_sk_pos + 1]][2])
            elif key in (ord('d'), ord('D')):
                sk    = SKILL_ORDER[cursor]
                cur_lv = player.skills.get(sk, 0)
                if player.skill_points > 0 and cur_lv < SKILL_MAX:
                    player.skills[sk]  = cur_lv + 1
                    player.skill_points -= 1
                    can_spend = player.skill_points > 0


def show_levelup_modal(stdscr, player):
    """Modal overlay for choosing a stat to increase on level-up. No cancel — must pick."""
    STAT_DESC = {
        'body':     '+HP / ATK',
        'reflex':   '+dodge',
        'mind':     '+XP / FOV',
        'tech':     '+ranged',
        'presence': '+intimidate',
    }
    BOX_W      = 34
    BOX_H      = 13
    panel_attr = curses.color_pair(COLOR_PANEL)
    hi_attr    = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD
    head_attr  = panel_attr | curses.A_BOLD

    term_h, term_w = stdscr.getmaxyx()
    box_y = max(0, (term_h - BOX_H) // 2)
    box_x = max(0, (term_w - BOX_W) // 2)

    cursor = 0

    def _draw():
        # Border
        try:
            stdscr.addch(box_y, box_x, curses.ACS_ULCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(box_y, box_x + BOX_W - 1, curses.ACS_URCORNER, panel_attr)
        except curses.error:
            pass
        for ry in range(1, BOX_H - 1):
            try:
                stdscr.addch(box_y + ry, box_x, curses.ACS_VLINE, panel_attr)
                stdscr.addch(box_y + ry, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
            except curses.error:
                pass
        try:
            stdscr.addch(box_y + BOX_H - 1, box_x, curses.ACS_LLCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(box_y + BOX_H - 1, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(box_y + BOX_H - 1, box_x + BOX_W - 1, curses.ACS_LRCORNER, panel_attr)
        except curses.error:
            pass

        # Title row
        title = f"  LEVEL UP!  Rank -> {player.level}  "
        try:
            stdscr.addstr(box_y + 1, box_x + 1, title[:BOX_W - 2].center(BOX_W - 2), head_attr)
        except curses.error:
            pass

        # Prompt row
        try:
            stdscr.addstr(box_y + 3, box_x + 1,
                          "  Choose a stat to increase:  "[:BOX_W - 2],
                          panel_attr)
        except curses.error:
            pass

        # Stat rows (rows 5-9)
        for i, stat in enumerate(STATS):
            row = box_y + 5 + i
            val = getattr(player, stat)
            label = STAT_LABELS[i]
            desc  = STAT_DESC[stat]
            prefix = '>' if i == cursor else ' '
            line = f" {prefix} {label:<9}{val:>2}  {desc}"
            attr = hi_attr if i == cursor else panel_attr
            try:
                stdscr.addstr(row, box_x + 1, line[:BOX_W - 2].ljust(BOX_W - 2), attr)
            except curses.error:
                pass

        # Footer
        try:
            stdscr.addstr(box_y + 11, box_x + 1,
                          "  W/S: select   Enter: pick  "[:BOX_W - 2].center(BOX_W - 2),
                          panel_attr)
        except curses.error:
            pass

        stdscr.refresh()

    while True:
        _draw()
        key = stdscr.getch()
        if key in (ord('w'), ord('W'), curses.KEY_UP):
            cursor = (cursor - 1) % len(STATS)
        elif key in (ord('s'), ord('S'), curses.KEY_DOWN):
            cursor = (cursor + 1) % len(STATS)
        elif key in (ord('\n'), curses.KEY_ENTER, 10, 13):
            stat_name = STATS[cursor]
            new_val = min(STAT_MAX, getattr(player, stat_name) + 1)
            setattr(player, stat_name, new_val)
            if stat_name == 'body':
                player.max_hp = 20 + player.body * 2
            player.hp = player.max_hp
            break


def show_run_summary(stdscr, player, site_name, outcome='dead'):
    """Run summary screen shown on death or mid-run restart. Returns True to restart, False to quit."""
    panel  = curses.color_pair(COLOR_PANEL)
    bold   = curses.color_pair(COLOR_PANEL)    | curses.A_BOLD
    dim    = curses.color_pair(COLOR_DARK)     | curses.A_DIM
    red    = curses.color_pair(COLOR_HP_LOW)   | curses.A_BOLD
    green  = curses.color_pair(COLOR_ITEM)     | curses.A_BOLD
    yellow = curses.color_pair(COLOR_TARGET)   | curses.A_BOLD

    total_xp = player.xp + player.XP_PER_LEVEL * (player.level * (player.level - 1) // 2)

    if outcome == 'dead':
        heading      = "MISSION FAILED"
        heading_attr = red
        outcome_str  = "Killed in action"
    else:
        heading      = "RUN COMPLETE"
        heading_attr = green
        outcome_str  = "Returned to the Meridian"

    BOX_W   = 52
    inner_w = BOX_W - 4

    while True:
        term_h, term_w = stdscr.getmaxyx()
        stdscr.erase()

        # Centre the box
        bx = max(0, (term_w - BOX_W) // 2)
        by = max(0, (term_h - 22) // 2)

        def row(y, text, attr, centre=False):
            x = bx + 2 + (max(0, inner_w - len(text)) // 2 if centre else 0)
            try:
                stdscr.addstr(by + y, x, text[:inner_w], attr)
            except curses.error:
                pass

        div = "─" * inner_w

        row(0,  heading,                              heading_attr, centre=True)
        row(1,  div,                                  dim)
        row(2,  "",                                   0)
        row(3,  f"{player.name}",                     bold, centre=True)
        row(4,  f"{player.race}  {player.char_class}", panel, centre=True)
        row(5,  "",                                   0)
        row(6,  div,                                  dim)
        row(7,  f"  Site          {site_name}",       panel)
        row(8,  f"  Outcome       {outcome_str}",     panel)
        row(9,  f"  Deepest floor {player.max_floor_reached}", panel)
        row(10, div,                                  dim)
        row(11, "",                                   0)
        row(12, f"  Enemies killed   {player.enemies_killed}", yellow)
        row(13, f"  Items collected  {player.items_found}",    yellow)
        row(14, f"  Total XP         {total_xp}",              yellow)
        row(15, f"  Final level      {player.level}",          yellow)
        row(16, f"  Credits          {player.credits} cr",     yellow)
        row(17, "",                                   0)
        row(18, div,                                  dim)
        row(19, "",                                   0)
        row(20, "[ R ] New run          [ Q ] Quit",  bold, centre=True)

        stdscr.refresh()
        key = stdscr.getch()

        if key in (ord('r'), ord('R')):
            return True
        if key in (ord('q'), ord('Q')):
            return False


def show_hacking_interface(stdscr, player, terminal, current_floor, explored,
                           enemies_on_map, items_on_map, special_rooms,
                           tiles, px, py, visible, log, terminals_on_map,
                           current_theme):
    """Hacking terminal interface. Returns True if a turn was consumed."""
    hack_lv = player.skills.get('hacking', 0)
    BOX_W   = 62
    inner_w = BOX_W - 4

    ACTIONS = [
        (0, "Read log",         "always available"),
        (1, "Map fragment",     "Hacking 1"),
        (2, "Disable units",    "Hacking 2"),
        (3, "Unlock vault",     "Hacking 3"),
        (4, "Alert protocol",   "Hacking 4"),
        (5, "Remote access",    "Hacking 5"),
    ]

    # Success rate for levels 1-5
    def _success_rate():
        return max(15, min(90, 60 + (player.tech - 5) * 8 - current_floor * 3))

    def _draw_box(sel):
        term_h, term_w = stdscr.getmaxyx()
        box_h = 2 + 3 + len(ACTIONS) + 2   # borders + header rows + actions + footer row + dividers
        box_y = max(0, (term_h - box_h) // 2)
        box_x = max(0, (term_w - BOX_W) // 2)

        term_attr  = curses.color_pair(COLOR_TERMINAL) | curses.A_BOLD
        panel_attr = curses.color_pair(COLOR_PANEL)
        dark_attr  = curses.color_pair(COLOR_DARK) | curses.A_DIM
        sel_attr   = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD

        def hline(row):
            try:
                stdscr.addch(row, box_x, curses.ACS_LTEE, term_attr)
                for bx in range(1, BOX_W - 1):
                    stdscr.addch(row, box_x + bx, curses.ACS_HLINE, term_attr)
                stdscr.addch(row, box_x + BOX_W - 1, curses.ACS_RTEE, term_attr)
            except curses.error:
                pass

        def border_row(row):
            try:
                stdscr.addch(row, box_x, curses.ACS_VLINE, term_attr)
                stdscr.addch(row, box_x + BOX_W - 1, curses.ACS_VLINE, term_attr)
                stdscr.addstr(row, box_x + 1, ' ' * (BOX_W - 2))
            except curses.error:
                pass

        # Top border
        try:
            title_str = " TERMINAL ACCESS "
            pad = BOX_W - 2 - len(title_str)
            left = pad // 2
            right = pad - left
            stdscr.addch(box_y, box_x, curses.ACS_ULCORNER, term_attr)
            for bx in range(1, left + 1):
                stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, term_attr)
            stdscr.addstr(box_y, box_x + left + 1, title_str, term_attr)
            for bx in range(left + 1 + len(title_str), BOX_W - 1):
                stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, term_attr)
            stdscr.addch(box_y, box_x + BOX_W - 1, curses.ACS_URCORNER, term_attr)
        except curses.error:
            pass

        # Terminal title row
        row = box_y + 1
        border_row(row)
        tname = terminal.title[:inner_w + 2]
        try:
            stdscr.addstr(row, box_x + 2, tname, term_attr)
        except curses.error:
            pass

        # Info row
        row = box_y + 2
        border_row(row)
        info = f"  Tech: {player.tech}   Hacking: {hack_lv}   Floor: {current_floor}"
        try:
            stdscr.addstr(row, box_x + 2, info[:inner_w + 2], panel_attr)
        except curses.error:
            pass

        hline(box_y + 3)

        # Action rows
        sr = _success_rate()
        for i, (req_lv, name, hint) in enumerate(ACTIONS):
            row = box_y + 4 + i
            border_row(row)
            locked   = (req_lv > hack_lv)
            selected = (i == sel) and not locked
            if locked:
                prefix = "---"
                rate_s = "[locked]"
                attr   = dark_attr
            elif req_lv == 0:
                prefix = "  >"  if selected else "   "
                rate_s = hint
                attr   = sel_attr if selected else panel_attr
            else:
                prefix = "  >" if selected else "   "
                rate_s = f"[{sr}% success]"
                attr   = sel_attr if selected else panel_attr

            line = f"{prefix} [{req_lv}] {name:<18} {hint:<14} {rate_s}"
            try:
                stdscr.addstr(row, box_x + 2, line[:inner_w + 2], attr)
            except curses.error:
                pass

        hline(box_y + 4 + len(ACTIONS))

        # Footer row
        row = box_y + 4 + len(ACTIONS) + 1
        border_row(row)
        footer = "W/S: select   Enter: execute   Esc: cancel"
        try:
            stdscr.addstr(row, box_x + 2, footer[:inner_w + 2], panel_attr)
        except curses.error:
            pass

        # Bottom border
        bot = box_y + 4 + len(ACTIONS) + 2
        try:
            stdscr.addch(bot, box_x, curses.ACS_LLCORNER, term_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(bot, box_x + bx, curses.ACS_HLINE, term_attr)
            stdscr.addch(bot, box_x + BOX_W - 1, curses.ACS_LRCORNER, term_attr)
        except curses.error:
            pass

        stdscr.refresh()

    from .world import ENEMY_TEMPLATES

    def _fail_spawn():
        scale = 1 + (current_floor - 1) * 0.2
        floors_avail = [(x, y) for y in range(MAP_H) for x in range(MAP_W)
                        if tiles[y][x] == FLOOR
                        and (x, y) not in enemies_on_map and (x, y) != (px, py)]
        if floors_avail:
            for pos in random.sample(floors_avail, min(2, len(floors_avail))):
                t = random.choices(ENEMY_TEMPLATES, weights=current_theme['weights'])[0]
                from .entities import Enemy
                enemies_on_map[pos] = Enemy(
                    name=t['name'], char=t['char'],
                    hp=max(1, int(t['hp'] * scale)), atk=max(1, int(t['atk'] * scale)),
                    dfn=int(t['dfn'] * scale), xp_reward=int(t['xp'] * scale),
                    behaviour=t.get('behaviour', 'melee'))
        log.appendleft("HACK FAILED — security alert triggered!")

    # Find the initially selected row (first unlocked)
    sel = 0

    while True:
        _draw_box(sel)
        key = stdscr.getch()

        if key == 27:           # Esc
            return False
        if key in (ord('w'), curses.KEY_UP):
            for step in range(1, len(ACTIONS)):
                nsel = (sel - step) % len(ACTIONS)
                if ACTIONS[nsel][0] <= hack_lv:
                    sel = nsel
                    break
        elif key in (ord('s'), curses.KEY_DOWN):
            for step in range(1, len(ACTIONS)):
                nsel = (sel + step) % len(ACTIONS)
                if ACTIONS[nsel][0] <= hack_lv:
                    sel = nsel
                    break
        elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
            req_lv = ACTIONS[sel][0]
            if req_lv > hack_lv:
                continue   # locked row, ignore

            # -- Level 0: Read log --
            if req_lv == 0:
                show_terminal(stdscr, terminal)
                tech_xp = max(0, (player.tech - 5) * 5)
                if tech_xp:
                    n_lv, lvl_msg = player.gain_xp(tech_xp)
                    log.appendleft(f"Tech interface: +{tech_xp} XP")
                    if lvl_msg:
                        log.appendleft(lvl_msg)
                return False   # no turn consumed

            # -- Levels 1-5: roll success --
            sr = _success_rate()
            success = random.randint(1, 100) <= sr

            if not success:
                _fail_spawn()
                return True   # turn consumed

            # -- Level 1: Map fragment --
            if req_lv == 1:
                for dy in range(-15, 16):
                    for dx in range(-15, 16):
                        tx2, ty2 = px + dx, py + dy
                        if 0 <= tx2 < MAP_W and 0 <= ty2 < MAP_H and tiles[ty2][tx2] == FLOOR:
                            explored.add((tx2, ty2))
                log.appendleft("Map fragment downloaded.")
                return True

            # -- Level 2: Disable units --
            if req_lv == 2:
                count = 0
                for pos, e in enemies_on_map.items():
                    if pos in visible and e.name in ('Sentry', 'Drone'):
                        apply_effect(e, 'stun', 3)
                        count += 1
                log.appendleft(f"Disabled {count} unit(s) in sensor range.")
                return True

            # -- Level 3: Unlock vault --
            if req_lv == 3:
                vault = next((sr2 for sr2 in special_rooms.values()
                              if sr2['type'] == 'vault' and not sr2['triggered']), None)
                if vault:
                    vault['triggered'] = True
                    rare = [it for it in ITEM_TEMPLATES if it.atk >= 3 or it.dfn >= 3]
                    if rare:
                        avail = list(vault['tiles'])
                        for pos in random.sample(avail, min(4, len(avail))):
                            items_on_map[pos] = copy.copy(random.choice(rare))
                    log.appendleft("Vault override successful. Rare gear inside.")
                else:
                    log.appendleft("No vault found on this floor.")
                return True

            # -- Level 4: Alert protocol --
            if req_lv == 4:
                scale = 1 + (current_floor - 1) * 0.2
                candidates = sorted(
                    [(x, y) for y in range(MAP_H) for x in range(MAP_W)
                     if tiles[y][x] == FLOOR
                     and (x, y) not in enemies_on_map and (x, y) != (px, py)],
                    key=lambda pos: abs(pos[0] - px) + abs(pos[1] - py)
                )
                from .world import ENEMY_TEMPLATES as ET
                from .entities import Enemy as EnemyCls
                for pos in candidates[:3]:
                    t = random.choices(ET, weights=current_theme['weights'])[0]
                    enemies_on_map[pos] = EnemyCls(
                        name=t['name'], char=t['char'],
                        hp=max(1, int(t['hp'] * scale)), atk=max(1, int(t['atk'] * scale)),
                        dfn=int(t['dfn'] * scale), xp_reward=int(t['xp'] * scale),
                        behaviour=t.get('behaviour', 'melee'))
                rare = [it for it in ITEM_TEMPLATES if it.atk >= 3 or it.dfn >= 3]
                if rare:
                    items_on_map[(px, py)] = copy.copy(random.choice(rare))
                log.appendleft("ALERT PROTOCOL — reinforcements converging. Rare cache unlocked.")
                return True

            # -- Level 5: Remote access --
            if req_lv == 5:
                others = [(pos, t2) for pos, t2 in terminals_on_map.items()
                          if not t2.read and pos != (px, py)]
                if not others:
                    log.appendleft("No unread terminals on this floor.")
                    return False
                # Show remote picker sub-menu
                rpick = 0
                while True:
                    term_h, term_w = stdscr.getmaxyx()
                    pbox_h = 2 + 2 + len(others) + 1
                    pbox_y = max(0, (term_h - pbox_h) // 2)
                    pbox_x = max(0, (term_w - BOX_W) // 2)
                    term_attr  = curses.color_pair(COLOR_TERMINAL) | curses.A_BOLD
                    panel_attr = curses.color_pair(COLOR_PANEL)
                    sel_attr   = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD

                    def _prow(row):
                        try:
                            stdscr.addch(row, pbox_x, curses.ACS_VLINE, term_attr)
                            stdscr.addch(row, pbox_x + BOX_W - 1, curses.ACS_VLINE, term_attr)
                            stdscr.addstr(row, pbox_x + 1, ' ' * (BOX_W - 2))
                        except curses.error:
                            pass

                    try:
                        rtitle = " REMOTE ACCESS — Select Terminal "
                        rpad   = BOX_W - 2 - len(rtitle)
                        rleft  = rpad // 2
                        stdscr.addch(pbox_y, pbox_x, curses.ACS_ULCORNER, term_attr)
                        for bx in range(1, rleft + 1):
                            stdscr.addch(pbox_y, pbox_x + bx, curses.ACS_HLINE, term_attr)
                        stdscr.addstr(pbox_y, pbox_x + rleft + 1, rtitle, term_attr)
                        for bx in range(rleft + 1 + len(rtitle), BOX_W - 1):
                            stdscr.addch(pbox_y, pbox_x + bx, curses.ACS_HLINE, term_attr)
                        stdscr.addch(pbox_y, pbox_x + BOX_W - 1, curses.ACS_URCORNER, term_attr)
                    except curses.error:
                        pass

                    _prow(pbox_y + 1)
                    try:
                        stdscr.addstr(pbox_y + 1, pbox_x + 2,
                                      "W/S: select   Enter: read   Esc: cancel"[:inner_w + 2],
                                      panel_attr)
                    except curses.error:
                        pass

                    try:
                        stdscr.addch(pbox_y + 2, pbox_x, curses.ACS_LTEE, term_attr)
                        for bx in range(1, BOX_W - 1):
                            stdscr.addch(pbox_y + 2, pbox_x + bx, curses.ACS_HLINE, term_attr)
                        stdscr.addch(pbox_y + 2, pbox_x + BOX_W - 1, curses.ACS_RTEE, term_attr)
                    except curses.error:
                        pass

                    for oi, (opos, ot) in enumerate(others):
                        orow = pbox_y + 3 + oi
                        _prow(orow)
                        prefix = "  >" if oi == rpick else "   "
                        label  = f"{prefix} {ot.title[:inner_w - 1]}"
                        attr   = sel_attr if oi == rpick else panel_attr
                        try:
                            stdscr.addstr(orow, pbox_x + 2, label[:inner_w + 2], attr)
                        except curses.error:
                            pass

                    pbot = pbox_y + 3 + len(others)
                    try:
                        stdscr.addch(pbot, pbox_x, curses.ACS_LLCORNER, term_attr)
                        for bx in range(1, BOX_W - 1):
                            stdscr.addch(pbot, pbox_x + bx, curses.ACS_HLINE, term_attr)
                        stdscr.addch(pbot, pbox_x + BOX_W - 1, curses.ACS_LRCORNER, term_attr)
                    except curses.error:
                        pass

                    stdscr.refresh()
                    pk = stdscr.getch()

                    if pk == 27:
                        return False
                    if pk in (ord('w'), curses.KEY_UP):
                        rpick = (rpick - 1) % len(others)
                    elif pk in (ord('s'), curses.KEY_DOWN):
                        rpick = (rpick + 1) % len(others)
                    elif pk in (curses.KEY_ENTER, ord('\n'), ord('\r')):
                        chosen_t = others[rpick][1]
                        tech_xp  = max(0, (player.tech - 5) * 5)
                        show_terminal(stdscr, chosen_t)
                        if tech_xp:
                            n_lv, lvl_msg = player.gain_xp(tech_xp)
                            log.appendleft(f"Tech interface: +{tech_xp} XP")
                            if lvl_msg:
                                log.appendleft(lvl_msg)
                        log.appendleft("Remote access successful.")
                        return True


def show_cascade_modal(stdscr, player):
    """Full-screen HADES-7 transmission shown when corruption peaks at 100."""
    msgs = random.sample(_CASCADE_HADES7, min(3, len(_CASCADE_HADES7)))
    term_h, term_w = stdscr.getmaxyx()
    stdscr.erase()

    BOX_W   = min(64, term_w - 2)
    inner_w = BOX_W - 4
    bx      = max(0, (term_w - BOX_W) // 2)
    by      = max(0, (term_h - 18) // 2)

    warn  = curses.color_pair(COLOR_ENEMY)    | curses.A_BOLD
    panel = curses.color_pair(COLOR_PANEL)    | curses.A_BOLD
    dim   = curses.color_pair(COLOR_DARK)     | curses.A_DIM
    hades = curses.color_pair(COLOR_TERMINAL) | curses.A_BOLD

    def row(y, text, attr):
        try:
            stdscr.addstr(by + y, bx, f"  {text[:inner_w]:<{inner_w}}  ", attr)
        except curses.error:
            pass

    row(0,  "=" * inner_w,                                       warn)
    row(1,  "    >>>   RESONANCE CASCADE TRIGGERED   <<<",        warn)
    row(2,  "=" * inner_w,                                       warn)
    row(3,  "",                                                   0)
    row(4,  "SIGNAL STRENGTH:    [\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588]  CRITICAL",  warn)
    row(5,  "NEURAL INTEGRITY:   [\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591]  CRITICAL",  warn)
    row(6,  "COGNITIVE LINK:     [\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588]  SATURATED", warn)
    row(7,  "",                                                   0)
    for i, msg in enumerate(msgs):
        row(8 + i, f"[HADES-7]  {msg}",                          hades)
    row(8 + len(msgs),  "",                                       0)
    row(9 + len(msgs),  "-" * inner_w,                            panel)
    row(10 + len(msgs), "",                                       0)
    row(11 + len(msgs), "Neural buffer force-purged. Residual interference will persist.", dim)
    clarity = max(5, 65 - player.mind * 4)
    row(12 + len(msgs), f"Estimated cognitive recovery: {clarity}% compromised.",         dim)
    row(13 + len(msgs), "",                                       0)
    row(14 + len(msgs), "                    [ press any key ]",  panel)

    stdscr.refresh()
    stdscr.getch()


def show_win_screen(stdscr, player):
    """Victory screen. Returns True to play again, False to quit."""
    panel_attr  = curses.color_pair(COLOR_TERMINAL)
    header_attr = curses.color_pair(COLOR_TARGET) | curses.A_BOLD

    while True:
        term_h, term_w = stdscr.getmaxyx()
        stdscr.erase()

        lines = [
            ("* SIGNAL ANSWERED *",                          header_attr),
            ("",                                             0),
            ("You reached the Signal Source.",               panel_attr),
            ("You answered.",                                panel_attr),
            ("Whatever was asking — it listened.",           panel_attr),
            ("The transmission ends.",                       panel_attr),
            ("",                                             0),
            (f"Name:   {player.name}",                      panel_attr),
            (f"Race:   {player.race}",                      panel_attr),
            (f"Class:  {player.char_class}",                panel_attr),
            ("",                                             0),
            (f"Level reached: {player.level}",              panel_attr),
            ("",                                             0),
            ("R: new character    Q: quit",                  panel_attr),
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


def show_ship_screen(stdscr, player, sites, current_site=None):
    """Hub screen showing ship status.
    Returns 'exit' (leave ship at current location), 'nav', 'restart', or 'quit'."""
    panel_attr  = curses.color_pair(COLOR_PANEL)
    header_attr = panel_attr | curses.A_BOLD
    dim_attr    = curses.color_pair(COLOR_DARK) | curses.A_DIM

    while True:
        term_h, term_w = stdscr.getmaxyx()
        stdscr.erase()

        lines = [
            ("THE MERIDIAN",                                          header_attr),
            ("",                                                      0),
            (f"  Pilot: {player.name}",                              panel_attr),
            (f"  {player.race} {player.char_class}  Lvl {player.level}", panel_attr),
            ("",                                                      0),
            (f"  HP:    {player.hp} / {player.max_hp}",              panel_attr),
            (f"  CR:    {player.credits}",                            panel_attr),
            (f"  Fuel:  {player.fuel}",                               panel_attr),
            ("",                                                      0),
            ("  Location:",                                           header_attr),
        ]

        if current_site:
            status = " [cleared]" if current_site.cleared else ""
            lines.append((f"  {current_site.name}{status}", panel_attr))
            lines.append(("  " + current_site.desc[:40],   dim_attr))
        else:
            lines.append(("  In orbit — no destination set.", dim_attr))

        lines += [
            ("",                                                      0),
        ]
        if current_site:
            lines.append(("  [X] Exit Ship",                         panel_attr))
        lines += [
            ("  [N] Navigation Computer",                            panel_attr),
            ("  [R] New run   [Q] Quit",                             panel_attr),
        ]

        start_row = max(0, (term_h - len(lines)) // 2)
        col_off   = max(0, (term_w - 44) // 2)
        for i, (text, attr) in enumerate(lines):
            try:
                stdscr.addstr(start_row + i, col_off, text[:term_w - col_off - 1], attr)
            except curses.error:
                pass

        stdscr.refresh()
        key = stdscr.getch()

        if key in (ord('x'), ord('X')) and current_site:
            return 'exit'
        if key in (ord('n'), ord('N')):
            return 'nav'
        if key in (ord('r'), ord('R')):
            return 'restart'
        if key in (ord('q'), ord('Q')):
            return 'quit'


def draw_overland(stdscr, overland, player_pos, site_name, player, log, visible):
    """Draw the overland surface map, panel, and log."""
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    map_cols = w - PANEL_W

    tiles    = overland['tiles']
    explored = overland['explored']
    ox, oy   = player_pos

    # Tile colour map
    tile_attrs = {
        OV_OPEN:     curses.color_pair(COLOR_OV_OPEN),
        OV_BLOCK:    curses.color_pair(COLOR_WALL)   | curses.A_BOLD,
        OV_TREE:     curses.color_pair(COLOR_OV_FOREST) | curses.A_DIM,
        OV_LANDING:  curses.color_pair(COLOR_TERMINAL)  | curses.A_BOLD,
        OV_ENTRANCE: curses.color_pair(COLOR_STAIR)     | curses.A_BOLD,
    }

    for ty in range(min(MAP_H, h - LOG_LINES)):
        for tx in range(min(MAP_W, map_cols)):
            pos = (tx, ty)
            if pos not in explored:
                continue
            ch   = tiles[ty][tx]
            attr = tile_attrs.get(ch, curses.color_pair(COLOR_FLOOR))
            if pos not in visible:
                attr = curses.color_pair(COLOR_DARK) | curses.A_DIM
            try:
                stdscr.addch(ty, tx, ch, attr)
            except curses.error:
                pass

    # Draw player
    try:
        stdscr.addch(oy, ox, PLAYER,
                     curses.color_pair(COLOR_PLAYER) | curses.A_BOLD)
    except curses.error:
        pass

    # Right panel
    panel_col = w - PANEL_W
    p_attr    = curses.color_pair(COLOR_PANEL)
    hd_attr   = p_attr | curses.A_BOLD
    hp_attr   = (curses.color_pair(COLOR_HP_LOW) | curses.A_BOLD
                 if player.hp <= player.max_hp // 4 else p_attr)
    panel_lines = [
        ("SURFACE",                              hd_attr),
        (None, 0),
        (site_name[:PANEL_W - 1],               p_attr),
        (None, 0),
        (f"HP:  {player.hp:>3} / {player.max_hp:<3}", hp_attr),
        (f"Cr:  {player.credits}",              p_attr),
        (f"Fuel:{player.fuel}",                 p_attr),
        (None, 0),
        ("WASD: move",                          p_attr),
        (">: enter dungeon",                    p_attr),
        ("B: back to ship",                     p_attr),
    ]
    for i, (text, attr) in enumerate(panel_lines):
        if text is None:
            continue
        try:
            stdscr.addstr(i, panel_col + 1, text[:PANEL_W - 2], attr)
        except curses.error:
            pass

    # Log
    log_start = h - LOG_LINES
    log_list  = list(log)
    for i in range(LOG_LINES):
        msg = log_list[i] if i < len(log_list) else ''
        try:
            stdscr.addstr(log_start + i, 0, msg[:map_cols - 1],
                          curses.color_pair(COLOR_PANEL))
        except curses.error:
            pass

    stdscr.refresh()


def show_nav_computer(stdscr, player, sites):
    """Site selection menu. W/S navigate, Enter travel, Esc back.
    Returns selected Site or None."""
    panel_attr  = curses.color_pair(COLOR_PANEL)
    header_attr = panel_attr | curses.A_BOLD
    dim_attr    = panel_attr | curses.A_DIM
    sel_attr    = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD
    err_attr    = curses.color_pair(COLOR_HP_LOW)

    cur = 0
    msg = ""

    while True:
        term_h, term_w = stdscr.getmaxyx()
        stdscr.erase()

        title    = "NAV COMPUTER — Choose destination"
        nav_hint = "W/S: navigate   Enter: travel   Esc: back"
        try:
            stdscr.addstr(1, max(0, (term_w - len(title)) // 2), title, header_attr)
            stdscr.addstr(2, max(0, (term_w - len(nav_hint)) // 2), nav_hint, dim_attr)
        except curses.error:
            pass

        start_col = max(0, (term_w - 62) // 2)
        for i, site in enumerate(sites):
            row        = 4 + i * 2
            can_afford = player.fuel >= site.fuel_cost
            if site.cleared:
                status = "[cleared]"
            elif not can_afford:
                need   = site.fuel_cost - player.fuel
                status = f"[need {need} more fuel]"
            else:
                status = "[available]"
            cost_str = f"cost: {site.fuel_cost}"
            text = f"[{site.char}] {site.name:<22} {cost_str:<10} {status}"
            prefix = "> " if i == cur else "  "
            attr   = sel_attr if i == cur else (dim_attr if not can_afford else panel_attr)
            try:
                stdscr.addstr(row, start_col, (prefix + text)[:term_w - start_col - 1], attr)
                if site.desc:
                    stdscr.addstr(row + 1, start_col + 4,
                                  site.desc[:term_w - start_col - 5], dim_attr)
            except curses.error:
                pass

        if msg:
            msg_row = 4 + len(sites) * 2 + 1
            try:
                stdscr.addstr(msg_row, start_col, msg[:term_w - start_col - 1], err_attr)
            except curses.error:
                pass

        stdscr.refresh()
        key = stdscr.getch()

        if key == 27:
            return None
        if key in (curses.KEY_UP, ord('w'), ord('W')):
            cur = max(0, cur - 1)
            msg = ""
        elif key in (curses.KEY_DOWN, ord('s'), ord('S')):
            cur = min(len(sites) - 1, cur + 1)
            msg = ""
        elif key in (curses.KEY_ENTER, 10, 13):
            site = sites[cur]
            if player.fuel < site.fuel_cost:
                msg = f"Not enough fuel. Need {site.fuel_cost}, have {player.fuel}."
            else:
                return site
