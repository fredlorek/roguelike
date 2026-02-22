# CLAUDE.md — Roguelike Project

## Overview
Single-file terminal roguelike written in Python using `curses`. All game logic lives in `roguelike.py`.

Run: `python3 roguelike.py`
Syntax check: `python3 -m py_compile roguelike.py`

## Architecture

### Key constants
- `MAP_W = 80`, `MAP_H = 40` — tile grid dimensions
- `PANEL_W = 20` — right-hand stats panel width (including border)
- `FOV_RADIUS = 8` — line-of-sight radius

### Data flow
1. `make_floor(floor_num)` generates a floor dict: `tiles`, `start`, `stair_up`, `stair_down`, `items`, `explored`
2. `floors` dict (keyed by floor number) caches all visited floors for persistence
3. `items_on_map` and `explored` are mutable — in-place mutation propagates to the cache automatically (no explicit save step)

### Core functions
| Function | Purpose |
|---|---|
| `generate_dungeon()` | BSP-style room placement + corridor carving; returns `(tiles, rooms)` |
| `make_floor(n)` | Wraps `generate_dungeon` + `scatter_items`; returns floor state dict |
| `scatter_items(tiles, n, exclude)` | Places `n` random items, skipping `exclude` positions |
| `compute_fov(tiles, px, py)` | Bresenham ray-cast FOV; returns visible tile set |
| `draw(...)` | Full redraw: map, panel, status bar |
| `draw_panel(...)` | Right-side stats panel (floor, HP, level, XP, ATK, DEF) |
| `show_equipment_screen(...)` | Modal inventory/equip UI |
| `main(stdscr)` | Game loop: input → movement → stair traversal → FOV → draw |

### Color pairs
| Constant | Index | Color | Used for |
|---|---|---|---|
| `COLOR_WALL` | 1 | White | `#` tiles |
| `COLOR_FLOOR` | 2 | Black | `.` tiles (visible) |
| `COLOR_PLAYER` | 3 | Yellow | `@` |
| `COLOR_PANEL` | 4 | Cyan | Stats panel |
| `COLOR_HP_LOW` | 5 | Red | HP when ≤ 25% |
| `COLOR_DARK` | 6 | White+DIM | Explored-but-dark tiles |
| `COLOR_ITEM` | 7 | Green | Items on map |
| `COLOR_STAIR` | 8 | Magenta | `>` / `<` stairs |

## Conventions
- **No external dependencies** — stdlib only (`curses`, `copy`, `random`)
- **Single file** — all changes go in `roguelike.py`; do not split into modules
- **In-place mutation for persistence** — use `.pop()`, `|=`, etc. on `items_on_map` and `explored`; never replace them with new objects while on an active floor
- **`curses.error` suppression** — all `addch`/`addstr` calls are wrapped in `try/except curses.error` to handle terminal edge cases (last cell, small windows)
- Stair positions are room centers: `stair_down = rooms[-1].center()`, `start/stair_up = rooms[0].center()`
- Floor 1 has `stair_up = None`; floors > 1 have `stair_up = start`

## Controls
| Key | Action |
|---|---|
| WASD / Arrow keys | Move |
| `>` tile (walk onto) | Descend one floor |
| `<` tile (walk onto) | Ascend one floor |
| `I` | Open equipment screen |
| `R` | New dungeon (resets floors, keeps player equipment) |
| `Q` | Quit |
