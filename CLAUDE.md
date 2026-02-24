# CLAUDE.md — Roguelike Project

## Overview

Terminal roguelike written in Python using `curses`. Core game logic lives in `roguelike.py`.
Procedural lore content lives in `lore_gen.py` (the intentional exception to single-file convention).

Run: `python3 roguelike.py`
Syntax check: `python3 -m py_compile roguelike.py && python3 -m py_compile lore_gen.py`

The game is a sci-fi dungeon crawler built around an overworld loop: the player pilots "The
Meridian" to named sites (derelict stations, wrecks, colony ruins), explores them as
procedurally generated dungeon floors, and returns to the ship between runs. No hard win
condition — sites can be cleared but the universe keeps expanding.

---

## Architecture

### Key constants
- `MAP_W = 80`, `MAP_H = 40` — tile grid dimensions
- `PANEL_W = 20` — right-hand stats panel width (including border)
- `FOV_RADIUS = 8` — base line-of-sight radius (extended by Mind + Cartography)
- `MAX_FLOOR = 10` — depth of Erebus Station (the flagship site)
- `LOG_LINES = 4` — message log rows at the bottom
- `POINT_BUY_POINTS = 20` — stat points available at character creation
- `STARTING_SKILL_POINTS = 4` — free skill points allocated in creation Step 4
- `SKILL_MAX = 5` — maximum level for any skill
- `COLOR_HAZARD = 20` — red color pair for hazard tiles (`^`/`~`/`=`)

### Data flow
1. `make_floor(floor_num, theme_fn, enemy_density, is_final, place_boss)` generates a floor dict
2. Each `Site` has a `.floors` dict (keyed by floor number) that persists between visits
3. `items_on_map` and `explored` are mutated in-place — changes propagate to the cache automatically
4. The outer loop is: `main()` → `show_character_creation()` → `show_ship_screen()` ↔
   `show_nav_computer()` → `run_site()` → back to ship

### Core functions
| Function | Purpose |
|---|---|
| `generate_dungeon()` | BSP-style room placement + corridor carving; returns `(tiles, rooms)` |
| `make_floor(n, ...)` | Wraps dungeon gen + item/enemy scatter; returns floor state dict |
| `scatter_enemies / items / terminals / special_rooms / hazards` | Populate a freshly generated floor |
| `compute_fov(tiles, px, py, radius)` | Bresenham ray-cast FOV; returns visible tile set |
| `find_path(tiles, start, goal, blocked)` | A* used by enemy AI |
| `enemy_turn(...)` | Move and attack with every enemy; handles all AI behaviours |
| `tick_effects(entity, label)` | Advance status effects one turn; returns messages |
| `draw(...)` | Full redraw: map, panel, message log |
| `draw_panel(...)` | Right-side stats panel |
| `run_site(stdscr, site, player)` | Dungeon game loop for one site; returns `'escaped'`/`'dead'`/`'restart'` |
| `show_ship_screen(...)` | Hub: ship status, site list, N/R/Q |
| `show_nav_computer(...)` | Site selection; deducts fuel on confirm |
| `make_sites()` | Returns a fresh list of `Site` objects for a new run |
| `show_character_creation(stdscr)` | 6-step wizard; returns configured `Player` |
| `show_skill_levelup_modal(stdscr, player, points=2)` | Spend skill points after level-up; unspent banked |
| `show_skills_screen(stdscr, player)` | K key in-game: read-only overview + spend banked SP |
| `show_hacking_interface(stdscr, player, terminal, ...)` | H key terminal hacking modal; returns True if turn consumed |
| `main(stdscr)` | Outer coordinator: character creation → ship ↔ site loop |

### Sites
| Site | Floors | Fuel | Enemy density | Notes |
|---|---|---|---|---|
| Erebus Station | 10 | 0 | 1.0× | Main story; HADES-7 boss on floor 10 |
| Frontier Town | 1 | 1 | 0 (none) | Supply stop; shops/armory only |
| Wreck: ISC Calyx | 4 | 2 | 1.4× | Drone/Sentry heavy |
| Colony Ruin KE-7 | 6 | 2 | 1.0× | Balanced enemy mix |

