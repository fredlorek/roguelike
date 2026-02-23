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
- `FOV_RADIUS = 8` — base line-of-sight radius (extended by Mind stat)
- `MAX_FLOOR = 10` — depth of Erebus Station (the flagship site)
- `LOG_LINES = 4` — message log rows at the bottom

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
| `scatter_enemies / items / terminals / special_rooms` | Populate a freshly generated floor |
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
| `show_character_creation(stdscr)` | 5-step wizard; returns configured `Player` |
| `main(stdscr)` | Outer coordinator: character creation → ship ↔ site loop |

### Sites
| Site | Floors | Fuel | Enemy density | Notes |
|---|---|---|---|---|
| Erebus Station | 10 | 0 | 1.0× | Main story; HADES-7 boss on floor 10 |
| Frontier Town | 1 | 1 | 0 (none) | Supply stop; shops/armory only |
| Wreck: ISC Calyx | 4 | 2 | 1.4× | Drone/Sentry heavy |
| Colony Ruin KE-7 | 6 | 2 | 1.0× | Balanced enemy mix |

### Player character
- **Stats** (5): Body, Reflex, Mind, Tech, Presence — set at creation via point-buy
  - Body → max HP and melee ATK; Reflex → dodge chance; Mind → XP multiplier and FOV radius;
    Tech → ranged ATK bonus; Presence → intimidate chance and shop discounts
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

### 1. Character development overhaul

Replace the current race/class/5-stat system with a richer point-buy + skill tree that gives
character builds real mechanical identity and supports the game's sci-fi themes.

**Stats (keep, may rename):** Body, Reflex, Mind, Tech, Presence remain the five core
attributes. They set baseline combat math. Point-buy at creation allocates a larger pool
(e.g. 20 points, not 10) across a wider range (1–20).

**Skills (new layer):** Skills are distinct from stats and improve through spending skill
points earned at each level-up. Each skill has levels 0–5; higher levels unlock passives
and active abilities. Suggested tree:

| Category | Skills | Example effects |
|---|---|---|
| Combat | Firearms, Melee, Heavy Weapons | +ranged ATK per level; melee crits; AoE unlocks |
| Technical | Engineering, Hacking, Electronics | repair items; terminal exploits; drone disable |
| Navigation | Pilot, Cartography, Survival | fuel efficiency; map reveals; trap resistance |
| Social | Intimidation, Barter, Persuasion | enemy hesitation; shop price; loot negotiation |

**Level-up flow:** each level grants 1 stat point AND 2 skill points. The current modal
(`show_levelup_modal`) splits into two steps: pick a stat, then pick a skill to advance.

**Character creation:** the 5-step wizard gains a sixth step (skill selection) where the
player pre-allocates a small starting pool (e.g. 4 skill points) to establish early identity.
Race and class modifiers should apply to both stat bases and skill starting levels.

**Downstream effects to wire in once skills exist:**
- Hacking level gates terminal interactions (item 3)
- Engineering level gates trap disarming and tool activation (item 4)
- Pilot level reduces fuel cost or unlocks ship upgrades
- Cartography level extends `fov_radius` (currently driven by Mind alone)
- Survival level reduces status-effect duration from hazard tiles (item 2)

---

### 2. Traps and hazardous tiles

Place tripwire mines, acid puddles, and electric floor panels in `make_floor`. These are
tile variants stored in a `hazards` dict on the floor alongside `items` and `enemies`.
Stepping on a hazard triggers a status effect (acid → burn, electric → stun) and removes
the tile (mines) or persists for N turns (puddles, panels). Rewards cautious play and makes
Reflex/Survival skill investment tangible. The status-effect system already handles damage
and messaging — this is purely a floor-generation and movement-handler addition.

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
