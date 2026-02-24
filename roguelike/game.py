"""Game loop and enemy AI."""

import collections
import copy
import curses
import random

from .constants import *
from .entities import Enemy, Terminal
from .world import (find_path, compute_fov, make_floor, get_theme,
                    apply_effect, tick_effects, _bresenham, ENEMY_TEMPLATES)
from .data import ITEM_TEMPLATES, LORE_POOL, WIN_TERMINAL, SHOP_STOCK
from .lore_gen import generate_terminal
from . import ui


def enemy_turn(enemies, tiles, px, py, visible, player,
               smoke_tiles=None, hazards_on_map=None):
    """Move and attack with every enemy. Returns list of combat message strings."""
    msgs       = []
    player_pos = (px, py)
    # Track occupied positions so enemies don't pile onto the same tile this turn.
    occupied = set(enemies.keys())

    intimidate_chance = max(0, (player.presence - 5) * 3 + player.skills.get('intimidation', 0) * 3)
    player_in_smoke   = bool(smoke_tiles and (px, py) in smoke_tiles)

    def _check_mine(enemy):
        """Check if enemy is on a player-placed mine. Trigger it. Returns True if killed."""
        if not hazards_on_map:
            return False
        cur = next((p for p, e in enemies.items() if e is enemy), None)
        if cur is None or cur not in hazards_on_map:
            return False
        h = hazards_on_map[cur]
        if not h.get('placed_by_player'):
            return False
        dmg = 12
        enemy.hp -= dmg
        h['triggers_left'] -= 1
        if h['triggers_left'] <= 0:
            del hazards_on_map[cur]
        msgs.append(f"BOOM! Mine hits {enemy.name} for {dmg}!")
        if enemy.hp <= 0:
            if cur in enemies:
                del enemies[cur]
            occupied.discard(cur)
            player.enemies_killed += 1
            return True
        return False

    def _random_walk(enemy, epos):
        """Try to move enemy one step randomly. Updates enemies/occupied in place."""
        ex, ey = epos
        dirs = [(0, 1), (0, -1), (1, 0), (-1, 0)]
        random.shuffle(dirs)
        for ndx, ndy in dirs:
            npos = (ex + ndx, ey + ndy)
            nx, ny = npos
            if (0 <= nx < MAP_W and 0 <= ny < MAP_H
                    and tiles[ny][nx] == FLOOR
                    and npos not in occupied
                    and npos != player_pos):
                occupied.discard(epos)
                occupied.add(npos)
                enemies[npos] = enemy
                del enemies[epos]
                return npos
        return epos

    def _do_melee(enemy, epos):
        """Attack player from epos (must be adjacent). Returns True if attack happened."""
        if abs(epos[0] - px) + abs(epos[1] - py) != 1:
            return False
        if player.dodge_chance > 0 and random.randint(1, 100) <= player.dodge_chance:
            msgs.append(f"{enemy.name} attacks — you dodge!")
        else:
            dmg = max(1, enemy.atk - player.dfn)
            player.hp -= dmg
            msgs.append(f"{enemy.name} hits you for {dmg}!")
            on_hit = ENEMY_ON_HIT.get(enemy.name)
            if on_hit and random.random() < on_hit[2]:
                effect, turns, _ = on_hit
                apply_effect(player, effect, turns)
                msgs.append(f"{enemy.name}'s attack inflicts {effect}!")
        return True

    def _astar_step(enemy, epos):
        """Take one A* step toward player. Returns new position after step (may be same)."""
        blocked = occupied - {epos}
        path    = find_path(tiles, epos, player_pos, blocked)
        if not path:
            return epos, False  # (new_pos, attacked)
        step = path[0]
        if step == player_pos:
            _do_melee(enemy, epos)
            return epos, True
        elif step not in occupied:
            occupied.discard(epos)
            occupied.add(step)
            enemies[step] = enemy
            del enemies[epos]
            return step, False
        return epos, False

    for epos, enemy in list(enemies.items()):
        # Presence intimidate: visible enemies may hesitate and skip their turn
        if intimidate_chance > 0 and epos in visible:
            if random.randint(1, 100) <= intimidate_chance:
                continue

        if enemy.active_effects:
            effect_msgs = tick_effects(enemy, enemy.name)
            msgs.extend(effect_msgs)
            if enemy.hp <= 0:
                del enemies[epos]
                continue
            if 'stun' in enemy.active_effects:
                continue   # stunned enemy skips its turn

        # Smoke: player is hidden — all enemies random walk
        if player_in_smoke:
            _random_walk(enemy, epos)
            _check_mine(enemy)
            continue

        behaviour = enemy.behaviour

        # -- Ranged (Gunner) --
        if behaviour == 'ranged':
            if epos in visible:
                ex, ey = epos
                dist   = abs(ex - px) + abs(ey - py)
                if dist <= 2:
                    # Too close — try to retreat to the tile furthest from player
                    best_pos  = epos
                    best_dist = dist
                    for ndx, ndy in [(0,1),(0,-1),(1,0),(-1,0)]:
                        cand = (ex + ndx, ey + ndy)
                        cx, cy = cand
                        if (0 <= cx < MAP_W and 0 <= cy < MAP_H
                                and tiles[cy][cx] == FLOOR
                                and cand not in occupied
                                and cand != player_pos):
                            d = abs(cx - px) + abs(cy - py)
                            if d > best_dist:
                                best_dist = d
                                best_pos  = cand
                    if best_pos != epos:
                        occupied.discard(epos)
                        occupied.add(best_pos)
                        enemies[best_pos] = enemy
                        del enemies[epos]
                else:
                    # Fire at player
                    if player.dodge_chance > 0 and random.randint(1, 100) <= player.dodge_chance:
                        msgs.append(f"{enemy.name} fires at you — you dodge!")
                    else:
                        dmg = max(1, enemy.atk - player.dfn)
                        player.hp -= dmg
                        msgs.append(f"{enemy.name} fires at you for {dmg}!")
                        on_hit = ENEMY_ON_HIT.get(enemy.name)
                        if on_hit and random.random() < on_hit[2]:
                            effect, turns, _ = on_hit
                            apply_effect(player, effect, turns)
                            msgs.append(f"{enemy.name}'s attack inflicts {effect}!")
            else:
                _random_walk(enemy, epos)
            _check_mine(enemy)
            continue

        # -- Fast (Lurker) --
        if behaviour == 'fast':
            cur = epos
            for _ in range(2):
                if cur in visible:
                    cur, attacked = _astar_step(enemy, cur)
                    if attacked:
                        break
                    # Only take a second step if still in FOV after moving
                    if cur not in visible:
                        break
                else:
                    _random_walk(enemy, cur)
                    break
            _check_mine(enemy)
            continue

        # -- Brute --
        if behaviour == 'brute':
            if epos in visible:
                if enemy.cooldown > 0:
                    enemy.cooldown -= 1
                    _check_mine(enemy)
                    continue
                # Act this turn, then set cooldown
                enemy.cooldown = 1
                _astar_step(enemy, epos)
            else:
                _random_walk(enemy, epos)
            _check_mine(enemy)
            continue

        # -- Exploder / Melee (default) --
        if epos in visible:
            _astar_step(enemy, epos)
        else:
            _random_walk(enemy, epos)
        _check_mine(enemy)

    return msgs


