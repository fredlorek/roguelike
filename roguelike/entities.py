"""Game entity classes — zero curses dependency."""

from .constants import (SKILL_ORDER, SKILL_MAX, FOV_RADIUS, MAX_INVENTORY,
                        EFFECT_DAMAGE, EFFECT_DURATION, SKILLS, STATS,
                        STAT_MAX)


class Room:
    def __init__(self, x, y, w, h):
        self.x1, self.y1 = x, y
        self.x2, self.y2 = x + w, y + h

    def center(self):
        return (self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2

    def intersects(self, other, pad=1):
        return (self.x1 - pad < other.x2 and self.x2 + pad > other.x1 and
                self.y1 - pad < other.y2 and self.y2 + pad > other.y1)


class Item:
    def __init__(self, name, slot, atk=0, dfn=0, char='!', consumable=False, heal=0, ranged=False,
                 effect=None, effect_turns=0, fuel=0,
                 charges=0, max_charges=0, tool_effect=None, skill_req=None, skill_level=0):
        self.name         = name   # display name
        self.slot         = slot   # 'weapon', 'armor', 'use', or 'tool'
        self.atk          = atk
        self.dfn          = dfn
        self.char         = char   # glyph on map
        self.consumable   = consumable
        self.heal         = heal
        self.ranged       = ranged
        self.effect       = effect
        self.effect_turns = effect_turns
        self.fuel         = fuel
        self.charges      = charges      # remaining uses (tools)
        self.max_charges  = max_charges  # starting charges
        self.tool_effect  = tool_effect  # 'bypass'/'jammer'/'grapple'/'repair_drone'
        self.skill_req    = skill_req    # skill key required to use
        self.skill_level  = skill_level  # minimum level of that skill

    def stat_str(self):
        if self.tool_effect:
            req = (f" [{SKILLS[self.skill_req]['name']} {self.skill_level}]"
                   if self.skill_req else "")
            return f"[{self.charges}/{self.max_charges}]{req}"
        if self.consumable:
            if self.fuel:
                return f'+{self.fuel} Fuel'
            if self.effect == 'antidote':
                return 'Clears effects'
            elif self.effect == 'scan':
                return 'Detects all traps'
            elif self.effect:
                return f'Apply: {self.effect.capitalize()}'
            return f'Heals {self.heal} HP' if self.heal else ''
        parts = []
        if self.atk: parts.append(f'+{self.atk} ATK')
        if self.dfn: parts.append(f'+{self.dfn} DEF')
        if self.ranged: parts.append('[ranged]')
        return '  '.join(parts)

    def use(self, player):
        if self.fuel:
            player.fuel += self.fuel
            return f"Used {self.name}: +{self.fuel} fuel."
        if self.effect == 'antidote':
            if player.active_effects:
                player.active_effects.clear()
                return f"Used {self.name}: all effects cleared."
            return f"Used {self.name}: no effects to clear."
        if self.effect in ('poison', 'burn', 'stun'):
            return f"Threw {self.name}."   # enemy targeting handled in main loop
        if self.effect in ('emp', 'smoke', 'stim', 'prox_mine', 'scanner'):
            return f"Used {self.name}."    # effect applied in run_site
        if self.heal:
            medicine   = getattr(player, 'skills', {}).get('medicine', 0)
            total_heal = self.heal + medicine * 2
            restored   = min(total_heal, player.max_hp - player.hp)
            player.hp  = min(player.max_hp, player.hp + total_heal)
            return f"Used {self.name}: +{restored} HP."
        return f"Used {self.name}."


class Terminal:
    def __init__(self, title, lines):
        self.title = title
        self.lines = lines
        self.read  = False


class Site:
    def __init__(self, name, char, depth, desc, fuel_cost,
                 theme_fn=None, enemy_density=1.0):
        self.name          = name           # display name
        self.char          = char           # glyph in nav computer
        self.depth         = depth          # number of floors
        self.desc          = desc           # one-line flavour text
        self.fuel_cost     = fuel_cost      # fuel to travel here
        self.theme_fn      = theme_fn       # callable(floor_num)->theme dict; None = get_theme
        self.enemy_density = enemy_density  # multiplier on enemy count
        self.floors        = {}             # floor cache (persists between visits)
        self.cleared       = False          # True after boss defeated


class Enemy:
    def __init__(self, name, char, hp, atk, dfn, xp_reward, boss=False, behaviour='melee'):
        self.name      = name
        self.char      = char
        self.hp        = hp
        self.max_hp    = hp
        self.atk       = atk
        self.dfn       = dfn
        self.xp_reward = xp_reward
        self.boss      = boss
        self.behaviour = behaviour
        self.cooldown  = 0
        self.active_effects = {}


class Player:
    XP_PER_LEVEL = 100
    SLOTS = ('weapon', 'armor', 'helmet', 'gloves', 'boots', 'tool')
    SLOT_LABELS = {'weapon': 'Weapon', 'armor': 'Armor',
                   'helmet': 'Helmet', 'gloves': 'Gloves', 'boots': 'Boots',
                   'tool':   'Tool'}

    def __init__(self, name='Unknown', race='Human', char_class='Soldier',
                 body=5, reflex=5, mind=5, tech=5, presence=5, skills=None):
        self.name       = name
        self.race       = race
        self.char_class = char_class
        self.body       = body
        self.reflex     = reflex
        self.mind       = mind
        self.tech       = tech
        self.presence   = presence
        self.max_hp     = 20 + body * 2   # body=5 -> 30 HP (matches old default)
        self.hp         = self.max_hp
        self.level      = 1
        self.xp         = 0
        self.inventory  = []
        self.equipment  = {s: None for s in self.SLOTS}
        self.credits    = 0
        self.fuel       = 3
        self.active_effects = {}   # effect_name -> remaining_turns
        self.skills       = dict(skills) if skills else {k: 0 for k in SKILL_ORDER}
        self.skill_points = 0   # unspent points; accumulate until spent
        # Run statistics (reset each new character)
        self.enemies_killed    = 0
        self.items_found       = 0
        self.max_floor_reached = 0

    @property
    def atk(self):
        weapon_bonus = sum(i.atk for i in self.equipment.values() if i)
        return 1 + max(0, (self.body - 5) // 2) + weapon_bonus + self.skills.get('melee', 0)

    @property
    def dfn(self):
        return sum(i.dfn for i in self.equipment.values() if i)

    @property
    def dodge_chance(self):
        """Percent chance to dodge an attack. Driven by reflex + Tactics skill."""
        return max(0, (self.reflex - 5) * 4) + self.skills.get('tactics', 0) * 2

    @property
    def ranged_atk(self):
        """ATK for ranged weapons, with tech bonus + Firearms skill on top of base ATK."""
        return self.atk + max(0, (self.tech - 5) // 2) + self.skills.get('firearms', 0)

    @property
    def xp_gain_multiplier(self):
        """XP multiplier from mind stat (mind=5 -> 1.0x, mind=10 -> 1.25x)."""
        return 1.0 + max(0, (self.mind - 5) * 0.05)

    @property
    def fov_radius(self):
        """FOV radius extended by mind stat + Cartography skill."""
        return FOV_RADIUS + max(0, (self.mind - 5) // 3) + self.skills.get('cartography', 0) // 2

    @property
    def fuel_discount(self):
        """Fuel cost reduction from Pilot skill (lv0-1: 0, lv2-3: 1, lv4-5: 2)."""
        return self.skills.get('pilot', 0) // 2

    @property
    def xp_next(self):
        return self.XP_PER_LEVEL * self.level

    def gain_xp(self, amount):
        self.xp += int(amount * self.xp_gain_multiplier)
        levels_gained = 0
        while self.xp >= self.xp_next:
            self.xp    -= self.xp_next
            self.level += 1
            levels_gained += 1
        if levels_gained:
            return levels_gained, f"Level up! You are now level {self.level}."
        return 0, None

    def pickup(self, item):
        if len(self.inventory) >= MAX_INVENTORY:
            return False
        self.inventory.append(item)
        return True

    def equip(self, item):           # item must be in inventory
        old = self.equipment[item.slot]
        self.equipment[item.slot] = item
        self.inventory.remove(item)
        if old:
            self.inventory.append(old)

    def unequip(self, slot):
        item = self.equipment[slot]
        if item:
            self.inventory.append(item)
            self.equipment[slot] = None