### Player character
- **Stats** (5): Body, Reflex, Mind, Tech, Presence — set at creation via point-buy (20 pts)
  - Body → max HP and melee ATK; Reflex → dodge chance; Mind → XP multiplier and FOV radius;
    Tech → ranged ATK bonus; Presence → intimidate chance and shop discounts
- **Skills** (12, levels 0–5): each skill earned at level-up (2 pts/level) or at creation (4 free pts + background bonus)

| Category | Skills | Mechanical effect |
|---|---|---|
| Combat | Melee | +1 melee ATK/lv |
| Combat | Firearms | +1 ranged ATK/lv |
| Combat | Tactics | +2% dodge/lv |
| Technical | Engineering | See traps (lv1), disarm adjacent trap with `E` (lv2) |
| Technical | Hacking | `H` key interface: lv0 read, lv1 map fragment, lv2 disable units, lv3 unlock vault, lv4 alert protocol, lv5 remote access |
| Technical | Electronics | Signal Jammer at lv1 (active via `X` key); Radar/drones (future) |
| Navigation | Pilot | -1 fuel cost per 2 levels |
| Navigation | Cartography | +1 FOV radius per 2 levels |
| Navigation | Survival | -1 turn off all status-effect durations/lv |
| Social | Intimidation | +3% enemy hesitation/lv |
| Social | Barter | -5% shop prices/lv (floor 40%) |
| Social | Medicine | +2 HP per heal item use/lv |

- **Background skill bonuses** (pre-seeded at creation, non-removable): Soldier: Melee 1 + Tactics 1; Engineer: Engineering 1 + Electronics 1; Medic: Medicine 1 + Survival 1; Hacker: Hacking 1 + Cartography 1
- `player.skill_points` — banked unspent SP; shown in panel; spent via K key
- **Equipment slots** (6): weapon, armor, helmet, gloves, boots, tool
- **Resources**: HP, XP, credits, fuel
- **Status effects**: poison, burn, stun, repair, stim — applied by enemies, items, and tools; ticked each turn

### Enemies
| Name | Char | Behaviour | Special |
|---|---|---|---|
| Drone | d | melee | — |
| Sentry | S | melee | stun on-hit |
| Stalker | X | melee | poison on-hit |
| Gunner | G | ranged | retreats when close; burn on-hit |
| Lurker | L | fast (2 moves) | — |
| Brute | B | brute (cooldown) | stun on-hit |
| Exploder | E | melee | AoE detonation on death |
| HADES-7 Remnant | H | melee | boss; kills clear Erebus Station |

### Special rooms
`shop`, `armory`, `medbay`, `terminal_hub`, `vault` — placed in interior rooms by
`scatter_special_rooms`. Not generated on boss/final floors (`is_final=True`).

### Color pairs
Indices 1–19 cover: walls (×4 themed variants), floor, player, panel, HP-low, dark, item,
stair, enemy (×4 behaviour variants), target reticle, terminal, special room floor.

---

## Conventions
- **No external dependencies** — stdlib only (`curses`, `copy`, `random`, `heapq`, `collections`)
- **Single file (with one exception)** — all game logic in `roguelike.py`; `lore_gen.py` is the
  deliberate exception (word banks, procedural lore, no curses dependency)
- **In-place mutation for persistence** — never replace `items_on_map` or `explored` with new
  objects while on an active floor; mutate them directly so the `Site.floors` cache stays live
- **`curses.error` suppression** — all `addch`/`addstr` calls wrapped in `try/except curses.error`
- **Floor geometry** — stair_down = `rooms[-1].center()`; start/stair_up = `rooms[0].center()`;
  floor 1 has `stair_up = None`; final floors (`is_final=True`) have `stair_down = None`