def run_site(stdscr, site, player):
    """Run the dungeon game loop for a site.
    Returns 'escaped' (left via B), 'dead', or 'restart' (R pressed)."""
    current_floor = 1

    smoke_tiles = {}   # {(x,y): turns_remaining} — player-deployed smoke
    corruption  = 0    # signal corruption counter (Erebus Station floors 7-10)

    def _load_floor(fnum):
        if fnum not in site.floors:
            is_final  = (fnum == site.depth)
            place_boss = is_final and site.name == 'Erebus Station'
            site.floors[fnum] = make_floor(
                fnum,
                theme_fn=site.theme_fn,
                enemy_density=site.enemy_density,
                is_final=is_final,
                place_boss=place_boss,
            )
        # Reset per-floor Grapple Line charge when entering a new floor
        grapple = player.equipment.get('tool')
        if grapple and grapple.tool_effect == 'grapple' and grapple.charges < grapple.max_charges:
            grapple.charges = grapple.max_charges
        return site.floors[fnum]

    floor_data       = _load_floor(current_floor)
    tiles            = floor_data['tiles']
    px, py           = floor_data['start']
    items_on_map     = floor_data['items']
    enemies_on_map   = floor_data['enemies']
    terminals_on_map = floor_data['terminals']
    special_rooms    = floor_data.get('special_rooms', {})
    stair_up         = floor_data['stair_up']
    stair_down       = floor_data['stair_down']
    explored         = floor_data['explored']
    hazards_on_map   = floor_data.get('hazards', {})

    player.max_floor_reached = max(player.max_floor_reached, current_floor)

    log     = collections.deque(maxlen=LOG_LINES)
    visible = compute_fov(tiles, px, py, player.fov_radius)
    explored |= visible

    theme_fn = site.theme_fn or get_theme
    current_theme = theme_fn(current_floor)

    ui.draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
            stair_up, stair_down, current_floor, enemies_on_map, log,
            terminals=terminals_on_map, special_rooms=special_rooms,
            max_floor=site.depth, theme_override=current_theme,
            hazards=hazards_on_map, smoke_tiles=smoke_tiles)

    MOVE_KEYS = {
        ord('w'):         ( 0, -1),
        ord('a'):         (-1,  0),
        ord('s'):         ( 0,  1),
        ord('d'):         ( 1,  0),
        curses.KEY_UP:    ( 0, -1),
        curses.KEY_LEFT:  (-1,  0),
        curses.KEY_DOWN:  ( 0,  1),
        curses.KEY_RIGHT: ( 1,  0),
        curses.KEY_A1:    (-1, -1),
        curses.KEY_A3:    ( 1, -1),
        curses.KEY_C1:    (-1,  1),
        curses.KEY_C3:    ( 1,  1),
        ord('7'):         (-1, -1),
        ord('9'):         ( 1, -1),
        ord('1'):         (-1,  1),
        ord('3'):         ( 1,  1),
    }

    while True:
        key = stdscr.getch()

        if key in (ord('q'), ord('Q')):
            return 'escaped'

        if key in (ord('b'), ord('B')):
            if current_floor == 1:
                return 'escaped'
            log.appendleft("Return to floor 1 to leave the site.")

        if key in (ord('r'), ord('R')):
            return 'restart'

        if key in (ord('i'), ord('I')):
            result = ui.show_equipment_screen(stdscr, player, px, py, items_on_map)
            if result:
                log.appendleft(result)

        if key in (ord('k'), ord('K')):
            ui.show_skills_screen(stdscr, player)

        if key in (ord('m'), ord('M')):
            ui.show_minimap(stdscr, tiles, px, py, player, visible, explored,
                            items_on_map, stair_up, stair_down, enemies_on_map,
                            terminals_on_map, hazards_on_map, special_rooms,
                            current_floor, site.depth,
                            current_theme.get('name', ''), current_theme,
                            smoke_tiles=smoke_tiles)

        if key in (ord('h'), ord('H')):
            if 'stun' in player.active_effects:
                log.appendleft("You are stunned and cannot act!")
                for msg in tick_effects(player, "You"):
                    log.appendleft(msg)
                e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player,
                                    smoke_tiles=smoke_tiles, hazards_on_map=hazards_on_map)
                for em in e_msgs:
                    log.appendleft(em)
            else:
                hack_lv = player.skills.get('hacking', 0)
                on_terminal = terminals_on_map.get((px, py))
                if on_terminal:
                    consumed = ui.show_hacking_interface(
                        stdscr, player, on_terminal, current_floor, explored,
                        enemies_on_map, items_on_map, special_rooms,
                        tiles, px, py, visible, log, terminals_on_map, current_theme)
                    if consumed:
                        for msg in tick_effects(player, "You"):
                            log.appendleft(msg)
                        e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player,
                                            smoke_tiles=smoke_tiles, hazards_on_map=hazards_on_map)
                        for em in e_msgs:
                            log.appendleft(em)
                        if site.name == 'Erebus Station' and current_floor >= 7 and corruption > 0:
                            reduction = min(corruption, 30)
                            corruption -= reduction
                            log.appendleft(f"// Terminal handshake: signal suppressed -{reduction}%")
                elif hack_lv >= 5:
                    # Remote access from anywhere on floor
                    others = [(pos, t) for pos, t in terminals_on_map.items() if not t.read]
                    if others:
                        # Build a temporary dummy terminal to pass to show_hacking_interface
                        # Actually, pick via remote picker directly here then open interface
                        rpick2 = 0
                        BOX_W2  = 62
                        inner_w2 = BOX_W2 - 4
                        while True:
                            term_h2, term_w2 = stdscr.getmaxyx()
                            pbox_h2 = 2 + 2 + len(others) + 1
                            pbox_y2 = max(0, (term_h2 - pbox_h2) // 2)
                            pbox_x2 = max(0, (term_w2 - BOX_W2) // 2)
                            t_attr2  = curses.color_pair(COLOR_TERMINAL) | curses.A_BOLD
                            p_attr2  = curses.color_pair(COLOR_PANEL)
                            s_attr2  = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD

                            def _r2row(row):
                                try:
                                    stdscr.addch(row, pbox_x2, curses.ACS_VLINE, t_attr2)
                                    stdscr.addch(row, pbox_x2 + BOX_W2 - 1, curses.ACS_VLINE, t_attr2)
                                    stdscr.addstr(row, pbox_x2 + 1, ' ' * (BOX_W2 - 2))
                                except curses.error:
                                    pass

                            try:
                                rtitle2 = " REMOTE ACCESS — Select Terminal "
                                rpad2   = BOX_W2 - 2 - len(rtitle2)
                                rleft2  = rpad2 // 2
                                stdscr.addch(pbox_y2, pbox_x2, curses.ACS_ULCORNER, t_attr2)
                                for bx in range(1, rleft2 + 1):
                                    stdscr.addch(pbox_y2, pbox_x2 + bx, curses.ACS_HLINE, t_attr2)
                                stdscr.addstr(pbox_y2, pbox_x2 + rleft2 + 1, rtitle2, t_attr2)
                                for bx in range(rleft2 + 1 + len(rtitle2), BOX_W2 - 1):
                                    stdscr.addch(pbox_y2, pbox_x2 + bx, curses.ACS_HLINE, t_attr2)
                                stdscr.addch(pbox_y2, pbox_x2 + BOX_W2 - 1, curses.ACS_URCORNER, t_attr2)
                            except curses.error:
                                pass

                            _r2row(pbox_y2 + 1)
                            try:
                                stdscr.addstr(pbox_y2 + 1, pbox_x2 + 2,
                                              "W/S: select   Enter: hack   Esc: cancel"[:inner_w2 + 2],
                                              p_attr2)
                            except curses.error:
                                pass

                            try:
                                stdscr.addch(pbox_y2 + 2, pbox_x2, curses.ACS_LTEE, t_attr2)
                                for bx in range(1, BOX_W2 - 1):
                                    stdscr.addch(pbox_y2 + 2, pbox_x2 + bx, curses.ACS_HLINE, t_attr2)
                                stdscr.addch(pbox_y2 + 2, pbox_x2 + BOX_W2 - 1, curses.ACS_RTEE, t_attr2)
                            except curses.error:
                                pass

                            for oi2, (opos2, ot2) in enumerate(others):
                                orow2 = pbox_y2 + 3 + oi2
                                _r2row(orow2)
                                pfx2 = "  >" if oi2 == rpick2 else "   "
                                lbl2 = f"{pfx2} {ot2.title[:inner_w2 - 1]}"
                                a2   = s_attr2 if oi2 == rpick2 else p_attr2
                                try:
                                    stdscr.addstr(orow2, pbox_x2 + 2, lbl2[:inner_w2 + 2], a2)
                                except curses.error:
                                    pass

                            pbot2 = pbox_y2 + 3 + len(others)
                            try:
                                stdscr.addch(pbot2, pbox_x2, curses.ACS_LLCORNER, t_attr2)
                                for bx in range(1, BOX_W2 - 1):
                                    stdscr.addch(pbot2, pbox_x2 + bx, curses.ACS_HLINE, t_attr2)
                                stdscr.addch(pbot2, pbox_x2 + BOX_W2 - 1, curses.ACS_LRCORNER, t_attr2)
                            except curses.error:
                                pass

                            stdscr.refresh()
                            pk2 = stdscr.getch()

                            if pk2 == 27:
                                break
                            if pk2 in (ord('w'), curses.KEY_UP):
                                rpick2 = (rpick2 - 1) % len(others)
                            elif pk2 in (ord('s'), curses.KEY_DOWN):
                                rpick2 = (rpick2 + 1) % len(others)
                            elif pk2 in (curses.KEY_ENTER, ord('\n'), ord('\r')):
                                chosen_pos2, chosen_t2 = others[rpick2]
                                consumed2 = ui.show_hacking_interface(
                                    stdscr, player, chosen_t2, current_floor, explored,
                                    enemies_on_map, items_on_map, special_rooms,
                                    tiles, chosen_pos2[0], chosen_pos2[1], visible, log,
                                    terminals_on_map, current_theme)
                                if consumed2:
                                    for msg in tick_effects(player, "You"):
                                        log.appendleft(msg)
                                    e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player,
                                                        smoke_tiles=smoke_tiles, hazards_on_map=hazards_on_map)
                                    for em in e_msgs:
                                        log.appendleft(em)
                                    if site.name == 'Erebus Station' and current_floor >= 7 and corruption > 0:
                                        reduction = min(corruption, 30)
                                        corruption -= reduction
                                        log.appendleft(f"// Terminal handshake: signal suppressed -{reduction}%")
                                break
                    else:
                        log.appendleft("No unread terminals on this floor.")
                else:
                    log.appendleft("No terminal in range.")

        if key in (ord('e'), ord('E')):
            if 'stun' in player.active_effects:
                log.appendleft("You are stunned and cannot act!")
                for msg in tick_effects(player, "You"):
                    log.appendleft(msg)
                e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player,
                                    smoke_tiles=smoke_tiles, hazards_on_map=hazards_on_map)
                for em in e_msgs:
                    log.appendleft(em)
            else:
                eng = player.skills.get('engineering', 0)
                if eng >= 2:
                    candidates = [(px + dx, py + dy)
                                  for dx, dy in [(0, 0), (0, -1), (0, 1), (-1, 0), (1, 0)]]
                    found = [(pos, hazards_on_map[pos]) for pos in candidates
                             if pos in hazards_on_map
                             and (eng >= 1 or hazards_on_map[pos]['revealed'])]
                    if found:
                        pos, h = found[0]
                        del hazards_on_map[pos]
                        log.appendleft(f"Engineering: {h['type']} trap disarmed.")
                        for msg in tick_effects(player, "You"):
                            log.appendleft(msg)
                        e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player,
                                            smoke_tiles=smoke_tiles, hazards_on_map=hazards_on_map)
                        for em in e_msgs:
                            log.appendleft(em)
                    else:
                        log.appendleft("No visible trap nearby to disarm.")
                else:
                    log.appendleft("Engineering 2+ required to disarm traps.")

        # -- X key: activate equipped tool --
        if key in (ord('x'), ord('X')):
            tool = player.equipment.get('tool')
            if not tool:
                log.appendleft("No tool equipped. [I] to equip a tool.")
            elif 'stun' in player.active_effects:
                log.appendleft("You are stunned and cannot act!")
                for msg in tick_effects(player, "You"):
                    log.appendleft(msg)
                e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player,
                                    smoke_tiles=smoke_tiles, hazards_on_map=hazards_on_map)
                for em in e_msgs:
                    log.appendleft(em)
            elif tool.charges <= 0:
                log.appendleft(f"{tool.name} is depleted.")
            else:
                if tool.skill_req and player.skills.get(tool.skill_req, 0) < tool.skill_level:
                    log.appendleft(
                        f"Requires {SKILLS[tool.skill_req]['name']} {tool.skill_level}.")
                else:
                    tool_used = False

                    if tool.tool_effect == 'bypass':
                        candidates = [(px + dx, py + dy)
                                      for dx, dy in [(0, 0), (0, -1), (0, 1), (-1, 0), (1, 0)]]
                        found_trap = [pos for pos in candidates if pos in hazards_on_map]
                        if found_trap:
                            tpos = found_trap[0]
                            htype = hazards_on_map[tpos]['type']
                            del hazards_on_map[tpos]
                            log.appendleft(f"Bypass Kit: {htype} trap disarmed safely.")
                            tool_used = True
                        else:
                            log.appendleft("Bypass Kit: no trap in range.")

                    elif tool.tool_effect == 'jammer':
                        count = sum(1 for pos, e in enemies_on_map.items()
                                    if pos in visible and e.name in ('Drone', 'Sentry')
                                    and not apply_effect(e, 'stun', 2))
                        # apply_effect returns None, so count via loop
                        count = 0
                        for pos, e in enemies_on_map.items():
                            if pos in visible and e.name in ('Drone', 'Sentry'):
                                apply_effect(e, 'stun', 2)
                                count += 1
                        log.appendleft(f"Signal Jammer: {count} unit(s) disabled.")
                        tool_used = True

                    elif tool.tool_effect == 'grapple':
                        log.appendleft("GRAPPLE — direction? (WASD/arrows)")
                        ui.draw(stdscr, tiles, px, py, player, visible, explored,
                                items_on_map, stair_up, stair_down, current_floor,
                                enemies_on_map, log, terminals=terminals_on_map,
                                special_rooms=special_rooms, max_floor=site.depth,
                                theme_override=current_theme, hazards=hazards_on_map,
                                smoke_tiles=smoke_tiles)
                        gk = stdscr.getch()
                        dir_map = {
                            ord('w'): (0, -1), ord('W'): (0, -1), curses.KEY_UP:    (0, -1),
                            ord('s'): (0,  1), ord('S'): (0,  1), curses.KEY_DOWN:  (0,  1),
                            ord('a'): (-1, 0), ord('A'): (-1, 0), curses.KEY_LEFT:  (-1, 0),
                            ord('d'): (1,  0), ord('D'): (1,  0), curses.KEY_RIGHT: (1,  0),
                        }
                        if gk in dir_map:
                            gdx, gdy = dir_map[gk]
                            wx, wy   = px + gdx,     py + gdy
                            lx2, ly2 = px + 2 * gdx, py + 2 * gdy
                            if (0 <= wx < MAP_W and 0 <= wy < MAP_H
                                    and tiles[wy][wx] == WALL
                                    and 0 <= lx2 < MAP_W and 0 <= ly2 < MAP_H
                                    and tiles[ly2][lx2] == FLOOR):
                                px, py = lx2, ly2
                                log.appendleft("Grapple Line: vaulted over wall!")
                                tool_used = True
                            else:
                                log.appendleft("Can't grapple that way.")
                        else:
                            log.appendleft("Grapple cancelled.")

                    elif tool.tool_effect == 'repair_drone':
                        apply_effect(player, 'repair', 3)
                        log.appendleft("Repair Drone deployed — restoring 15 HP over 3 turns.")
                        tool_used = True

                    if tool_used:
                        tool.charges -= 1
                        for msg in tick_effects(player, "You"):
                            log.appendleft(msg)
                        e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player,
                                            smoke_tiles=smoke_tiles, hazards_on_map=hazards_on_map)
                        for em in e_msgs:
                            log.appendleft(em)

        if key in (ord('u'), ord('U')):
            consumables = [i for i in player.inventory if i.consumable]
            if consumables:
                item = consumables[0]
                msg = item.use(player)
                log.appendleft(msg)
                if item.effect in ('poison', 'burn', 'stun'):
                    targets = [(pos, e) for pos, e in enemies_on_map.items() if pos in visible]
                    if targets:
                        tpos, target = min(targets, key=lambda pe: abs(pe[0][0]-px)+abs(pe[0][1]-py))
                        apply_effect(target, item.effect, item.effect_turns)
                        log.appendleft(f"{target.name} is hit — {item.effect}!")
                    else:
                        log.appendleft("No visible target.")
                elif item.effect == 'scan':
                    for h in hazards_on_map.values():
                        h['revealed'] = True
                    n = len(hazards_on_map)
                    log.appendleft(f"Used {item.name}: "
                                   f"{'%d hazard(s) marked.' % n if n else 'no hazards here.'}")
                elif item.effect == 'emp':
                    count = 0
                    for pos, e in enemies_on_map.items():
                        if pos in visible and e.name in ('Drone', 'Sentry'):
                            apply_effect(e, 'stun', 2)
                            count += 1
                    log.appendleft(f"EMP Charge: {count} unit(s) disabled.")
                elif item.effect == 'scanner':
                    for sy2 in range(MAP_H):
                        for sx2 in range(MAP_W):
                            if tiles[sy2][sx2] == FLOOR:
                                explored.add((sx2, sy2))
                    log.appendleft("Scanner Chip activated — full floor mapped.")
                elif item.effect == 'smoke':
                    radius = 3
                    for dy2 in range(-radius, radius + 1):
                        for dx2 in range(-radius, radius + 1):
                            if dx2 * dx2 + dy2 * dy2 <= radius * radius:
                                tx2, ty2 = px + dx2, py + dy2
                                if 0 <= tx2 < MAP_W and 0 <= ty2 < MAP_H:
                                    smoke_tiles[(tx2, ty2)] = 3
                    log.appendleft("Smoke grenade deployed.")
                elif item.effect == 'stim':
                    apply_effect(player, 'stim', 5)
                    log.appendleft("Stimpack injected — speed doubled for 5 turns!")
                elif item.effect == 'prox_mine':
                    hazards_on_map[(px, py)] = {
                        'type': 'prox_mine', 'char': '*',
                        'triggers_left': 1, 'revealed': True, 'placed_by_player': True,
                    }
                    log.appendleft("Proximity mine placed.")
                player.inventory.remove(item)
            else:
                log.appendleft("No consumables in inventory.")

        if key in (ord('t'), ord('T')):
            in_shop = False
            for sroom in special_rooms.values():
                if (px, py) in sroom['tiles'] and sroom['type'] == 'shop':
                    in_shop = True
                    result = ui.show_shop_screen(stdscr, player, sroom['stock'])
                    if result:
                        log.appendleft(result)
                    break
            if not in_shop:
                log.appendleft("No shop here.")

        if key in (ord('f'), ord('F')):
            if 'stun' in player.active_effects:
                log.appendleft("You are stunned and cannot fire!")
                for msg in tick_effects(player, "You"):
                    log.appendleft(msg)
                e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player,
                                    smoke_tiles=smoke_tiles, hazards_on_map=hazards_on_map)
                for em in e_msgs:
                    log.appendleft(em)
            else:
                weapon = player.equipment.get('weapon')
                if not weapon or not weapon.ranged:
                    log.appendleft("No ranged weapon equipped.")
                else:
                    target_pos, _ = ui.show_targeting(
                        stdscr, tiles, px, py, player, visible, explored,
                        items_on_map, stair_up, stair_down, current_floor,
                        enemies_on_map, log, terminals_on_map, hazards_on_map,
                        smoke_tiles=smoke_tiles, corruption=corruption)
                    if target_pos is not None:
                        tx, ty  = target_pos
                        hit_pos = None
                        for lx, ly in _bresenham(px, py, tx, ty):
                            if (lx, ly) == (px, py):
                                continue
                            if tiles[ly][lx] == WALL:
                                break
                            if (lx, ly) in enemies_on_map:
                                hit_pos = (lx, ly)
                                break

                        if hit_pos:
                            enemy = enemies_on_map[hit_pos]
                            dmg   = max(1, player.ranged_atk - enemy.dfn)
                            enemy.hp -= dmg
                            if enemy.hp <= 0:
                                del enemies_on_map[hit_pos]
                                player.enemies_killed += 1
                                if enemy.behaviour == 'exploder':
                                    kx, ky = hit_pos
                                    if abs(kx - px) + abs(ky - py) <= 1:
                                        splash = max(1, int(enemy.atk * 0.5))
                                        player.hp -= splash
                                        log.appendleft(f"{enemy.name} detonates — caught in blast! -{splash} HP!")
                                    else:
                                        log.appendleft(f"{enemy.name} detonates!")
                                n_lv, lvl_msg = player.gain_xp(enemy.xp_reward)
                                cr_drop = max(1, enemy.xp_reward // 2)
                                player.credits += cr_drop
                                log.appendleft(
                                    f"You shoot {enemy.name} for {dmg}. "
                                    f"{enemy.name} destroyed! +{enemy.xp_reward} XP +{cr_drop} cr")
                                if lvl_msg:
                                    log.appendleft(lvl_msg)
                                for _ in range(n_lv):
                                    ui.show_levelup_modal(stdscr, player)
                                    ui.show_skill_levelup_modal(stdscr, player, points=2)
                                if enemy.boss:
                                    ui.draw(stdscr, tiles, px, py, player, visible, explored,
                                            items_on_map, stair_up, stair_down, current_floor,
                                            enemies_on_map, log, terminals=terminals_on_map,
                                            special_rooms=special_rooms, max_floor=site.depth,
                                            theme_override=current_theme, hazards=hazards_on_map,
                                            smoke_tiles=smoke_tiles, corruption=corruption)
                                    ui.show_terminal(stdscr, WIN_TERMINAL)
                                    site.cleared = True
                                    return 'escaped'
                            else:
                                log.appendleft(f"You shoot {enemy.name} for {dmg}.")
                        else:
                            log.appendleft("The shot goes wide.")

                        e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player,
                                            smoke_tiles=smoke_tiles, hazards_on_map=hazards_on_map)
                        for em in e_msgs:
                            log.appendleft(em)

        if key in MOVE_KEYS:
            if 'stun' in player.active_effects:
                log.appendleft("You are stunned and cannot act!")
                for msg in tick_effects(player, "You"):
                    log.appendleft(msg)
                e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player,
                                    smoke_tiles=smoke_tiles, hazards_on_map=hazards_on_map)
                for em in e_msgs:
                    log.appendleft(em)
            else:
                for msg in tick_effects(player, "You"):
                    log.appendleft(msg)

                def _do_move(mk):
                    """Process one movement key. Returns True if stairs were taken."""
                    nonlocal px, py, current_floor, floor_data, tiles, items_on_map
                    nonlocal enemies_on_map, terminals_on_map, special_rooms, stair_up
                    nonlocal stair_down, explored, hazards_on_map, current_theme
                    dx2, dy2 = MOVE_KEYS[mk]
                    nx2, ny2 = px + dx2, py + dy2
                    if (nx2, ny2) in enemies_on_map:
                        en2 = enemies_on_map[(nx2, ny2)]
                        dmg2 = max(1, player.atk - en2.dfn)
                        en2.hp -= dmg2
                        if en2.hp <= 0:
                            del enemies_on_map[(nx2, ny2)]
                            player.enemies_killed += 1
                            if en2.behaviour == 'exploder':
                                splash2 = max(1, int(en2.atk * 0.5))
                                player.hp -= splash2
                                log.appendleft(f"{en2.name} detonates — caught in blast! -{splash2} HP!")
                            n_lv2, lvl_msg2 = player.gain_xp(en2.xp_reward)
                            cr2 = max(1, en2.xp_reward // 2)
                            player.credits += cr2
                            log.appendleft(
                                f"You hit {en2.name} for {dmg2}. "
                                f"{en2.name} destroyed! +{en2.xp_reward} XP +{cr2} cr")
                            if lvl_msg2:
                                log.appendleft(lvl_msg2)
                            for _ in range(n_lv2):
                                ui.show_levelup_modal(stdscr, player)
                                ui.show_skill_levelup_modal(stdscr, player, points=2)
                            if en2.boss:
                                ui.draw(stdscr, tiles, px, py, player, visible, explored,
                                        items_on_map, stair_up, stair_down, current_floor,
                                        enemies_on_map, log, terminals=terminals_on_map,
                                        special_rooms=special_rooms, max_floor=site.depth,
                                        theme_override=current_theme, hazards=hazards_on_map,
                                        smoke_tiles=smoke_tiles, corruption=corruption)
                                ui.show_terminal(stdscr, WIN_TERMINAL)
                                site.cleared = True
                                return 'escaped'
                        else:
                            edm2 = max(1, en2.atk - player.dfn)
                            player.hp -= edm2
                            log.appendleft(
                                f"You hit {en2.name} for {dmg2}. "
                                f"{en2.name} hits back for {edm2}.")
                    elif 0 <= nx2 < MAP_W and 0 <= ny2 < MAP_H and tiles[ny2][nx2] == FLOOR:
                        px, py = nx2, ny2

                        if (px, py) in hazards_on_map:
                            hazard2 = hazards_on_map[(px, py)]
                            hdata2  = HAZARD_DATA.get(hazard2['type'])
                            if hdata2:
                                if player.dodge_chance > 0 and random.randint(1, 100) <= player.dodge_chance:
                                    log.appendleft(f"You sense danger — sidestep the {hazard2['type']}!")
                                else:
                                    if hdata2['dmg']:
                                        hdmg = hdata2['dmg'] + current_floor
                                        player.hp -= hdmg
                                        log.appendleft(f"{hazard2['type'].capitalize()} detonates! -{hdmg} HP!")
                                    apply_effect(player, hdata2['effect'], hdata2['effect_turns'])
                                    log.appendleft(
                                        f"{hazard2['type'].capitalize()} — {hdata2['effect']} {hdata2['effect_turns']}t!")
                                    hazard2['triggers_left'] -= 1
                                    if hazard2['triggers_left'] <= 0:
                                        del hazards_on_map[(px, py)]

                        n_lv2, _ = player.gain_xp(1)
                        for _ in range(n_lv2):
                            ui.show_levelup_modal(stdscr, player)
                            ui.show_skill_levelup_modal(stdscr, player, points=2)
                        if (px, py) in items_on_map:
                            picked2 = items_on_map[(px, py)]
                            if player.pickup(picked2):
                                items_on_map.pop((px, py))
                                player.items_found += 1
                                log.appendleft(f"Picked up {picked2.name}.")
                            else:
                                log.appendleft("Inventory full.")

                        if (px, py) in terminals_on_map:
                            t2 = terminals_on_map[(px, py)]
                            if not t2.read:
                                log.appendleft(f"Terminal — [H] to access: {t2.title[:38]}")
                            else:
                                log.appendleft(f"[offline] {t2.title[:44]}")

                        for sroom in special_rooms.values():
                            if (px, py) in sroom['tiles']:
                                rtype = sroom['type']
                                if not sroom['triggered']:
                                    sroom['triggered'] = True
                                    if rtype == 'shop':
                                        log.appendleft("SUPPLY DEPOT — [T] to trade.")
                                    elif rtype == 'armory':
                                        gear = [it for it in ITEM_TEMPLATES
                                                if it.slot in ('weapon', 'armor', 'helmet',
                                                               'gloves', 'boots', 'tool')]
                                        avail = list(sroom['tiles'] - {(px, py)})
                                        for pos in random.sample(avail, min(3, len(avail))):
                                            items_on_map[pos] = copy.copy(random.choice(gear))
                                        log.appendleft("ARMORY — Equipment available.")
                                    elif rtype == 'medbay':
                                        player.hp = player.max_hp
                                        heals = [it for it in ITEM_TEMPLATES if it.consumable]
                                        avail = list(sroom['tiles'] - {(px, py)})
                                        for pos in random.sample(avail, min(2, len(avail))):
                                            items_on_map[pos] = copy.copy(random.choice(heals))
                                        log.appendleft("MED BAY — HP restored. Supplies found.")
                                    elif rtype == 'terminal_hub':
                                        hub_lore = (random.sample(LORE_POOL, 1) +
                                                    [generate_terminal(current_floor) for _ in range(2)])
                                        avail = list(sroom['tiles'] - {(px, py)})
                                        for pos, (ttl, tlines) in zip(
                                                random.sample(avail, min(3, len(avail))), hub_lore):
                                            terminals_on_map[pos] = Terminal(ttl, tlines)
                                        log.appendleft("TERMINAL HUB — Data nodes online.")
                                    elif rtype == 'vault':
                                        cost = 50
                                        if ui.show_vault_prompt(stdscr, cost, player.credits):
                                            if player.credits >= cost:
                                                player.credits -= cost
                                                rare = [it for it in ITEM_TEMPLATES
                                                        if it.atk >= 3 or it.dfn >= 3]
                                                avail = list(sroom['tiles'] - {(px, py)})
                                                for pos in random.sample(avail, min(4, len(avail))):
                                                    items_on_map[pos] = copy.copy(random.choice(rare))
                                                log.appendleft("VAULT OPENED. Rare gear inside.")
                                            else:
                                                sroom['triggered'] = False
                                                log.appendleft("Insufficient credits.")
                                        else:
                                            sroom['triggered'] = False
                                break

                        if stair_down and (px, py) == stair_down:
                            current_floor += 1
                            floor_data       = _load_floor(current_floor)
                            tiles            = floor_data['tiles']
                            px, py           = floor_data['start']
                            items_on_map     = floor_data['items']
                            enemies_on_map   = floor_data['enemies']
                            terminals_on_map = floor_data['terminals']
                            special_rooms    = floor_data.get('special_rooms', {})
                            stair_up         = floor_data['stair_up']
                            stair_down       = floor_data['stair_down']
                            explored         = floor_data['explored']
                            hazards_on_map   = floor_data.get('hazards', {})
                            current_theme    = theme_fn(current_floor)
                            arrival = current_theme.get('msg')
                            player.max_floor_reached = max(player.max_floor_reached, current_floor)
                            log.appendleft(f"You descend to floor {current_floor}.")
                            if arrival:
                                log.appendleft(arrival)
                            return 'stairs'
                        elif stair_up and (px, py) == stair_up:
                            current_floor -= 1
                            floor_data       = site.floors[current_floor]
                            tiles            = floor_data['tiles']
                            px, py           = floor_data['stair_down']
                            items_on_map     = floor_data['items']
                            enemies_on_map   = floor_data['enemies']
                            terminals_on_map = floor_data['terminals']
                            special_rooms    = floor_data.get('special_rooms', {})
                            stair_up         = floor_data['stair_up']
                            stair_down       = floor_data['stair_down']
                            explored         = floor_data['explored']
                            hazards_on_map   = floor_data.get('hazards', {})
                            current_theme    = theme_fn(current_floor)
                            log.appendleft(f"You ascend to floor {current_floor}.")
                            return 'stairs'
                    return None   # normal move (no stairs, no boss kill)

                move_result = _do_move(key)
                if move_result == 'escaped':
                    return 'escaped'

                # -- Signal corruption (Erebus Station floors 7-10) --
                if site.name == 'Erebus Station' and current_floor >= 7:
                    rate = max(1, 3
                               - max(0, player.mind - 5) // 2
                               - player.skills.get('hacking', 0) // 3)
                    corruption = min(CORRUPTION_MAX, corruption + rate)
                    tier = (3 if corruption >= 75 else
                            2 if corruption >= 50 else
                            1 if corruption >= 25 else 0)
                    if tier == 1 and random.random() < 0.25:
                        log.appendleft(random.choice(_CORRUPT_WHISPER))
                    elif tier == 2:
                        if random.random() < 0.40:
                            log.appendleft(random.choice(_CORRUPT_INTERFERE))
                        if random.random() < 0.12:
                            apply_effect(player, 'burn', 1)
                            log.appendleft("// SIGNAL SURGE: synaptic burn — 1t!")
                    elif tier == 3:
                        if random.random() < 0.60:
                            log.appendleft(random.choice(_CORRUPT_CASCADE))
                        if random.random() < 0.22:
                            eff = random.choice(['burn', 'stun'])
                            apply_effect(player, eff, 1)
                            log.appendleft(f"// RESONANCE: cognitive disruption — {eff} 1t!")
                    if corruption >= CORRUPTION_MAX:
                        ui.show_cascade_modal(stdscr, player)
                        corruption = 40
                        apply_effect(player, 'stun', 1)
                        log.appendleft("// Neural buffer purged — consciousness reasserting...")

                # Stim: bonus move on same floor
                if 'stim' in player.active_effects and move_result != 'stairs':
                    v_stim = compute_fov(tiles, px, py, player.fov_radius)
                    explored |= v_stim
                    ui.draw(stdscr, tiles, px, py, player, v_stim, explored,
                            items_on_map, stair_up, stair_down, current_floor,
                            enemies_on_map, log, terminals=terminals_on_map,
                            special_rooms=special_rooms, max_floor=site.depth,
                            theme_override=current_theme, hazards=hazards_on_map,
                            smoke_tiles=smoke_tiles, corruption=corruption)
                    key2 = stdscr.getch()
                    if key2 in MOVE_KEYS and 'stun' not in player.active_effects:
                        r2 = _do_move(key2)
                        if r2 == 'escaped':
                            return 'escaped'

                e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player,
                                    smoke_tiles=smoke_tiles, hazards_on_map=hazards_on_map)
                for em in e_msgs:
                    log.appendleft(em)

                # Tick smoke clouds after each enemy turn
                for spos in list(smoke_tiles.keys()):
                    smoke_tiles[spos] -= 1
                    if smoke_tiles[spos] <= 0:
                        del smoke_tiles[spos]

        visible   = compute_fov(tiles, px, py, player.fov_radius)
        explored |= visible

        # FOV flicker: corruption dims the edges of sight (rendering only)
        fov_mod = 0
        if site.name == 'Erebus Station' and current_floor >= 7:
            if corruption >= 75:
                fov_mod = -1
            elif corruption >= 50 and random.random() < 0.35:
                fov_mod = -1
        visible_draw = (compute_fov(tiles, px, py, max(1, player.fov_radius + fov_mod))
                        if fov_mod else visible)

        if player.hp <= 0:
            player.hp = 0
            ui.draw(stdscr, tiles, px, py, player, visible_draw, explored, items_on_map,
                    stair_up, stair_down, current_floor, enemies_on_map, log,
                    terminals=terminals_on_map, special_rooms=special_rooms,
                    max_floor=site.depth, theme_override=current_theme,
                    hazards=hazards_on_map, smoke_tiles=smoke_tiles, corruption=corruption)
            return 'dead'

        ui.draw(stdscr, tiles, px, py, player, visible_draw, explored, items_on_map,
                stair_up, stair_down, current_floor, enemies_on_map, log,
                terminals=terminals_on_map, special_rooms=special_rooms,
                max_floor=site.depth, theme_override=current_theme,
                hazards=hazards_on_map, smoke_tiles=smoke_tiles, corruption=corruption)
