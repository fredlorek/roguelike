# CLAUDE.md — Roguelike Project

## Quick Start

```
python3 -m roguelike
python3 -m py_compile roguelike/constants.py roguelike/entities.py roguelike/data.py \
    roguelike/world.py roguelike/ui.py roguelike/game.py roguelike/__main__.py \
    roguelike/lore_gen.py
```

Sci-fi dungeon crawler. Player pilots *The Meridian* to named sites, explores procedurally
generated floors, returns to ship between runs. Win condition: defeat HADES-7 on Erebus fl. 10
(ending sequence not yet built — boss kill currently just sets `site.cleared = True`).

---

## Package Structure

```
roguelike/
  __main__.py     # Entry point + save system: main(), SAVE_PATH, save_game(), load_game(),
                  #   delete_save(), show_continue_screen(); curses.wrapper entry point
  constants.py    # All named constants and lookup tables; zero imports
  entities.py     # Data classes: Player, Item, Enemy, Site, Room, Terminal; zero curses
  data.py         # Static content: ITEM_TEMPLATES, SHOP_STOCK, LORE_POOL, WIN_TERMINAL
  world.py        # Pure logic: dungeon gen, scatter_*, make_floor, FOV, A*, apply_effect,
                  #   tick_effects, make_sites, _frontier_theme, _calyx_theme, _colony_theme;
                  #   zero curses
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

`show_continue_screen` lives in `__main__.py` (not `ui.py`) because it needs `SAVE_PATH`.

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
3. Outer loop: `main()` → check save → `show_continue_screen()` or `show_character_creation()`
   → `show_ship_screen()` ↔ `show_nav_computer()` → `run_site()` → ship

### Save system (`__main__.py`)
- `SAVE_PATH` = `~/.roguelike/save.pkl` (Linux/Mac) or `%APPDATA%\.roguelike\save.pkl` (Windows)
- Format: `pickle({'player': Player, 'sites': [Site, ...]})` — full game state in one dict
- **Save** after `run_site` returns `'escaped'`; also on ship-screen quit (`Q`)
- **Delete** after `run_site` returns `'dead'` or `'restart'`
- `show_continue_screen` shows `[C] Continue / [N] New Game / [Q] Quit` with player name/level
- Atomic write: write to `.tmp` then `Path.replace()` to avoid corruption on crash
- **Pickle constraint**: `Site.theme_fn` must be a named module-level function — lambdas are
  not picklable. Named theme fns: `_frontier_theme`, `_calyx_theme`, `_colony_theme` in `world.py`

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
| `main(stdscr)` | __main__ | outer coordinator; save/load orchestration |

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
- **Key attrs**: `player.level`, `player.name`, `player.fuel`, `player.credits`,
  `player.skills` (dict), `player.active_effects` (dict), `player.equipment` (dict)

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
| HADES-7 Remnant | H | melee | boss; kill sets `site.cleared = True` |

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

- **No external dependencies** — stdlib only (`curses`, `copy`, `random`, `heapq`, `collections`,
  `pickle`, `pathlib`, `os`, `sys`)
- **Curses isolation** — `entities.py` and `world.py` import zero curses; all rendering in `ui.py`
- **In-place mutation for persistence** — never replace `items_on_map` or `explored` with new
  objects on an active floor; mutate them so `Site.floors` cache stays live
- **`curses.error` suppression** — all `addch`/`addstr` calls wrapped in `try/except curses.error`
- **Floor geometry** — `stair_down = rooms[-1].center()`; `stair_up = rooms[0].center()`;
  floor 1 has `stair_up = None`; final floors have `stair_down = None`
- **Theme functions** — `theme_fn` must be a named module-level function (not a lambda);
  lambdas break `pickle`. Use `{**get_theme(n), ...}` pattern to inherit all required keys.

---

## Next Up

### 1. In-game help screen (`?` key)
Add `show_help_screen(stdscr)` to `ui.py`. Handle `?` in `run_site` (non-turn-consuming,
like minimap). Display the controls table in a full-screen modal; `?` or Esc to close.
No state changes needed — pure rendering.

### 2. High score table
Store top 10 runs in `~/.roguelike/scores.json` (same dir as save). Record on
death/restart/quit-after-visiting-a-site. Fields: `name, level, kills, floors, site, outcome, date`.
Show from startup screen with a `[H] High Scores` option. Sort by `max_floor_reached` then `kills`.
Add `record_score(player, site_name, outcome)` helper to `__main__.py` alongside save helpers.

### 3. Difficulty setting at character creation
Add a step to `show_character_creation` (after background, before point-buy). Choices:
Easy / Normal / Hard. Store as `player.difficulty` (string). Apply multipliers in `run_site`
when calling `make_floor`: Hard → `enemy_density *= 1.5`, starting fuel 2, credits 0;
Easy → `enemy_density *= 0.7`, +10 max HP, starting credits 50. No changes to `make_floor`
signature — adjust density on the `site` object or pass inline.

### 4. Erebus ending sequence
After HADES-7 is killed, `run_site` currently returns `'escaped'` with `site.cleared = True`.
Add a `show_erebus_ending(stdscr, player)` in `ui.py`: final HADES-7 terminal message,
escape sequence, win screen with run stats. `run_site` should return a new `'won'` result
when the boss floor is cleared; `main()` handles `'won'` by calling the ending screen,
deleting the save, then returning to startup (no new run offered automatically).

---

## Build

```sh
# Linux / Mac
./build.sh

# Windows
build.bat
```

Both scripts run `pyinstaller --onefile --name "The Meridian" roguelike/__main__.py`.
Windows additionally installs `windows-curses`. Output: `dist/The Meridian[.exe]`.

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