- **Theme inheritance** — custom `theme_fn` lambdas in `make_sites()` use `{**get_theme(n), ...}`
  so they always carry all required keys (`gen`, `weights`, `wall_cp`, `name`, `msg`)

---

## To-Do

Items ordered by dependency and impact. Each item lists what it needs and what it unblocks.

### ~~1. Character development overhaul~~ ✓ DONE

12-skill tree (Melee, Firearms, Tactics, Engineering, Hacking, Electronics, Pilot,
Cartography, Survival, Intimidation, Barter, Medicine) added on top of the 5-stat system.
Point-buy raised to 20. Background classes seed 2 skills at level 1. Creation wizard
expanded to 6 steps with a Skill Allocation step. Level-up grants stat + 2 skill points
via back-to-back modals; unspent points bank to `player.skill_points`. K key opens
`show_skills_screen`. All skills mechanically wired (Engineering/Hacking/Electronics
stubbed pending items 2/3/4).

---

### ~~2. Traps and hazardous tiles~~ ✓ DONE

Tripwire mines (`^`, 1-shot, burn+dmg), acid puddles (`~`, 5-shot, burn), electric panels
(`=`, 4-shot, stun) placed via `scatter_hazards()`. Hidden from Engineering 0 players until
revealed by Sensor Kit or Engineering 1+ (passive visibility in FOV). `E` key disarms at
Engineering 2+. Survival reduces effect duration; dodge_chance gives sidestep message.
`Sensor Kit` consumable (buy from shops, 20 cr) reveals all floor hazards instantly.
`HAZARD_DATA` dict defines all hazard properties. Floors 1-2: none; 3-5: 0-2; 6+: 1-3.

---

### ~~3. Hacking mechanic for terminals~~ ✓ DONE

`H` key on terminal tile opens `show_hacking_interface()`. Actions scale with Hacking level:
lv0 read log (no turn cost), lv1 map fragment (radius 15), lv2 disable Sentries/Drones in
FOV for 3t, lv3 unlock vault without credits, lv4 alert protocol (3 reinforcements + rare
drop), lv5 remote access any unread terminal. Success formula:
`max(15, min(90, 60 + (tech-5)*8 - floor*3))`. Failure spawns 2 reinforcements. Locked rows
shown in grey. Stunned players still waste their turn. Hacking 5 off-terminal: remote picker
shows all unread terminals floor-wide.

---

### ~~4. Tech gear and tool sets~~ ✓ DONE

`'tool'` equipment slot (sixth slot, `X` key to activate). Tools are limited-charge active
items distinct from consumables:
- **Bypass Kit** — disarms an adjacent trap without triggering it (Engineering 1 gated)
- **Signal Jammer** — stuns all Drones and Sentries in FOV for 2 turns (Electronics 1 gated)
- **Grapple Line** — move through one wall tile; one charge per floor (no skill gate); charge
  resets on floor entry
- **Repair Drone** — restores 15 HP over 3 turns via `repair` status effect (Engineering 1 gated)

All appear in shops and armory rooms. `draw_panel()` shows tool name + charges; hint updated
to `[I]Equip [K]Skills [X]Tool`.

---

### ~~5. Consumable variety~~ ✓ DONE

Tactically distinct one-use items added to `ITEM_TEMPLATES` and `SHOP_STOCK`:
- **Smoke Grenade** — `%` tile overlay (radius 3, 3 turns); enemies in smoke do random walk
- **EMP Charge** — stuns all Drones and Sentries in FOV (consumable version of Signal Jammer)
- **Scanner Chip** — adds all non-wall floor tiles to `explored` (instant minimap)
- **Stimpack** — `stim` status: 2 moves/turn for 5 turns; then stun 1t
- **Proximity Mine** — places `prox_mine` hazard on current tile; 12 dmg to any enemy that
  steps on it; one trigger; removed from map on detonation

