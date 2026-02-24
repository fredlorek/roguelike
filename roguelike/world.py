"""Dungeon generation, scatter functions, FOV, A*, effects — zero curses."""

import collections
import copy
import heapq
import random

from .constants import *
from .entities import Room, Item, Enemy, Terminal, Site
from .data import ITEM_TEMPLATES, LORE_POOL, SHOP_STOCK
from .lore_gen import generate_terminal


ENEMY_TEMPLATES = [
    {'name': 'Drone',    'char': 'd', 'hp': 8,  'atk': 3,  'dfn': 0, 'xp': 10, 'behaviour': 'melee'},
    {'name': 'Sentry',   'char': 'S', 'hp': 15, 'atk': 5,  'dfn': 2, 'xp': 25, 'behaviour': 'melee'},
    {'name': 'Stalker',  'char': 'X', 'hp': 22, 'atk': 7,  'dfn': 1, 'xp': 40, 'behaviour': 'melee'},
    {'name': 'Gunner',   'char': 'G', 'hp': 12, 'atk': 6,  'dfn': 0, 'xp': 30, 'behaviour': 'ranged'},
    {'name': 'Lurker',   'char': 'L', 'hp': 14, 'atk': 5,  'dfn': 0, 'xp': 35, 'behaviour': 'fast'},
    {'name': 'Brute',    'char': 'B', 'hp': 35, 'atk': 10, 'dfn': 3, 'xp': 60, 'behaviour': 'brute'},
    {'name': 'Exploder', 'char': 'E', 'hp': 10, 'atk': 4,  'dfn': 0, 'xp': 20, 'behaviour': 'exploder'},
]

# Floor themes: keyed by (min_floor, max_floor)
THEME_DATA = {
    (1,  3):  {'name': 'Operations Deck',
               'wall_cp': COLOR_WALL,
               'msg': None,
               'weights': [5, 3, 1, 2, 1, 0, 2],
               'gen': {'max_rooms': 30, 'min_rw': 5, 'max_rw': 12, 'min_rh': 4, 'max_rh': 9}},
    (4,  6):  {'name': 'Research Wing',
               'wall_cp': COLOR_WALL_2,
               'msg': "Emergency lighting only. The station is badly damaged.",
               'weights': [2, 5, 2, 3, 2, 1, 2],
               'gen': {'max_rooms': 25, 'min_rw': 4, 'max_rw': 10, 'min_rh': 3, 'max_rh': 8}},
    (7,  9):  {'name': 'Sublevel Core',
               'wall_cp': COLOR_WALL_3,
               'msg': "The signal is overwhelming. Something is very wrong here.",
               'weights': [1, 2, 5, 2, 3, 2, 1],
               'gen': {'max_rooms': 20, 'min_rw': 3, 'max_rw': 9, 'min_rh': 3, 'max_rh': 7}},
    (10, 10): {'name': 'Signal Source',
               'wall_cp': COLOR_WALL_4,
               'msg': "You feel it in your bones. You have arrived.",
               'weights': [0, 1, 4, 1, 3, 3, 1],
               'gen': {'max_rooms': 15, 'min_rw': 6, 'max_rw': 14, 'min_rh': 5, 'max_rh': 11}},
}


def get_theme(floor_num):
    for (lo, hi), data in THEME_DATA.items():
        if lo <= floor_num <= hi:
            return data
    return list(THEME_DATA.values())[-1]  # fallback to deepest theme


def scatter_enemies(tiles, floor_num, n, exclude=(), weights=None):
    floors = [(x, y) for y in range(MAP_H) for x in range(MAP_W)
              if tiles[y][x] == FLOOR and (x, y) not in exclude]
    positions = random.sample(floors, min(n, len(floors)))
    scale = 1 + (floor_num - 1) * 0.2   # +20% stats per floor
    result = {}
    for pos in positions:
        t = random.choices(ENEMY_TEMPLATES, weights=weights)[0]
        result[pos] = Enemy(
            name=t['name'], char=t['char'],
            hp=max(1, int(t['hp'] * scale)),
            atk=max(1, int(t['atk'] * scale)),
            dfn=int(t['dfn'] * scale),
            xp_reward=int(t['xp'] * scale),
            behaviour=t.get('behaviour', 'melee'),
        )
    return result


