# CLAUDE.md — Roguelike Project

## Quick Start

```
python3 -m roguelike
python3 -m py_compile roguelike/constants.py roguelike/entities.py roguelike/data.py \
    roguelike/world.py roguelike/ui.py roguelike/game.py roguelike/__main__.py \
    roguelike/lore_gen.py
```

Sci-fi dungeon crawler. Player pilots *The Meridian* to named sites, explores procedurally
generated floors, returns to ship between runs. No hard win condition.

---

## Package Structure

```
roguelike/
  __main__.py     # Entry point: python3 -m roguelike; main() + curses.wrapper
  constants.py    # All named constants and lookup tables; zero imports
  entities.py     # Data classes: Player, Item, Enemy, Site, Room, Terminal; zero curses
  data.py         # Static content: ITEM_TEMPLATES, SHOP_STOCK, LORE_POOL, WIN_TERMINAL
  world.py        # Pure logic: dungeon gen, scatter_*, make_floor, FOV, A*, apply_effect,
                  #   tick_effects, make_sites; zero curses
  ui.py           # All curses code: draw, draw_panel, show_minimap, show_equipment_screen,
                  #   show_shop_screen, show_targeting, show_character_creation,
                  #   show_skill_levelup_modal, show_skills_screen, show_levelup_modal,
                  #   show_run_summary, show_hacking_interface, show_cascade_modal,
                  #   show_ship_screen, show_nav_computer
  game.py         # Game loop: enemy_turn, run_site; all UI calls prefixed ui.*
  lore_gen.py     # Procedural lore: word banks, generate_terminal; no curses
```

`entities.py` and `world.py` have zero curses imports — they are the pygame-portable core.
All curses usage lives in `ui.py` (rendering) and `game.py` (key codes only).

`apply_effect` and `tick_effects` live in `world.py` so both `game.py` and `ui.py` can
import them without a circular dependency.

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
| Function | Module | Purpose |
|---|---|---|
| `generate_dungeon()` | world | BSP room placement + corridor carving → `(tiles, rooms)` |
| `make_floor(n, ...)` | world | dungeon gen + scatter; returns floor state dict |
| `scatter_enemies / items / terminals / special_rooms / hazards` | world | populate a fresh floor |
| `compute_fov(tiles, px, py, radius)` | world | Bresenham ray-cast → visible tile set |
| `find_path(tiles, start, goal, blocked)` | world | A* for enemy AI |
| `apply_effect(entity, name, duration)` | world | add/extend a status effect |
| `tick_effects(entity, label)` | world | advance status effects one turn → messages |
| `enemy_turn(...)` | game | move/attack all enemies; handles smoke, mines, AI |
| `run_site(stdscr, site, player)` | game | dungeon loop → `'escaped'`/`'dead'`/`'restart'` |
| `draw(...)` | ui | full redraw: map + panel + log |
| `draw_panel(...)` | ui | right-side stats; tool, FX, signal bar |
| `show_minimap(...)` | ui | `M` key full-screen floor map; WASD to pan |
| `show_hacking_interface(...)` | ui | `H` key terminal modal → True if turn consumed |
| `show_cascade_modal(...)` | ui | HADES-7 transmission at corruption peak |
| `show_character_creation(stdscr)` | ui | 6-step creation wizard → `Player` |
| `show_run_summary(...)` | ui | post-death/restart recap screen |
| `show_ship_screen(...)` | ui | hub: ship status, site list |
| `show_nav_computer(...)` | ui | site selection; deducts fuel |
| `main(stdscr)` | __main__ | outer coordinator |

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
- **Curses isolation** — `entities.py` and `world.py` import zero curses; all rendering in `ui.py`
- **In-place mutation for persistence** — never replace `items_on_map` or `explored` with new
  objects on an active floor; mutate them so `Site.floors` cache stays live
- **`curses.error` suppression** — all `addch`/`addstr` calls wrapped in `try/except curses.error`
- **Floor geometry** — `stair_down = rooms[-1].center()`; `stair_up = rooms[0].center()`;
  floor 1 has `stair_up = None`; final floors have `stair_down = None`
- **Theme inheritance** — `theme_fn` lambdas use `{**get_theme(n), ...}` to carry all required keys

---

## Next Up

### 1. Save games
`pickle` the game state: `Player`, `[Site]`, position, current floor.
Save to `~/.roguelike/save.pkl` (`%APPDATA%` on Windows). Auto-save on clean exit;
delete on death. `Continue` option on main menu when save exists.

### 2. Windows executable
`pip install pyinstaller windows-curses` then:
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