`smoke_tiles = {(x,y): turns}` dict local to `run_site()`; ticked after each enemy turn;
passed to `enemy_turn()` and `draw()`.

---

### ~~6. Signal corruption mechanic~~ ✓ DONE

`corruption` counter (0–100) in `run_site()`, active on Erebus Station floors 7–10.
Increments each move: `rate = max(1, 3 - (mind-5)//2 - hacking//3)` — high Mind and
Hacking reduce the rate. Terminal hacks that consume a turn reduce corruption by 30.

**Tiers and effects (applied after each move):**
| Range | Tier | Effects |
|---|---|---|
| 0–24 | Clean | none |
| 25–49 | Whisper | 25% chance: phantom sound in log |
| 50–74 | Interference | 40% phantom sound; 12% synaptic burn 1t; 35% FOV flicker (-1 radius, rendering only) |
| 75–99 | Cascade | 60% phantom sound; 22% random stun/burn 1t; FOV always -1 |
| 100 | Resonance | `show_cascade_modal()` + reset to 40 + stun 1t |

**`show_cascade_modal()`**: full-screen HADES-7 transmission overlay — bars showing
SIGNAL/NEURAL/COGNITIVE status, 3 random transmissions from `_CASCADE_HADES7` pool,
estimated cognitive compromise based on Mind stat.

**Panel**: `Sig:████░░░░░░  67%` row added to `draw_panel()` when `corruption > 0`,
colour-coded green < 25%, yellow < 50%, orange < 75%, red ≥ 75%.

**FOV flicker** is rendering-only (`visible_draw` separate from `visible`); AI and
explored tracking always use the full-radius `visible`.

---

### ~~7. Minimap overlay~~ ✓ DONE

`M` key opens `show_minimap()`: full-screen floor view using `explored` set. Walls `#`
in themed dim colour, floor `.` dim, stairs `><` magenta, items green, terminals cyan,
hazards (if known) red, smoke `%` dim, player `@` yellow bold. Enemies shown in their
behaviour colours when currently visible. Special room centroids show a glyph if the
room has been entered: `$` shop, `A` armory, `+` medbay, `H` hub, `V` vault.

Header shows floor name, floor N/site_depth, and exploration % (green ≥80%, yellow ≥50%,
red <50%). WASD / arrows pan the camera; M or Esc closes. Legend row at bottom.

---

### 8. Run summary screen

After death (or voluntarily ending a run), show a recap before returning to the ship:
site last visited, floors reached, enemies killed, items found, XP earned, cause of death.
All tallying requires adding a few counters to `Player` (enemies killed, floors visited).
Display function lives alongside `show_game_over`. Closes the feedback loop and gives each
run a concrete shape.

**Do this first** — small, isolated, no dependencies on the items below.

---

### 9. ~~Difficulty and challenge modes~~ — DROPPED

Removed from scope. May revisit in a later planning session if the game calls for it.

---

### 10. Reorganize into a multi-file package

**Do before save games** — save files encode Python module paths; reorganize first so
those paths are stable.

Split `roguelike.py` into a proper package. Proposed structure:

```
roguelike/
  __main__.py     # entry point: calls main()
  constants.py    # MAP_W/H, COLOR_*, CORRUPTION_MAX, HAZARD_DATA, corruption msg pools
  data.py         # ITEM_TEMPLATES, SHOP_STOCK, LORE_POOL, WIN_TERMINAL, SKILLS
  entities.py     # Player, Item, Enemy, Site, Room, Terminal  (zero curses imports)
  world.py        # dungeon gen, scatter_*, make_floor, FOV, A*, find_path  (zero curses)
  ui.py           # all draw/show_* functions  (all curses usage lives here)
  lore_gen.py     # unchanged
```

**Key discipline**: `entities.py` and `world.py` must have zero curses imports — they
become pure logic and will port to pygame untouched. All curses usage stays in `ui.py`.

