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
| Technical | Hacking | Terminal depth (future item 3) |
| Technical | Electronics | Radar/drones (future item 3/4) |
| Navigation | Pilot | -1 fuel cost per 2 levels |
| Navigation | Cartography | +1 FOV radius per 2 levels |
| Navigation | Survival | -1 turn off all status-effect durations/lv |
| Social | Intimidation | +3% enemy hesitation/lv |
| Social | Barter | -5% shop prices/lv (floor 40%) |
| Social | Medicine | +2 HP per heal item use/lv |

- **Background skill bonuses** (pre-seeded at creation, non-removable): Soldier: Melee 1 + Tactics 1; Engineer: Engineering 1 + Electronics 1; Medic: Medicine 1 + Survival 1; Hacker: Hacking 1 + Cartography 1
- `player.skill_points` — banked unspent SP; shown in panel; spent via K key
- **Equipment slots** (5): weapon, armor, helmet, gloves, boots
- **Resources**: HP, XP, credits, fuel
- **Status effects**: poison, burn, stun — applied by enemies and grenades; ticked each turn

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

### 3. Hacking mechanic for terminals

When the player walks onto a terminal tile, pressing `H` (or Enter) opens a hacking
interface instead of just reading the log. The action available scales with the player's
Hacking skill level:
- Level 0: read the log (current behaviour)
- Level 1: download a map fragment (partially reveals `explored`)
- Level 2: disable all Sentries/Drones in FOV for 3 turns
- Level 3: unlock a locked vault without paying credits
- Level 4: trigger a floor-wide alert (enemy density increases, rare loot reward)
- Level 5: remote-access any terminal on the floor from distance

Hacking costs one turn and can fail (based on Tech stat vs. floor level), with a failed
attempt alerting nearby enemies.

---

### 4. Tech gear and tool sets

Add a `'tool'` equipment slot (sixth slot, key `K` to activate). Tools are single-use or
limited-charge active items distinct from consumables:
- **Bypass Kit** — disarms an adjacent trap without triggering it (Engineering gated)
- **Signal Jammer** — stuns all Drones and Sentries in FOV for 2 turns (Electronics gated)
- **Grapple Line** — move through one wall tile; one charge per floor (no skill gate)
- **Repair Drone** — restores 15 HP over 3 turns (Engineering gated)

Tools appear in shops and armory rooms. This gives the Tech/Engineering investment a
moment-to-moment expression beyond the ranged-ATK bonus.

---

### 5. Consumable variety

Add tactically distinct one-use items that broaden decision-making beyond "heal or fight":
- **Smoke Grenade** — creates a `smoke` tile overlay blocking enemy LOS for 3 turns
- **EMP Charge** — stuns all Drones and Sentries in FOV (overlaps with Signal Jammer but
  is a consumable, not a tool; stackable and findable)
- **Scanner Chip** — adds all floor tiles to `explored` (instant minimap)
- **Stimpack** — doubles movement speed (two moves per turn) for 5 turns; adds stun
  afterwards
- **Proximity Mine** — places a triggered explosive on the current tile

---

### 6. Signal corruption mechanic

On Erebus Station floors 7–10, a per-turn `corruption` counter increments each move.
As it rises it triggers escalating effects: dim FOV flicker (reduce radius by 1 for one
turn), phantom enemy sounds in the log, random -1 penalties to a stat for 3 turns. At
maximum corruption the player enters a "resonance cascade" state — the signal is actively
trying to communicate. High Mind stat reduces corruption rate; completing a terminal read
resets the counter. Makes the late-game theme mechanically tangible without a new system.

---

### 7. Minimap overlay

`M` key draws a full-screen greyscale overview of the current floor using the `explored`
set. Walls in dim white, floor in dim black, stairs/items/enemies as coloured glyphs.
Pure rendering — no logic changes. Closes the navigation loop on large floors and rewards
thorough exploration.

---

### 8. Run summary screen

After death (or voluntarily ending a run), show a recap before returning to the ship:
site last visited, floors reached, enemies killed, items found, XP earned, cause of death.
All tallying requires adding a few counters to `Player` (enemies killed, floors visited).
Display function lives alongside `show_game_over`. Closes the feedback loop and gives each
run a concrete shape.

---

### 9. Difficulty and challenge modes

Difficulty selector at character creation: Normal / Hard / Ironman.
- **Hard** — enemy ATK/HP +25%; shop prices +50%; fuel costs +1 per site
- **Ironman** — saves disabled (already the case), `R` (new run) disabled inside a site;
  death is permanent and the game returns to the main menu with no option to continue
A `difficulty` flag on `Player` drives the multipliers; no new systems required.

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
| `E` | Disarm adjacent/current trap (Engineering 2+ required; costs a turn) |
| `U` | Use first consumable (grenades auto-target nearest visible enemy) |
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
