# CLAUDE.md — Roguelike Project

## Quick Start

```
python3 roguelike.py
python3 -m py_compile roguelike.py && python3 -m py_compile lore_gen.py
```

Sci-fi dungeon crawler. Player pilots *The Meridian* to named sites, explores procedurally
generated floors, returns to ship between runs. No hard win condition.

---

## Architecture

### Key constants
| Constant | Value | Purpose |
|---|---|---|
| `MAP_W / MAP_H` | 80 / 40 | tile grid |
| `PANEL_W` | 20 | right-hand stats panel (incl. border) |
| `FOV_RADIUS` | 8 | base LOS radius (extended by Mind + Cartography) |
| `MAX_FLOOR` | 10 | Erebus Station depth |
| `LOG_LINES` | 4 | message log rows |
| `POINT_BUY_POINTS` | 20 | stat points at character creation |
| `STARTING_SKILL_POINTS` | 4 | free skill points at creation |
| `SKILL_MAX` | 5 | max level per skill |
| `CORRUPTION_MAX` | 100 | signal corruption ceiling (Erebus floors 7–10) |

### Data flow
1. `make_floor(n, theme_fn, enemy_density, is_final, place_boss)` → floor state dict
2. `Site.floors` dict caches visited floors; in-place mutation auto-persists
3. Outer loop: `main()` → `show_character_creation()` → `show_ship_screen()` ↔ `show_nav_computer()` → `run_site()` → ship

### Core functions
| Function | Purpose |
|---|---|
| `generate_dungeon()` | BSP room placement + corridor carving → `(tiles, rooms)` |
| `make_floor(n, ...)` | dungeon gen + scatter; returns floor state dict |
| `scatter_enemies / items / terminals / special_rooms / hazards` | populate a fresh floor |
| `compute_fov(tiles, px, py, radius)` | Bresenham ray-cast → visible tile set |
| `find_path(tiles, start, goal, blocked)` | A* for enemy AI |
| `enemy_turn(...)` | move/attack all enemies; handles smoke, mines, AI behaviours |
| `tick_effects(entity, label)` | advance status effects one turn → messages |
| `draw(...)` | full redraw: map + panel + log; accepts `smoke_tiles`, `corruption` |
| `draw_panel(...)` | right-side stats; shows tool, FX, signal bar |
| `show_minimap(...)` | `M` key full-screen floor map; WASD to pan |
| `run_site(stdscr, site, player)` | dungeon loop → `'escaped'`/`'dead'`/`'restart'` |
| `show_ship_screen(...)` | hub: ship status, site list |
| `show_nav_computer(...)` | site selection; deducts fuel |
| `show_character_creation(stdscr)` | 6-step creation wizard → `Player` |
| `show_hacking_interface(...)` | `H` key terminal modal → True if turn consumed |
| `show_cascade_modal(stdscr, player)` | HADES-7 transmission at corruption peak |
| `main(stdscr)` | outer coordinator |

### Sites
| Site | Floors | Fuel | Notes |
|---|---|---|---|
| Erebus Station | 10 | 0 | Main story; HADES-7 boss fl.10; signal corruption fl.7+ |
| Frontier Town | 1 | 1 | Supply stop; no enemies |
| Wreck: ISC Calyx | 4 | 2 | Drone/Sentry heavy (1.4× density) |
| Colony Ruin KE-7 | 6 | 2 | Balanced mix |

### Player
- **Stats** (5, point-buy 20): Body → HP/melee ATK; Reflex → dodge; Mind → XP multiplier/FOV; Tech → ranged ATK; Presence → intimidate/discounts
- **Skills** (12, lv 0–5): Melee, Firearms, Tactics, Engineering, Hacking, Electronics, Pilot, Cartography, Survival, Intimidation, Barter, Medicine
- **Backgrounds**: Soldier (Melee 1 + Tactics 1), Engineer (Engineering 1 + Electronics 1), Medic (Medicine 1 + Survival 1), Hacker (Hacking 1 + Cartography 1)
- **Equipment slots** (6): weapon, armor, helmet, gloves, boots, tool
- **Status effects**: poison, burn, stun, repair, stim

### Enemies
| Name | Char | Behaviour | Special |
|---|---|---|---|
| Drone | d | melee | — |
| Sentry | S | melee | stun on-hit |
| Stalker | X | melee | poison on-hit |
| Gunner | G | ranged | retreats when close; burn on-hit |
| Lurker | L | fast (2 moves) | — |
| Brute | B | brute (cooldown) | stun on-hit |
| Exploder | E | melee | AoE on death |
| HADES-7 Remnant | H | melee | boss; kill clears Erebus |

