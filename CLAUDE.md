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

## Completed

- **Enemy variety** — Gunner, Lurker, Brute, Exploder with distinct AI and per-type colour coding.
- **Richer level-up rewards** — modal lets player pick a stat to raise; Body recalculates max HP.
- **Status effects** — poison, burn, stun on `Player`/`Enemy`; `tick_effects` runs each turn;
  Stalker/Gunner/Sentry/Brute apply on-hit; Toxin Grenade, Stun Charge, Nano-Antidote added;
  FX row in panel; stun blocks player action for one turn.

## To-Do: Path to Playable

Items ordered by build dependency and impact on moment-to-moment feel.

1. **Run summary screen** — after winning or dying, show a recap: floors reached, enemies killed,
   items found, XP earned, cause of death. Closes the feedback loop so each run has a concrete
   shape. All data is on `Player` already — just needs tallying and a display function alongside
   `show_game_over`.

2. **Consumable variety** — add tactically distinct throwables that use the new status-effect
   system: a Smoke Grenade (blocks LOS for 3 turns), an EMP Charge (inflicts stun on all Drones
   and Sentries in FOV), a Scanner Chip (reveals full floor map). These give players real choices
   beyond "heal or don't heal" and put the grenade-targeting code from step #3 to full use.

3. **Minimap overlay** — the `explored` set is already tracked per floor. Add an `M` key that
   draws a full-screen greyscale overview of the explored map. Pure rendering work, no logic
   changes.

4. **Traps and hazardous tiles** — place tripwire mines, acid puddles, and electric floor panels
   in `make_floor`. Acid/electric apply burn/stun (reusing the status-effect system). Raises the
   cost of careless movement and rewards careful play.

5. **Tech gear and tool sets** — add a `'tool'` equipment slot and a `T` key to activate it: a
   Bypass Kit disarms traps (#4), a Signal Jammer stuns Drones/Sentries in FOV, a Grapple Line
   lets the player move through one wall tile. Gives the Tech stat moment-to-moment expression
   and bridges into the hacking mechanic (#6).

6. **Hacking mechanic for terminals** — let the player "jack in" to a terminal (costs a turn) for
   a Mind-scaled bonus: low Mind reads the log, high Mind can disable nearby enemies, unlock a
   vault, or reveal the floor map. Terminals become interactive rewards rather than passive
   flavour.

7. **Signal corruption mechanic** — add a per-turn interference counter that grows on floors 7–10
   and causes escalating effects: random stat penalties, brief FOV flickering, phantom enemy
   sounds in the log. Makes the late-game theme tangible without adding new systems.

8. **Difficulty and challenge modes** — difficulty selector at character creation (Normal / Hard /
   Ironman). Hard scales enemy ATK/HP by 25% and halves shop credits. Ironman disables `R`.
   Small multipliers that extend replayability without new content.

9. **Procedurally generated overland map** — world map with named sites (derelict ships, colony
   ruins, signal outposts), each its own dungeon with a distinct theme and enemy set. Player
   chooses which site to enter. Requires a `Site` data structure and overland rendering layer.
   Best tackled once per-floor content (items, enemies, effects) is fully solid.

10. **Spaceship as home base** — persistent hub between overland maps: upgrade bays, cargo hold,
    eventually crew NPCs. Travel costs fuel found in dungeons. Turns disconnected runs into an
    ongoing campaign. Architecturally a non-dungeon screen with its own state dict outside
    `floors`.

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
| `U` | Use first consumable (grenades auto-target nearest visible enemy) |
| `F` | Fire ranged weapon (opens targeting cursor) |
| `T` | Open shop (when standing in a Supply Depot) |
| `R` | New dungeon (resets floors, keeps player equipment) |
| `Q` | Quit |