def generate_dungeon(max_rooms=30, min_rw=5, max_rw=12, min_rh=4, max_rh=9):
    tiles = [[WALL] * MAP_W for _ in range(MAP_H)]
    rooms = []

    for _ in range(max_rooms):
        w = random.randint(min_rw, max_rw)
        h = random.randint(min_rh, max_rh)
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


def scatter_terminals(tiles, n=2, exclude=(), floor_num=1):
    floors = [(x, y) for y in range(MAP_H) for x in range(MAP_W)
              if tiles[y][x] == FLOOR and (x, y) not in exclude]
    positions = random.sample(floors, min(n, len(floors)))
    result = {}
    for i, pos in enumerate(positions):
        if i % 2 == 0:
            # Even slots: authored story beats from LORE_POOL
            title, lines = random.choice(LORE_POOL)
        else:
            # Odd slots: procedurally generated ambient entry
            title, lines = generate_terminal(floor_num)
        result[pos] = Terminal(title, lines)
    return result


def scatter_hazards(tiles, floor_num, n=0, exclude=()):
    """Place hazard tiles. Returns {(x,y): hazard_dict} or {} if n=0."""
    if n <= 0:
        return {}
    hazard_types   = ['mine', 'acid', 'electric']
    hazard_weights = [40, 30, 30]
    floors    = [(x, y) for y in range(MAP_H) for x in range(MAP_W)
                 if tiles[y][x] == FLOOR and (x, y) not in exclude]
    positions = random.sample(floors, min(n, len(floors)))
    result = {}
    for pos in positions:
        htype = random.choices(hazard_types, weights=hazard_weights)[0]
        hdata = HAZARD_DATA[htype]
        result[pos] = {
            'type':          htype,
            'char':          hdata['char'],
            'triggers_left': hdata['triggers'],
            'revealed':      False,
        }
    return result


def scatter_special_rooms(tiles, rooms, floor_num, is_final=False):
    """Pick interior rooms and assign special types. Returns dict keyed by int -> spec dict."""
    if is_final:
        return {}
    interior = rooms[1:-1]  # skip start room and stair/boss room
    if not interior:
        return {}

    n      = min(2, len(interior))
    chosen = random.sample(interior, n)

    pool = ['shop', 'armory', 'medbay', 'terminal_hub', 'vault']
    if floor_num <= 3:
        pool = [t for t in pool if t != 'vault']
    random.shuffle(pool)

    specials = {}
    for i, room in enumerate(chosen):
        rtype = pool[i % len(pool)]
        room_tiles = frozenset(
            (x, y)
            for y in range(room.y1, room.y2)
            for x in range(room.x1, room.x2)
            if tiles[y][x] == FLOOR
        )
        spec = {'type': rtype, 'tiles': room_tiles, 'triggered': False}
        if rtype == 'shop':
            sample_size = min(7, len(SHOP_STOCK))
            spec['stock'] = [(copy.copy(item), price)
                             for item, price in random.sample(SHOP_STOCK, sample_size)]
        specials[i] = spec

    return specials