### Items of note
| Category | Items |
|---|---|
| Tools (`X` key) | Bypass Kit (eng 1), Signal Jammer (elec 1), Grapple Line, Repair Drone (eng 1) |
| Consumables (`U` key) | Medkit, Grenade, Sensor Kit, Smoke Grenade, EMP Charge, Scanner Chip, Stimpack, Proximity Mine |
| Other | Fuel Cell, ranged/melee weapons, armor, helmets, gloves, boots |

### Special rooms
`shop`, `armory`, `medbay`, `terminal_hub`, `vault` — placed by `scatter_special_rooms`;
not on final floors. Shop stock drawn from `SHOP_STOCK`; armory scatters gear items.

### Signal corruption (Erebus fl. 7–10)
`corruption` (0–100) increments each move: `max(1, 3 - (mind-5)//2 - hacking//3)`.
Terminal hacks reduce it by 30. Tiers: Whisper (25) → Interference (50) → Cascade (75)
→ Resonance (100: modal + reset to 40 + stun). FOV flicker is render-only (`visible_draw`).

---

## Conventions

- **No external dependencies** — stdlib only (`curses`, `copy`, `random`, `heapq`, `collections`)
- **Single file (transitioning)** — currently `roguelike.py` + `lore_gen.py`; next milestone
  splits into a package (see Next Up). New code should keep curses out of logic functions.
- **In-place mutation for persistence** — never replace `items_on_map` or `explored` with new
  objects on an active floor; mutate them so `Site.floors` cache stays live
- **`curses.error` suppression** — all `addch`/`addstr` calls wrapped in `try/except curses.error`
- **Floor geometry** — `stair_down = rooms[-1].center()`; `stair_up = rooms[0].center()`;
  floor 1 has `stair_up = None`; final floors have `stair_down = None`
- **Theme inheritance** — `theme_fn` lambdas use `{**get_theme(n), ...}` to carry all required keys

---

## Next Up

Planned order (each unblocks the next):

### 1. Run summary screen
Show a recap after death or run-end: site, floors reached, enemies killed, XP, cause of death.
Needs kill/floor counters on `Player`. `show_run_summary()` alongside `show_game_over()`.

### 2. Reorganize into a package
Split `roguelike.py` into:
```
roguelike/
  __main__.py   # entry: python3 -m roguelike
  constants.py  # MAP_W/H, COLOR_*, HAZARD_DATA, corruption pools
  data.py       # ITEM_TEMPLATES, SHOP_STOCK, LORE_POOL, WIN_TERMINAL, SKILLS
  entities.py   # Player, Item, Enemy, Site, Room, Terminal  — zero curses
  world.py      # dungeon gen, scatter_*, make_floor, FOV, A*  — zero curses
  ui.py         # all draw/show_* functions  — all curses here
  lore_gen.py   # unchanged
```
`entities.py` and `world.py` must import zero curses — they become the pygame-portable core.

### 3. Save games
After reorganization (module paths must be stable before serializing).
`pickle` the game state: `Player`, `[Site]`, position, current floor.
Save to `~/.roguelike/save.pkl` (`%APPDATA%` on Windows). Auto-save on clean exit;
delete on death. `Continue` option on main menu when save exists.

### 4. Windows executable
After codebase is stable. `pip install pyinstaller windows-curses` then:
```
pyinstaller --onefile --name "The Meridian" roguelike/__main__.py
```
Keep a `.spec` file in the repo. Test on a clean Windows machine (no Python).

---

## Controls

### In a site
| Key | Action |
|---|---|
| WASD / Arrows | Move / melee attack |
| `>` / `<` (walk onto) | Descend / ascend floor |
| `B` | Back to ship (floor 1 only) |
| `I` | Equipment screen |
| `K` | Skills screen (spend banked SP) |
| `M` | Minimap overlay (WASD pan, M/Esc close) |
| `H` | Hack terminal / remote-pick (Hacking 5) |
| `E` | Disarm trap (Engineering 2+) |
| `U` | Use first consumable |
| `X` | Activate equipped tool |
| `F` | Fire ranged weapon (Tab cycles targets) |
| `T` | Open shop (in Supply Depot) |
| `R` | New run |
| `Q` | Back to ship |

### Ship / nav computer
| Key | Action |
|---|---|
| `N` | Navigation computer |
| W / S | Navigate site list |
| Enter | Travel to site |
| Esc | Back |
| `R` | New run |
| `Q` | Quit |