Run command becomes `python3 -m roguelike`. Syntax check:
`python3 -m py_compile roguelike/*.py && python3 -m py_compile roguelike/lore_gen.py`

---

### 11. Save games

**Do after reorganization** — stable module paths prevent save-file breakage during
future refactors.

Use `pickle` for simplicity (local single-player game; no security concern). Save the
full game state: `Player`, `[Site]`, `current_site_index`, `px`, `py`, `current_floor`.
The `Site.floors` cache (tiles, enemies, items, explored, hazards) is the bulk of the
data and pickles cleanly since it contains only stdlib types and our own classes.

Save file: `~/.roguelike/save.pkl` (or `%APPDATA%/roguelike/save.pkl` on Windows).
`S` key on the ship screen saves; game auto-saves on clean exit. On death the save is
deleted (permadeath by default). Add a `Continue` option to the main menu when a save
exists.

---

### 12. Windows executable

**Do last** — pure packaging step, easiest when the codebase is otherwise stable.

```
pip install pyinstaller windows-curses
pyinstaller --onefile --name "The Meridian" roguelike/__main__.py
```

`windows-curses` is a drop-in replacement that PyInstaller bundles automatically.
Test the resulting `.exe` on a clean Windows machine (no Python installed) before
shipping. A `.spec` file in the repo controls build options.

---

## Long-term Plan

### Goal
Build a sci-fi RPG with procedurally generated story elements, a full game universe,
graphics, and sound — starting small and iterating in curses.

### Technology path
- **Now:** Python + `curses` for prototyping game systems (combat, inventory, world gen, story)
- **Later:** Port rendering layer to `pygame` or `pygame-ce` for 2D graphics and sound
- Both are free and open source (LGPL); no commercial restrictions on selling the game
- Python is the permanent language choice (career cross-applicability; no C#/C++)

### Porting strategy
Game logic and rendering are deliberately kept separate:
- Pure logic (`Player`, `Item`, `Site`, `Room`, dungeon gen, FOV, A*, floor caching) has no
  curses dependency and ports untouched
- Only the rendering layer (`draw`, `draw_panel`, `show_*` screens) gets replaced with pygame
- The game loop structure (`main` → `run_site`) stays identical
- After reorganization (item 10) this separation is enforced structurally by module
  boundaries: `entities.py` + `world.py` are curses-free by convention and lint rule

### Principles
- Nail the systems first (character, combat, world gen, economy) before worrying about graphics
- Keep logic and rendering decoupled as features are added
- Iterate: prove something works in curses, then it's safe to build on

---

## Controls

### In a site (dungeon)
| Key | Action |
|---|---|
| WASD / Arrow keys | Move / melee attack |
| `>` tile (walk onto) | Descend one floor |
| `<` tile (walk onto) | Ascend one floor |
| `B` | Back to ship (floor 1 only) |
| `I` | Equipment screen |
| `K` | Skills screen (read-only; spend banked SP if any) |
| `M` | Minimap overlay (full-screen floor view; WASD to pan; M/Esc to close) |
| `H` | Hack terminal (on terminal tile) or remote-pick unread terminal (Hacking 5, off-tile) |
| `E` | Disarm adjacent/current trap (Engineering 2+ required; costs a turn) |
| `U` | Use first consumable (grenades auto-target nearest visible enemy) |
| `X` | Activate equipped tool (Bypass Kit / Signal Jammer / Grapple Line / Repair Drone) |
| `F` | Fire ranged weapon (opens targeting cursor; Tab cycles targets) |
| `T` | Open shop (when standing in a Supply Depot) |
| `R` | New run (new character creation) |
| `Q` | Return to ship screen |

### On the ship / nav computer
| Key | Action |
|---|---|
| `N` | Open navigation computer |
| W / S | Navigate site list |
| Enter | Travel to selected site (costs fuel) |
| Esc | Back |
| `R` | New run (new character) |
| `Q` | Quit game |