def make_floor(floor_num, theme_fn=None, enemy_density=1.0, is_final=False, place_boss=False):
    theme_fn = theme_fn or get_theme
    theme    = theme_fn(floor_num)
    tiles, rooms = generate_dungeon(**theme['gen'])
    if rooms:
        start = rooms[0].center()
    else:
        start = (MAP_W // 2, MAP_H // 2)

    stair_up   = start   # floor 1: marks exit back to overland; floors 2+: stair tile
    stair_down = None if is_final else (rooms[-1].center() if rooms else start)

    exclude_set = {stair_up, stair_down, start} - {None}
    n_enemies = int((3 + floor_num * 2) * enemy_density)
    if n_enemies > 0:
        enemies = scatter_enemies(tiles, floor_num, n=n_enemies,
                                  exclude=exclude_set, weights=theme['weights'])
    else:
        enemies = {}

    # Boss floor: place the boss in the last room
    if place_boss and rooms:
        boss_pos = rooms[-1].center()
        scale    = 1 + (floor_num - 1) * 0.2
        enemies[boss_pos] = Enemy(
            name='HADES-7 Remnant', char='H',
            hp=int(100 * scale), atk=int(12 * scale), dfn=int(3 * scale),
            xp_reward=500, boss=True,
        )
        exclude_set = exclude_set | {boss_pos}

    items     = scatter_items(tiles, exclude=exclude_set | set(enemies.keys()))
    terminals = scatter_terminals(tiles, exclude=exclude_set | set(enemies.keys()),
                                  floor_num=floor_num)

    special_rooms = scatter_special_rooms(tiles, rooms, floor_num, is_final=is_final)

    # Clear enemies/items/terminals from special room tiles (safe zones)
    all_special_tiles: set = set()
    for sr in special_rooms.values():
        all_special_tiles |= sr['tiles']
    for pos in list(enemies.keys()):
        if pos in all_special_tiles:
            del enemies[pos]
    for pos in list(items.keys()):
        if pos in all_special_tiles:
            del items[pos]
    for pos in list(terminals.keys()):
        if pos in all_special_tiles:
            del terminals[pos]

    if floor_num <= 2:
        n_hazards = 0
    elif floor_num <= 5:
        n_hazards = random.randint(0, 2)
    else:
        n_hazards = random.randint(1, 3)
    hazards = scatter_hazards(
        tiles, floor_num, n=n_hazards,
        exclude=exclude_set | set(enemies) | set(items) | all_special_tiles)

    return {
        'tiles':         tiles,
        'start':         start,
        'stair_up':      stair_up,
        'stair_down':    stair_down,
        'items':         items,
        'enemies':       enemies,
        'terminals':     terminals,
        'explored':      set(),
        'special_rooms': special_rooms,
        'hazards':       hazards,
    }


def _frontier_theme(f):
    return {**get_theme(1), 'name': 'Frontier Town'}


def _calyx_theme(f):
    return {**get_theme(min(f, 3)),
            'name': ['Cargo Hold', 'Crew Deck', 'Bridge', 'Reactor'][f - 1]}


def _colony_theme(f):
    return {**get_theme(min(f + 1, 9)),
            'name': ['Surface', 'Sub-Level 1', 'Sub-Level 2',
                     'Bunker', 'Lab', 'Core'][f - 1]}


def make_sites():
    """Create a fresh list of Site objects for a new run."""
    return [
        Site('Erebus Station',   'E', depth=10, fuel_cost=0,
             desc='ISC research station. Origin of the signal.'),

        Site('Frontier Town',    'T', depth=1,  fuel_cost=1,
             desc='Rough settlement. Supplies available.',
             enemy_density=0.0,
             theme_fn=_frontier_theme),

        Site('Wreck: ISC Calyx', 'W', depth=4,  fuel_cost=2,
             desc='Drifting hulk. Security drones still active.',
             enemy_density=1.4,
             theme_fn=_calyx_theme),

        Site('Colony Ruin KE-7', 'C', depth=6,  fuel_cost=2,
             desc='Abandoned colony. Something moved in.',
             theme_fn=_colony_theme),
    ]


# ── Supplementary POI theme functions (must be module-level for pickle) ───────

def _erebus_sensor_theme(f):
    return {**get_theme(min(f + 2, 6)), 'name': f'Sensor Array L{f}'}


def _frontier_mine_theme(f):
    names = ['Mine Entrance', 'Deep Vein']
    return {**get_theme(1), 'name': names[min(f - 1, len(names) - 1)]}


def _calyx_pods_theme(f):
    return {**_calyx_theme(1), 'name': 'Emergency Bay'}


def _colony_bunker_theme(f):
    names = ['Bunker Access', 'Lower Vault', 'Core Shelter']
    return {**get_theme(min(f + 3, 9)), 'name': names[min(f - 1, len(names) - 1)]}


# ── Per-site biome terrain configs ────────────────────────────────────────────

_BIOME_CONFIGS = {
    'Erebus Station': {
        'ground': '.', 'impassable': OV_BLOCK, 'feature': OV_CRYSTAL,
        'water': OV_WATER, 'n_impassable': 40, 'n_feature': 35, 'n_water': 18,
    },
    'Frontier Town': {
        'ground': OV_OPEN, 'impassable': OV_BLOCK, 'feature': OV_SHRUB,
        'water': None, 'n_impassable': 18, 'n_feature': 50, 'n_water': 0,
    },
    'Wreck: ISC Calyx': {
        'ground': '.', 'impassable': OV_BLOCK, 'feature': OV_SCRAP,
        'water': None, 'n_impassable': 55, 'n_feature': 25, 'n_water': 0,
    },
    'Colony Ruin KE-7': {
        'ground': OV_OPEN, 'impassable': OV_BLOCK, 'feature': OV_TREE,
        'water': OV_WATER, 'n_impassable': 22, 'n_feature': 60, 'n_water': 10,
    },
}
_DEFAULT_BIOME = {
    'ground': OV_OPEN, 'impassable': OV_BLOCK, 'feature': OV_TREE,
    'water': None, 'n_impassable': 20, 'n_feature': 20, 'n_water': 0,
}

# ── Per-site POI specs (main POI is always first, is_main=True) ───────────────

_POI_SPECS = {
    'Erebus Station': [
        {'label': 'Main Station',   'is_main': True,  'char': '>', 'type': 'dungeon'},
        {'label': 'Sensor Array',   'is_main': False, 'char': '[', 'type': 'facility',
         'depth': 2, 'enemy_density': 0.6, 'theme_fn': _erebus_sensor_theme,
         'desc': 'Signal monitoring outpost.'},
    ],
    'Frontier Town': [
        {'label': 'Settlement',     'is_main': True,  'char': '+', 'type': 'town'},
        {'label': 'Abandoned Mine', 'is_main': False, 'char': '>', 'type': 'dungeon',
         'depth': 2, 'enemy_density': 1.0, 'theme_fn': _frontier_mine_theme,
         'desc': 'Old excavation. Something moved in.'},
    ],
    'Wreck: ISC Calyx': [
        {'label': 'Main Wreck',     'is_main': True,  'char': '>', 'type': 'dungeon'},
        {'label': 'Emergency Bay',  'is_main': False, 'char': '[', 'type': 'facility',
         'depth': 1, 'enemy_density': 0.4, 'theme_fn': _calyx_pods_theme,
         'desc': 'Sealed emergency compartment.'},
    ],
    'Colony Ruin KE-7': [
        {'label': 'Colony Ruins',   'is_main': True,  'char': '>', 'type': 'dungeon'},
        {'label': 'Bunker',         'is_main': False, 'char': '>', 'type': 'dungeon',
         'depth': 3, 'enemy_density': 1.5, 'theme_fn': _colony_bunker_theme,
         'desc': 'Military hardened shelter. Heavy resistance.'},
    ],
}

# ── Overland terrain helpers ──────────────────────────────────────────────────

def _grow_terrain(tiles, char, total, n_seeds=None):
    """Grow terrain regions via random walk to create large sweeping features."""
    if total <= 0:
        return
    if n_seeds is None:
        n_seeds = max(2, total // 12)
    per_seed = max(1, total // n_seeds)
    for _ in range(n_seeds):
        x = random.randint(2, MAP_W - 3)
        y = random.randint(2, MAP_H - 3)
        placed = 0
        for _step in range(per_seed * 6):
            if 1 <= x < MAP_W - 1 and 1 <= y < MAP_H - 1:
                if tiles[y][x] != char:
                    tiles[y][x] = char
                    placed += 1
                    if placed >= per_seed:
                        break
            dx, dy = random.choice([(0,1),(0,-1),(1,0),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)])
            x = max(1, min(MAP_W - 2, x + dx))
            y = max(1, min(MAP_H - 2, y + dy))


def _clear_area(tiles, cx, cy, radius, fill):
    """Clear a square of tiles around (cx, cy) to ensure open ground."""
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < MAP_W and 0 <= ny < MAP_H:
                tiles[ny][nx] = fill


def _find_open_pos(tiles, x1, y1, x2, y2, avoid, min_dist=10):
    """Return an open tile within the rectangle [x1,x2]×[y1,y2] that is at
    least min_dist from every position in avoid."""
    for _ in range(400):
        x = random.randint(x1, x2)
        y = random.randint(y1, y2)
        if tiles[y][x] in OV_IMPASSABLE:
            continue
        if all(abs(x - ax) + abs(y - ay) >= min_dist for ax, ay in avoid):
            return (x, y)
    # Fallback: relax distance constraint
    for _ in range(100):
        x = random.randint(x1, x2)
        y = random.randint(y1, y2)
        if tiles[y][x] not in OV_IMPASSABLE:
            return (x, y)
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def _ensure_path(tiles, start, end, open_char):
    """BFS connectivity check; carve a path if start→end is blocked."""
    visited = {start}
    queue = collections.deque([start])
    while queue:
        cx, cy = queue.popleft()
        if (cx, cy) == end:
            return
        for ndx, ndy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            nx, ny = cx + ndx, cy + ndy
            npos = (nx, ny)
            if (0 <= nx < MAP_W and 0 <= ny < MAP_H
                    and npos not in visited
                    and tiles[ny][nx] not in OV_IMPASSABLE):
                visited.add(npos)
                queue.append(npos)
    # Not connected — carve diagonal-then-straight corridor
    cx, cy = start
    ex, ey = end
    while cx != ex or cy != ey:
        if cx < ex:   cx += 1
        elif cx > ex: cx -= 1
        if cy < ey:   cy += 1
        elif cy > ey: cy -= 1
        if tiles[cy][cx] in OV_IMPASSABLE:
            tiles[cy][cx] = open_char


# ── Overland map generation ───────────────────────────────────────────────────

def generate_overland(site_name):
    """Generate a planet-surface overland map with biome terrain and multiple POIs.
    Returns dict: tiles, player_start, pois, explored."""
    biome = _BIOME_CONFIGS.get(site_name, _DEFAULT_BIOME)

    # Fill with base ground, then grow terrain regions
    tiles = [[biome['ground']] * MAP_W for _ in range(MAP_H)]
    _grow_terrain(tiles, biome['impassable'], biome['n_impassable'])
    if biome.get('feature') and biome.get('n_feature', 0) > 0:
        _grow_terrain(tiles, biome['feature'], biome['n_feature'])
    if biome.get('water') and biome.get('n_water', 0) > 0:
        _grow_terrain(tiles, biome['water'], biome['n_water'],
                      n_seeds=max(1, biome['n_water'] // 20))

    # Place landing pad (top-left area) with clearance
    lx = random.randint(3, 12)
    ly = random.randint(3, 8)
    _clear_area(tiles, lx, ly, 2, biome['ground'])
    tiles[ly][lx] = OV_LANDING

    # Place POIs: main in bottom-right, supplementary in centre/other quadrants
    poi_specs = _POI_SPECS.get(site_name, [])
    quadrants = [
        (MAP_W // 2, MAP_H // 2, MAP_W - 5, MAP_H - 4),      # bottom-right: main
        (MAP_W // 4, MAP_H // 4, 3 * MAP_W // 4, 3 * MAP_H // 4),  # centre: secondary
        (5, MAP_H // 2, MAP_W // 2, MAP_H - 4),               # bottom-left: tertiary
    ]
    avoid = [(lx, ly)]
    pois = []

    for i, spec in enumerate(poi_specs):
        x1, y1, x2, y2 = quadrants[min(i, len(quadrants) - 1)]
        pos = _find_open_pos(tiles, x1, y1, x2, y2, avoid, min_dist=12)
        px, py = pos
        _clear_area(tiles, px, py, 1, biome['ground'])
        avoid.append(pos)

        poi = {
            'pos':     pos,
            'char':    spec['char'],
            'type':    spec['type'],
            'label':   spec['label'],
            'is_main': spec.get('is_main', False),
        }
        if not spec.get('is_main'):
            poi['site'] = Site(
                name=spec['label'],
                char=spec['char'],
                depth=spec['depth'],
                desc=spec.get('desc', ''),
                fuel_cost=0,
                enemy_density=spec.get('enemy_density', 1.0),
                theme_fn=spec.get('theme_fn'),
            )
        pois.append(poi)

    # Ensure every POI is reachable from the landing pad
    for poi in pois:
        _ensure_path(tiles, (lx, ly), poi['pos'], biome['ground'])

    return {
        'tiles':        tiles,
        'player_start': (lx, ly),
        'pois':         pois,
        'explored':     set(),
    }


def find_path(tiles, start, goal, blocked):
    """A* on the floor grid. blocked: set of (x,y) that cannot be entered.
    goal is always reachable even if in blocked (so enemies can attack the player).
    Returns a list of (x,y) steps not including start, or [] if unreachable."""
    if start == goal:
        return []

    def h(pos):
        return abs(pos[0] - goal[0]) + abs(pos[1] - goal[1])

    open_heap = [(h(start), 0, start)]
    came_from = {start: None}
    g_score   = {start: 0}

    while open_heap:
        _, g, pos = heapq.heappop(open_heap)

        if pos == goal:
            path, cur = [], pos
            while cur != start:
                path.append(cur)
                cur = came_from[cur]
            path.reverse()
            return path

        if g > g_score.get(pos, float('inf')):
            continue

        x, y = pos
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            nx, ny = x + dx, y + dy
            npos   = (nx, ny)
            if not (0 <= nx < MAP_W and 0 <= ny < MAP_H):
                continue
            if tiles[ny][nx] != FLOOR:
                continue
            if npos in blocked and npos != goal:
                continue
            ng = g + 1
            if ng < g_score.get(npos, float('inf')):
                g_score[npos]   = ng
                came_from[npos] = pos
                heapq.heappush(open_heap, (ng + h(npos), ng, npos))

    return []


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


def apply_effect(entity, effect, turns):
    """Apply or refresh a status effect (keeps max remaining turns).
    Player's Survival skill reduces duration by 1 per skill level (min 1)."""
    if hasattr(entity, 'skills'):
        turns = max(1, turns - entity.skills.get('survival', 0))
    entity.active_effects[effect] = max(entity.active_effects.get(effect, 0), turns)


def tick_effects(entity, label):
    """Tick active effects one turn. Returns list of message strings."""
    msgs = []
    expired = []
    for effect, turns in list(entity.active_effects.items()):
        if effect in EFFECT_DAMAGE:
            dmg = EFFECT_DAMAGE[effect]
            entity.hp -= dmg
            msgs.append(f"{label} takes {dmg} {effect} damage!")
        elif effect == 'repair':
            if hasattr(entity, 'max_hp') and entity.hp < entity.max_hp:
                heal = min(5, entity.max_hp - entity.hp)
                entity.hp += heal
                msgs.append(f"Repair Drone: +{heal} HP.")
        entity.active_effects[effect] = turns - 1
        if turns - 1 <= 0:
            expired.append(effect)
    for e in expired:
        del entity.active_effects[e]
        if e == 'stim':
            apply_effect(entity, 'stun', 1)
            msgs.append(f"{label}: stimpack crash — stunned!")
        elif e == 'repair':
            pass   # no expiry message for repair drone
        else:
            msgs.append(f"{label} is no longer affected by {e}.")
    return msgs
