# CLAUDE.md — Roguelike Project

## Overview
Terminal roguelike written in Python using `curses`. Core game logic lives in `roguelike.py`.
Procedural lore content lives in `lore_gen.py` (the intentional exception to single-file convention).

Run: `python3 roguelike.py`
Syntax check: `python3 -m py_compile roguelike.py && python3 -m py_compile lore_gen.py`

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
- **Single file (with one exception)** — all game logic goes in `roguelike.py`; do not split into modules. `lore_gen.py` is the deliberate exception: it is the content layer (word banks, procedural lore) and has **no curses dependency** — edit it freely without touching game logic
- **In-place mutation for persistence** — use `.pop()`, `|=`, etc. on `items_on_map` and `explored`; never replace them with new objects while on an active floor
- **`curses.error` suppression** — all `addch`/`addstr` calls are wrapped in `try/except curses.error` to handle terminal edge cases (last cell, small windows)
- Stair positions are room centers: `stair_down = rooms[-1].center()`, `start/stair_up = rooms[0].center()`
- Floor 1 has `stair_up = None`; floors > 1 have `stair_up = start`

## To-Do: Path to Playable

Items ordered by impact on the core game loop. The first few fix the biggest gaps in
moment-to-moment feel; later items add depth and replayability.

1. **Enemy variety and unique behaviours** — only 3 enemy types exist (Drone, Sentry, Stalker),
   all of which just walk up and melee. Add 3–4 more types per theme zone with distinct
   behaviours: a ranged shooter that keeps distance, a fast Stalker variant that moves twice per
   turn, a heavy Brute that is slow but hits hard, an Exploder that deals splash damage on death.
   This is the single biggest gap in combat feel.

2. **Richer level-up rewards** — levelling up currently only grants +5 max HP. Add an ATK or DEF
   bonus per level, or show a small modal letting the player put a point into one of their five
   stats. Without this, the XP/level system feels inert.

3. **Status effects** — add poison, burn, and stun as conditions that enemies (and traps) can
   inflict, and that the player can inflict via consumables. Store active effects on `Player` and
   `Enemy` and tick them at the start of each turn. This makes every combat decision matter more.

4. **Consumable variety** — the inventory has med-patches, medkits, and nano-injects, all of which
   just heal. Add a handful of tactically distinct items: a Smoke Grenade (blocks LOS for 3 turns),
   an EMP Charge (disables all Drones and Sentries in FOV for 2 turns), a Scanner Chip (reveals
   full floor map). These give players choices beyond "heal or don't heal."

5. **Traps and hazardous tiles** — introduce a small set of floor hazards placed by `make_floor`:
   tripwire mines, acid puddles, and electric floor panels. They raise the cost of careless
   movement and reward careful play. Traps can also be disarmed by high Tech stat, giving that
   stat more moment-to-moment expression.

6. **Signal corruption mechanic** — floors 7–10 are narratively the most dire, but mechanically
   identical to floor 1. Add a per-turn "signal interference" counter that grows on deep floors
   and causes escalating effects: random stat penalties, brief FOV flickering, phantom enemy
   sounds in the message log. This makes the theme tangible without adding new systems.

7. **Minimap overlay** — the `explored` set is already tracked per floor. Add an `M` key that
   draws a full-screen greyscale overview of the explored map so the player can orient themselves.
   This is pure rendering work with no logic changes.

8. **Hacking mechanic for terminals** — the Mind stat currently has limited expression. Let the
   player "jack in" to a terminal (costs a turn) for a bonus that scales with Mind: low Mind just
   reads the log, high Mind can disable nearby enemies, unlock a vault for free, or reveal the
   floor map. Terminals become interactive rewards rather than passive flavour.

9. **Run summary screen** — after winning or dying, show a recap: floors reached, enemies killed,
   items found, XP earned, cause of death. This closes the feedback loop and makes each run feel
   like it has a concrete shape. The data is all available on `Player` already — just needs
   tallying and a display function alongside `show_game_over`.

10. **Difficulty and challenge modes** — add a difficulty selector to character creation (Normal /
    Hard / Ironman). Hard increases enemy ATK/HP by 25% and halves shop credits. Ironman prevents
    the `R` key from resetting the dungeon — death is permanent. These are small constant
    multipliers that dramatically extend replayability without new content.

---

## Long-term Plan

### Goal
Build a sci-fi RPG with procedurally generated story elements, a full game universe, graphics, and sound — starting small and iterating.

### Technology path
- **Now:** Python + `curses` for prototyping game systems (combat, inventory, world gen, story)
- **Later:** Port rendering layer to `pygame` or `pygame-ce` for 2D graphics and sound
- Both are free and open source (LGPL) — no commercial restrictions on selling the game
- Python is the permanent language choice (career cross-applicability; no C#/C++)

### Porting strategy
Game logic and rendering are deliberately kept separate:
- Pure logic (`Player`, `Item`, `Room`, dungeon gen, FOV, floor caching) has no curses dependency and ports untouched
- Only the rendering layer (`draw`, `draw_panel`, `show_equipment_screen`) gets replaced with pygame equivalents
- The game loop structure stays the same

### Principles
- Nail the systems first (mechanics, world gen, story, economy) before worrying about graphics
- Keep logic and rendering decoupled as features are added
- Iterate: prove something works in curses, then it's safe to build on

## Controls
| Key | Action |
|---|---|
| WASD / Arrow keys | Move |
| `>` tile (walk onto) | Descend one floor |
| `<` tile (walk onto) | Ascend one floor |
| `I` | Open equipment screen |
| `R` | New dungeon (resets floors, keeps player equipment) |
| `Q` | Quit |
