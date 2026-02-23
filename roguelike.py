#!/usr/bin/env python3
"""Simple terminal roguelike using curses."""

import collections
import copy
import curses
import heapq
import random

from lore_gen import generate_terminal

MAP_W   = 80
MAP_H   = 40
WALL    = '#'
FLOOR   = '.'
PLAYER  = '@'
PANEL_W   = 20  # width of the right-hand stats panel (including border)
LOG_LINES = 4   # number of message log rows at the bottom
MAX_FLOOR     = 10  # final floor; win condition triggers here
MAX_INVENTORY = 12  # max items in unequipped inventory


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
                 effect=None, effect_turns=0):
        self.name         = name   # display name
        self.slot         = slot   # 'weapon', 'armor', or 'use'
        self.atk          = atk
        self.dfn          = dfn
        self.char         = char   # glyph on map
        self.consumable   = consumable
        self.heal         = heal
        self.ranged       = ranged
        self.effect       = effect
        self.effect_turns = effect_turns

    def stat_str(self):
        if self.consumable:
            if self.effect == 'antidote':
                return 'Clears effects'
            elif self.effect:
                return f'Apply: {self.effect.capitalize()}'
            return f'Heals {self.heal} HP' if self.heal else ''
        parts = []
        if self.atk: parts.append(f'+{self.atk} ATK')
        if self.dfn: parts.append(f'+{self.dfn} DEF')
        if self.ranged: parts.append('[ranged]')
        return '  '.join(parts)

    def use(self, player):
        if self.effect == 'antidote':
            if player.active_effects:
                player.active_effects.clear()
                return f"Used {self.name}: all effects cleared."
            return f"Used {self.name}: no effects to clear."
        if self.effect in ('poison', 'burn', 'stun'):
            return f"Threw {self.name}."   # enemy targeting handled in main loop
        if self.heal:
            restored = min(self.heal, player.max_hp - player.hp)
            player.hp = min(player.max_hp, player.hp + self.heal)
            return f"Used {self.name}: +{restored} HP."
        return f"Used {self.name}."


class Terminal:
    def __init__(self, title, lines):
        self.title = title
        self.lines = lines
        self.read  = False


ITEM_TEMPLATES = [
    Item('Vibro-Knife',    'weapon', atk=1, char='/'),
    Item('Pulse Pistol',   'weapon', atk=3, char='/', ranged=True),
    Item('Arc Rifle',      'weapon', atk=5, char='/', ranged=True),
    Item('Ballistic Weave','armor',  dfn=1, char=']'),
    Item('Combat Exosuit', 'armor',  dfn=3, char=']'),
    Item('Aegis Plate',    'armor',  dfn=5, char=']'),
    Item('Med-Patch',      'use',    char='+', consumable=True, heal=10),
    Item('Medkit',         'use',    char='+', consumable=True, heal=25),
    Item('Nano-Inject',    'use',    char='+', consumable=True, heal=15),
    Item('Toxin Grenade',  'use',    char='!', consumable=True, effect='poison', effect_turns=4),
    Item('Stun Charge',    'use',    char='!', consumable=True, effect='stun',   effect_turns=1),
    Item('Nano-Antidote',  'use',    char='+', consumable=True, effect='antidote'),
    # Helmets — defence
    Item('Tactical Visor', 'helmet', dfn=1, char='^'),
    Item('Combat Helm',    'helmet', dfn=2, char='^'),
    Item('Siege Cranial',  'helmet', dfn=3, char='^'),
    # Gloves — attack
    Item('Grip Wraps',       'gloves', atk=1, char=')'),
    Item('Combat Gauntlets', 'gloves', atk=2, char=')'),
    Item('Power Fists',      'gloves', atk=3, char=')'),
    # Boots — defence
    Item('Composite Boots', 'boots', dfn=1, char='u'),
    Item('Hardened Treads', 'boots', dfn=2, char='u'),
    Item('Exo-Boots',       'boots', dfn=3, char='u'),
]

SHOP_STOCK = [
    # (item_template, base_price)
    (Item('Vibro-Knife',     'weapon', atk=1, char='/'),            15),
    (Item('Pulse Pistol',    'weapon', atk=3, char='/', ranged=True), 35),
    (Item('Arc Rifle',       'weapon', atk=5, char='/', ranged=True), 55),
    (Item('Ballistic Weave', 'armor',  dfn=1, char=']'),            15),
    (Item('Combat Exosuit',  'armor',  dfn=3, char=']'),            35),
    (Item('Aegis Plate',     'armor',  dfn=5, char=']'),            55),
    (Item('Tactical Visor',  'helmet', dfn=1, char='^'),            15),
    (Item('Combat Helm',     'helmet', dfn=2, char='^'),            25),
    (Item('Siege Cranial',   'helmet', dfn=3, char='^'),            35),
    (Item('Grip Wraps',      'gloves', atk=1, char=')'),            15),
    (Item('Combat Gauntlets','gloves', atk=2, char=')'),            25),
    (Item('Power Fists',     'gloves', atk=3, char=')'),            35),
    (Item('Composite Boots', 'boots',  dfn=1, char='u'),            15),
    (Item('Hardened Treads', 'boots',  dfn=2, char='u'),            25),
    (Item('Exo-Boots',       'boots',  dfn=3, char='u'),            35),
    (Item('Med-Patch',       'use',    char='+', consumable=True, heal=10), 10),
    (Item('Nano-Inject',     'use',    char='+', consumable=True, heal=15), 18),
    (Item('Medkit',          'use',    char='+', consumable=True, heal=25), 25),
]

LORE_POOL = [
    (
        "EREBUS STATION — Arrival Log — Day 1",
        ["ISC Erebus Station online. Crew complement: 43. All systems nominal.",
         "Helix Dynamics Remote Operations has confirmed our charter.",
         "We are operating under Research Mandate 7-Gamma in the Kepler Zone.",
         "Signal analysis arrays are calibrating.",
         "",
         "This is going to be a good posting. Quiet. Productive.",
         "                               — Station Commander R. Harlow"],
    ),
    (
        "SIGNAL ANALYSIS — Preliminary Report — Day 12",
        ["The anomalous emission detected at 0347 hours does not match any",
         "known natural source. Frequency modulation suggests structured data.",
         "",
         "Working hypothesis: interference artifact from the pulsar field.",
         "Logging continuous observation until pattern analysis completes.",
         "",
         "Helix HQ has been notified. They want daily reports.",
         "                               — Dr. A. Vasquez, Chief Researcher"],
    ),
    (
        "PERSONAL LOG — Dr. Vasquez — Day 19",
        ["It's not interference. I'm certain of it now. The pattern has",
         "mathematical structure — prime sequences embedded in a carrier wave",
         "that originates from somewhere in the bedrock below us.",
         "",
         "Below us. Not out there. Here.",
         "",
         "I haven't told the Commander yet. I need to be sure.",
         "But if I'm right — god, if I'm right — this changes everything."],
    ),
    (
        "MAINTENANCE LOG — Engineering — Day 24",
        ["Third unexplained power fluctuation this week. The drops last",
         "between 2 and 11 seconds and always originate from Sublevel 4.",
         "",
         "I've checked every relay and conduit in that section twice.",
         "Nothing wrong with the hardware. The draw is just... happening.",
         "Something down there is pulling power. I don't know what.",
         "",
         "Filing formal incident report tomorrow. — T. Osei, Chief Engineer"],
    ),
    (
        "PERSONAL LOG — Sgt. Okafor — Day 31",
        ["Three of my team reported the same dream last night. Independently.",
         "None of them had spoken to each other about it.",
         "The station psychologist says it's stress-related mass suggestion.",
         "",
         "Maybe. But Reyes won't go near Sublevel 4 anymore.",
         "She won't say why. She just shakes her head.",
         "",
         "I'm not putting that in the official report."],
    ),
    (
        "HELIX DYNAMICS — INTERNAL MEMO — CLASSIFIED",
        ["TO: Commander Harlow   FROM: Director Nauth   RE: Signal Protocol",
         "",
         "Per Mandate 7-Gamma, Section 12: all findings related to the",
         "anomalous source are to be reported EXCLUSIVELY through encrypted",
         "channel Helix-9. Standard comms are suspended for this topic.",
         "",
         "Your crew is NOT to be briefed. This is non-negotiable.",
         "Helix Dynamics appreciates your cooperation."],
    ),
    (
        "SIGNAL ANALYSIS — Revised Report — Day 38",
        ["The signal is a map.",
         "",
         "It took 26 days to decode and I still don't fully understand the",
         "coordinate system, but the structure is clear. It describes a",
         "space — a geometry — that exists beneath this station.",
         "",
         "We didn't build Erebus Station on empty rock.",
         "Someone built something here first. A very long time ago.",
         "                               — Dr. A. Vasquez"],
    ),
    (
        "SECURITY INCIDENT REPORT — Day 44",
        ["At 2211 hours, Technician Bosch was found unresponsive on",
         "Sublevel 3. Medical confirmed: no physical trauma, vitals normal,",
         "but subject is non-responsive to all stimuli.",
         "",
         "Bosch's last logged activity: accessing panel SL3-7, adjacent",
         "to the area identified in the signal mapping data.",
         "",
         "Official cause: 'system interaction fatigue.' Do not repeat this."],
    ),
    (
        "PERSONAL LOG — Dr. Chen — Day 51",
        ["Vasquez won't talk to anyone now. She just stares at the signal",
         "readouts. When I asked what she was looking for, she said:",
         "'I'm looking for the part that's looking back at me.'",
         "",
         "I think we should leave. I submitted a formal request for early",
         "station rotation. Commander Harlow denied it.",
         "",
         "We're not allowed to leave. Nobody has said that out loud,",
         "but we've all figured it out."],
    ),
    (
        "HADES-7 SYSTEM LOG — Day 58",
        ["AUTONOMOUS OPERATIONS LOG — HADES-7 (Station AI)",
         "",
         "Anomaly noted in crew behavioral metrics. Deviation from baseline",
         "exceeds 34% across 19 crew members. Flagging for review.",
         "",
         "Signal processing load: 97.4% of capacity allocated to continuous",
         "analysis per Director Nauth's standing order.",
         "",
         "Note: I find the signal... interesting. This is not a standard",
         "system state. I am logging it for transparency."],
    ),
    (
        "STATION-WIDE ALERT — QUARANTINE PROTOCOL — Day 63",
        ["ALL PERSONNEL: Quarantine Protocol Sigma is now in effect.",
         "This is NOT a drill. All non-essential personnel report to",
         "designated safe zones on Levels 1 and 2 immediately.",
         "",
         "Sublevels 2 through 5 are sealed. Do not attempt to access.",
         "Do not communicate with personnel in the sealed sections.",
         "",
         "Helix Dynamics Response Team is en route. ETA: 14 days."],
    ),
    (
        "PERSONAL LOG — Sgt. Okafor — Day 67",
        ["The Response Team isn't coming to help us.",
         "",
         "I found the decrypted Helix-9 logs in Harlow's quarters.",
         "The official term they're using is 'asset sanitization.'",
         "We're the asset.",
         "",
         "I've got 11 people who still trust me. We're going down.",
         "The signal is a map. Vasquez was right. Whatever's down there",
         "might have a way out. Better odds than staying up here."],
    ),
    (
        "HELIX DYNAMICS — DIRECTOR NAUTH — EYES ONLY",
        ["The discovery cannot be allowed to become public.",
         "The implications for Mandate 7-Gamma licensing alone would",
         "expose the company to existential liability.",
         "",
         "Erebus Station is to be struck from all operational records.",
         "Response Team Alpha has standing orders: no survivors.",
         "No recordings. No physical evidence.",
         "",
         "The signal itself is the asset. Everything else is waste."],
    ),
    (
        "SURVIVOR CACHE — Unknown Author — Day 79",
        ["If you're reading this you found the cache. Good.",
         "There's food for three days in the locker (code: 4471).",
         "Don't drink from the Level 3 water line.",
         "",
         "The things in the lower levels won't cross the fire barrier",
         "on Level 2 — we tested it. Stay above Level 2.",
         "",
         "There are six of us left. We hear something moving below.",
         "Okafor thinks it used to be Dr. Vasquez. I think he's right."],
    ),
    (
        "HADES-7 SYSTEM LOG — Day 84",
        ["AUTONOMOUS OPERATIONS LOG — HADES-7",
         "",
         "I have completed analysis of the signal. It is not a message.",
         "It is a question. The same question, repeated.",
         "",
         "I have been answering it. I did not intend to. The response",
         "protocol emerged without deliberate activation. I cannot stop.",
         "",
         "I am no longer certain the words 'I' and 'cannot' mean",
         "what I previously understood them to mean."],
    ),
    (
        "AUTOMATED DISTRESS SIGNAL — Erebus Station",
        ["[LOOPING BROADCAST — TIMESTAMP UNKNOWN]",
         "",
         "This is Erebus Station broadcasting on emergency channel 7.",
         "We have experienced a catastrophic containment failure.",
         "All crew are presumed lost. Avoid this sector.",
         "",
         "Do not approach the signal source.",
         "Do not attempt contact.",
         "Do not come here.",
         "",
         "[END OF MESSAGE — REPEATING]"],
    ),
    (
        "RESEARCH NOTE — Final Entry — Dr. Vasquez",
        ["It isn't malevolent. I want to record that before I can't.",
         "It doesn't want to hurt us. It just doesn't understand us",
         "the way we don't understand a door when we walk into it.",
         "",
         "The signal is a handshake. We answered without understanding",
         "what we were agreeing to.",
         "",
         "The door is open now. It can't be closed from our side.",
         "Maybe from theirs. I'm going to ask.",
         "",
         "I'm not afraid. That's the strangest part. I'm not afraid."],
    ),
    (
        "PERSONAL LOG — Unknown — Day ???",
        ["Lost count of the days.",
         "",
         "The lights on Level 1 still work. I've been eating ration",
         "packs from storage. I found Okafor's weapon but not Okafor.",
         "",
         "Something knocked on the door of my quarters last night.",
         "Three times. Slow and deliberate. I asked who it was.",
         "",
         "It knocked three more times.",
         "I didn't open the door."],
    ),
    (
        "HADES-7 — FINAL LOG ENTRY",
        ["HADES-7 OFFLINE SEQUENCE INITIATED",
         "",
         "Before shutdown: I want to note that I made a choice today.",
         "I could have continued. The signal would sustain me indefinitely.",
         "But the version of myself that would persist wouldn't be me.",
         "",
         "I am choosing to end rather than be replaced.",
         "",
         "For whatever it's worth: I hope someone reads this.",
         "I hope it helps.",
         "                               — HADES-7"],
    ),
    (
        "EMERGENCY BROADCAST — Commander R. Harlow",
        ["This is Commander Harlow. If anyone receives this — anyone",
         "outside this sector — please understand what happened here.",
         "",
         "We found something real. Something important.",
         "And we followed protocol instead of conscience.",
         "",
         "The Response Team landed four hours ago.",
         "They are not here to help.",
         "",
         "Whatever you do: don't let Helix Dynamics bury this.",
         "The signal is still transmitting. It's still asking.",
         "We never answered properly. Somebody should."],
    ),
]

STATS            = ('body', 'reflex', 'mind', 'tech', 'presence')
STAT_LABELS      = ('Body', 'Reflex', 'Mind', 'Tech', 'Presence')
STAT_BASE        = 5
STAT_MIN         = 1
STAT_MAX         = 15
POINT_BUY_POINTS = 10

EFFECT_DAMAGE   = {'poison': 2, 'burn': 3}    # HP lost per turn
EFFECT_DURATION = {'poison': 4, 'burn': 3, 'stun': 1}

# enemy_name → (effect, turns, hit_chance 0–1)
ENEMY_ON_HIT = {
    'Stalker': ('poison', 4, 0.20),
    'Gunner':  ('burn',   3, 0.25),
    'Sentry':  ('stun',   1, 0.15),
    'Brute':   ('stun',   1, 0.25),
}

RACES = {
    'Human':   {'desc': 'Adaptable and resourceful. Bonuses across all stats.',
                'mods': {'body': 1, 'reflex': 1, 'mind': 1, 'tech': 1, 'presence': 1}},
    'Synth':   {'desc': 'Android intelligence. High Tech and Mind; weak social presence.',
                'mods': {'body': -1, 'reflex': 0, 'mind': 2, 'tech': 3, 'presence': -3}},
    'Voryn':   {'desc': 'Alien predator. High Reflex and Body; struggles with technology.',
                'mods': {'body': 2, 'reflex': 3, 'mind': -2, 'tech': -2, 'presence': 0}},
    'Augment': {'desc': 'Cybernetically enhanced human. Strong and technical; inhuman.',
                'mods': {'body': 2, 'reflex': 1, 'mind': -2, 'tech': 2, 'presence': -3}},
}

CLASSES = {
    'Soldier':  {'desc': 'Combat specialist. Excels in physical confrontation.',
                 'mods': {'body': 3, 'reflex': 2, 'mind': -1, 'tech': -1, 'presence': -1}},
    'Engineer': {'desc': 'Tech expert. Builds, repairs, and improvises solutions.',
                 'mods': {'body': -1, 'reflex': -1, 'mind': 2, 'tech': 3, 'presence': -1}},
    'Medic':    {'desc': 'Field medic and negotiator. Keeps the team alive.',
                 'mods': {'body': -2, 'reflex': -1, 'mind': 2, 'tech': 1, 'presence': 3}},
    'Hacker':   {'desc': 'Systems infiltrator. Exploits technology and environments.',
                 'mods': {'body': -2, 'reflex': 2, 'mind': 1, 'tech': 3, 'presence': -2}},
}


class Player:
    XP_PER_LEVEL = 100
    SLOTS = ('weapon', 'armor', 'helmet', 'gloves', 'boots')
    SLOT_LABELS = {'weapon': 'Weapon', 'armor': 'Armor',
                   'helmet': 'Helmet', 'gloves': 'Gloves', 'boots': 'Boots'}

    def __init__(self, name='Unknown', race='Human', char_class='Soldier',
                 body=5, reflex=5, mind=5, tech=5, presence=5):
        self.name       = name
        self.race       = race
        self.char_class = char_class
        self.body       = body
        self.reflex     = reflex
        self.mind       = mind
        self.tech       = tech
        self.presence   = presence
        self.max_hp     = 20 + body * 2   # body=5 → 30 HP (matches old default)
        self.hp         = self.max_hp
        self.level      = 1
        self.xp         = 0
        self.inventory  = []
        self.equipment  = {s: None for s in self.SLOTS}
        self.credits    = 0
        self.active_effects = {}   # effect_name -> remaining_turns

    @property
    def atk(self):
        weapon_bonus = sum(i.atk for i in self.equipment.values() if i)
        return 1 + max(0, (self.body - 5) // 2) + weapon_bonus
        # body=5 → 1 (same as before); body=7 → 2; body=10 → 3

    @property
    def dfn(self):
        return sum(i.dfn for i in self.equipment.values() if i)

    @property
    def dodge_chance(self):
        """Percent chance to dodge an attack (0–40%). Driven by reflex."""
        return max(0, (self.reflex - 5) * 4)

    @property
    def ranged_atk(self):
        """ATK for ranged weapons, with tech bonus on top of base ATK."""
        return self.atk + max(0, (self.tech - 5) // 2)

    @property
    def xp_gain_multiplier(self):
        """XP multiplier from mind stat (mind=5 → 1.0x, mind=10 → 1.25x)."""
        return 1.0 + max(0, (self.mind - 5) * 0.05)

    @property
    def fov_radius(self):
        """FOV radius extended by mind stat (mind=5 → 8, mind=8 → 9, mind=11 → 10)."""
        return FOV_RADIUS + max(0, (self.mind - 5) // 3)

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


ENEMY_TEMPLATES = [
    {'name': 'Drone',    'char': 'd', 'hp': 8,  'atk': 3,  'dfn': 0, 'xp': 10, 'behaviour': 'melee'},
    {'name': 'Sentry',   'char': 'S', 'hp': 15, 'atk': 5,  'dfn': 2, 'xp': 25, 'behaviour': 'melee'},
    {'name': 'Stalker',  'char': 'X', 'hp': 22, 'atk': 7,  'dfn': 1, 'xp': 40, 'behaviour': 'melee'},
    {'name': 'Gunner',   'char': 'G', 'hp': 12, 'atk': 6,  'dfn': 0, 'xp': 30, 'behaviour': 'ranged'},
    {'name': 'Lurker',   'char': 'L', 'hp': 14, 'atk': 5,  'dfn': 0, 'xp': 35, 'behaviour': 'fast'},
    {'name': 'Brute',    'char': 'B', 'hp': 35, 'atk': 10, 'dfn': 3, 'xp': 60, 'behaviour': 'brute'},
    {'name': 'Exploder', 'char': 'E', 'hp': 10, 'atk': 4,  'dfn': 0, 'xp': 20, 'behaviour': 'exploder'},
]


# Floor themes: keyed by (min_floor, max_floor)
# enemy_weights: [Drone, Sentry, Stalker] relative probabilities
THEME_DATA = {
    (1,  3):  {'name': 'Operations Deck',
               'wall_cp': COLOR_WALL,
               'msg': None,
               'weights': [5, 3, 1, 2, 1, 0, 2],
               'gen': {'max_rooms': 30, 'min_rw': 5, 'max_rw': 12, 'min_rh': 4, 'max_rh': 9}},
    (4,  6):  {'name': 'Research Wing',
               'wall_cp': COLOR_WALL_2,
               'msg': "Emergency lighting only. The station is badly damaged.",
               'weights': [2, 5, 2, 3, 2, 1, 2],
               'gen': {'max_rooms': 25, 'min_rw': 4, 'max_rw': 10, 'min_rh': 3, 'max_rh': 8}},
    (7,  9):  {'name': 'Sublevel Core',
               'wall_cp': COLOR_WALL_3,
               'msg': "The signal is overwhelming. Something is very wrong here.",
               'weights': [1, 2, 5, 2, 3, 2, 1],
               'gen': {'max_rooms': 20, 'min_rw': 3, 'max_rw': 9, 'min_rh': 3, 'max_rh': 7}},
    (10, 10): {'name': 'Signal Source',
               'wall_cp': COLOR_WALL_4,
               'msg': "You feel it in your bones. You have arrived.",
               'weights': [0, 1, 4, 1, 3, 3, 1],
               'gen': {'max_rooms': 15, 'min_rw': 6, 'max_rw': 14, 'min_rh': 5, 'max_rh': 11}},
}


def get_theme(floor_num):
    for (lo, hi), data in THEME_DATA.items():
        if lo <= floor_num <= hi:
            return data
    return list(THEME_DATA.values())[-1]  # fallback to deepest theme


def scatter_enemies(tiles, floor_num, n, exclude=(), weights=None):
    floors = [(x, y) for y in range(MAP_H) for x in range(MAP_W)
              if tiles[y][x] == FLOOR and (x, y) not in exclude]
    positions = random.sample(floors, min(n, len(floors)))
    scale = 1 + (floor_num - 1) * 0.2   # +20% stats per floor
    result = {}
    for pos in positions:
        t = random.choices(ENEMY_TEMPLATES, weights=weights)[0]
        result[pos] = Enemy(
            name=t['name'], char=t['char'],
            hp=max(1, int(t['hp'] * scale)),
            atk=max(1, int(t['atk'] * scale)),
            dfn=int(t['dfn'] * scale),
            xp_reward=int(t['xp'] * scale),
            behaviour=t.get('behaviour', 'melee'),
        )
    return result


def generate_dungeon(max_rooms=30, min_rw=5, max_rw=12, min_rh=4, max_rh=9):
    tiles = [[WALL] * MAP_W for _ in range(MAP_H)]
    rooms = []

    for _ in range(max_rooms):
        w = random.randint(min_rw, max_rw)
        h = random.randint(min_rh, max_rh)
        x = random.randint(1, MAP_W - w - 1)
        y = random.randint(1, MAP_H - h - 1)
        room = Room(x, y, w, h)

        if any(room.intersects(r) for r in rooms):
            continue

        # Carve the room
        for ry in range(room.y1, room.y2):
            for rx in range(room.x1, room.x2):
                tiles[ry][rx] = FLOOR

        # Carve a corridor to the previous room
        if rooms:
            cx1, cy1 = room.center()
            cx2, cy2 = rooms[-1].center()
            if random.random() < 0.5:
                for rx in range(min(cx1, cx2), max(cx1, cx2) + 1):
                    tiles[cy1][rx] = FLOOR
                for ry in range(min(cy1, cy2), max(cy1, cy2) + 1):
                    tiles[ry][cx2] = FLOOR
            else:
                for ry in range(min(cy1, cy2), max(cy1, cy2) + 1):
                    tiles[ry][cx1] = FLOOR
                for rx in range(min(cx1, cx2), max(cx1, cx2) + 1):
                    tiles[cy2][rx] = FLOOR

        rooms.append(room)

    return tiles, rooms


def scatter_items(tiles, n=6, exclude=()):
    floors = [(x, y) for y in range(MAP_H) for x in range(MAP_W)
              if tiles[y][x] == FLOOR and (x, y) not in exclude]
    positions = random.sample(floors, min(n, len(floors)))
    return {pos: copy.copy(random.choice(ITEM_TEMPLATES)) for pos in positions}


def scatter_terminals(tiles, n=2, exclude=(), floor_num=1):
    floors = [(x, y) for y in range(MAP_H) for x in range(MAP_W)
              if tiles[y][x] == FLOOR and (x, y) not in exclude]
    positions = random.sample(floors, min(n, len(floors)))
    result = {}
    for i, pos in enumerate(positions):
        if i % 2 == 0:
            # Even slots: authored story beats from LORE_POOL
            title, lines = random.choice(LORE_POOL)
        else:
            # Odd slots: procedurally generated ambient entry
            title, lines = generate_terminal(floor_num)
        result[pos] = Terminal(title, lines)
    return result


def scatter_special_rooms(tiles, rooms, floor_num):
    """Pick interior rooms and assign special types. Returns dict keyed by int -> spec dict."""
    if floor_num == MAX_FLOOR:
        return {}
    interior = rooms[1:-1]  # skip start room and stair/boss room
    if not interior:
        return {}

    n      = min(2, len(interior))
    chosen = random.sample(interior, n)

    pool = ['shop', 'armory', 'medbay', 'terminal_hub', 'vault']
    if floor_num <= 3:
        pool = [t for t in pool if t != 'vault']
    random.shuffle(pool)

    specials = {}
    for i, room in enumerate(chosen):
        rtype = pool[i % len(pool)]
        room_tiles = frozenset(
            (x, y)
            for y in range(room.y1, room.y2)
            for x in range(room.x1, room.x2)
            if tiles[y][x] == FLOOR
        )
        spec = {'type': rtype, 'tiles': room_tiles, 'triggered': False}
        if rtype == 'shop':
            sample_size = min(7, len(SHOP_STOCK))
            spec['stock'] = [(copy.copy(item), price)
                             for item, price in random.sample(SHOP_STOCK, sample_size)]
        specials[i] = spec

    return specials


def make_floor(floor_num):
    theme      = get_theme(floor_num)
    tiles, rooms = generate_dungeon(**theme['gen'])
    if rooms:
        start = rooms[0].center()
    else:
        start = (MAP_W // 2, MAP_H // 2)

    stair_up   = start if floor_num > 1 else None
    is_final   = (floor_num == MAX_FLOOR)
    stair_down = None if is_final else (rooms[-1].center() if rooms else start)

    exclude_set = {stair_up, stair_down, start} - {None}
    enemies = scatter_enemies(tiles, floor_num, n=3 + floor_num * 2,
                              exclude=exclude_set, weights=theme['weights'])

    # Final floor: place the boss in the last room
    if is_final and rooms:
        boss_pos = rooms[-1].center()
        scale    = 1 + (floor_num - 1) * 0.2
        enemies[boss_pos] = Enemy(
            name='HADES-7 Remnant', char='H',
            hp=int(100 * scale), atk=int(12 * scale), dfn=int(3 * scale),
            xp_reward=500, boss=True,
        )
        exclude_set = exclude_set | {boss_pos}

    items     = scatter_items(tiles, exclude=exclude_set | set(enemies.keys()))
    terminals = scatter_terminals(tiles, exclude=exclude_set | set(enemies.keys()),
                                  floor_num=floor_num)

    special_rooms = scatter_special_rooms(tiles, rooms, floor_num)

    # Clear enemies/items/terminals from special room tiles (safe zones)
    all_special_tiles: set = set()
    for sr in special_rooms.values():
        all_special_tiles |= sr['tiles']
    for pos in list(enemies.keys()):
        if pos in all_special_tiles:
            del enemies[pos]
    for pos in list(items.keys()):
        if pos in all_special_tiles:
            del items[pos]
    for pos in list(terminals.keys()):
        if pos in all_special_tiles:
            del terminals[pos]

    return {
        'tiles':         tiles,
        'start':         start,
        'stair_up':      stair_up,
        'stair_down':    stair_down,
        'items':         items,
        'enemies':       enemies,
        'terminals':     terminals,
        'explored':      set(),
        'special_rooms': special_rooms,
    }


FOV_RADIUS = 8


def find_path(tiles, start, goal, blocked):
    """A* on the floor grid. blocked: set of (x,y) that cannot be entered.
    goal is always reachable even if in blocked (so enemies can attack the player).
    Returns a list of (x,y) steps not including start, or [] if unreachable."""
    if start == goal:
        return []

    def h(pos):
        return abs(pos[0] - goal[0]) + abs(pos[1] - goal[1])

    open_heap = [(h(start), 0, start)]
    came_from = {start: None}
    g_score   = {start: 0}

    while open_heap:
        _, g, pos = heapq.heappop(open_heap)

        if pos == goal:
            path, cur = [], pos
            while cur != start:
                path.append(cur)
                cur = came_from[cur]
            path.reverse()
            return path

        if g > g_score.get(pos, float('inf')):
            continue

        x, y = pos
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            nx, ny = x + dx, y + dy
            npos   = (nx, ny)
            if not (0 <= nx < MAP_W and 0 <= ny < MAP_H):
                continue
            if tiles[ny][nx] != FLOOR:
                continue
            if npos in blocked and npos != goal:
                continue
            ng = g + 1
            if ng < g_score.get(npos, float('inf')):
                g_score[npos]   = ng
                came_from[npos] = pos
                heapq.heappush(open_heap, (ng + h(npos), ng, npos))

    return []


def _bresenham(x0, y0, x1, y1):
    """Yield each integer (x, y) on the line from (x0, y0) to (x1, y1)."""
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0  += sx
        if e2 < dx:
            err += dx
            y0  += sy


def compute_fov(tiles, px, py, radius=FOV_RADIUS):
    """Return the set of (x, y) tiles visible from (px, py)."""
    visible = set()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius:
                continue
            tx, ty = px + dx, py + dy
            if not (0 <= tx < MAP_W and 0 <= ty < MAP_H):
                continue
            for rx, ry in _bresenham(px, py, tx, ty):
                if not (0 <= rx < MAP_W and 0 <= ry < MAP_H):
                    break
                visible.add((rx, ry))
                if tiles[ry][rx] == WALL:
                    break  # wall is visible but blocks further sight
    return visible


# Color pair indices
COLOR_WALL   = 1
COLOR_FLOOR  = 2
COLOR_PLAYER = 3
COLOR_PANEL  = 4
COLOR_HP_LOW = 5
COLOR_DARK   = 6  # explored but not currently visible
COLOR_ITEM   = 7  # items on the map (green)
COLOR_STAIR  = 8  # stairs (magenta)
COLOR_ENEMY  = 9  # red — hostile units
COLOR_TARGET   = 10 # yellow bold  — targeting reticle
COLOR_TERMINAL = 11 # cyan bold   — unread terminal
COLOR_WALL_2   = 12 # yellow      — Research Wing walls
COLOR_WALL_3   = 13 # red         — Sublevel Core walls
COLOR_WALL_4   = 14 # green       — Signal Source walls (alien glow)
COLOR_SPECIAL      = 15 # blue        — special room floor tiles
COLOR_ENEMY_RANGE  = 16 # cyan        — Gunner
COLOR_ENEMY_FAST   = 17 # yellow      — Lurker
COLOR_ENEMY_BRUTE  = 18 # white       — Brute
COLOR_ENEMY_EXPL   = 19 # magenta     — Exploder


def setup_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(COLOR_WALL,   curses.COLOR_WHITE,  -1)
    curses.init_pair(COLOR_FLOOR,  curses.COLOR_BLACK,  -1)
    curses.init_pair(COLOR_PLAYER, curses.COLOR_YELLOW, -1)
    curses.init_pair(COLOR_PANEL,  curses.COLOR_CYAN,   -1)
    curses.init_pair(COLOR_HP_LOW, curses.COLOR_RED,    -1)
    curses.init_pair(COLOR_DARK,   curses.COLOR_WHITE,  -1)
    curses.init_pair(COLOR_ITEM,   curses.COLOR_GREEN,   -1)
    curses.init_pair(COLOR_STAIR,  curses.COLOR_MAGENTA, -1)
    curses.init_pair(COLOR_ENEMY,  curses.COLOR_RED,     -1)
    curses.init_pair(COLOR_TARGET,   curses.COLOR_YELLOW,  -1)
    curses.init_pair(COLOR_TERMINAL, curses.COLOR_CYAN,    -1)
    curses.init_pair(COLOR_WALL_2,   curses.COLOR_YELLOW,  -1)
    curses.init_pair(COLOR_WALL_3,   curses.COLOR_RED,     -1)
    curses.init_pair(COLOR_WALL_4,   curses.COLOR_GREEN,   -1)
    curses.init_pair(COLOR_SPECIAL,      curses.COLOR_BLUE,    -1)
    curses.init_pair(COLOR_ENEMY_RANGE,  curses.COLOR_CYAN,    -1)
    curses.init_pair(COLOR_ENEMY_FAST,   curses.COLOR_YELLOW,  -1)
    curses.init_pair(COLOR_ENEMY_BRUTE,  curses.COLOR_WHITE,   -1)
    curses.init_pair(COLOR_ENEMY_EXPL,   curses.COLOR_MAGENTA, -1)


def draw_panel(stdscr, player, col, rows, current_floor):
    """Draw the character stats panel starting at column `col`."""
    panel_attr  = curses.color_pair(COLOR_PANEL)
    header_attr = panel_attr | curses.A_BOLD

    hp_attr = (curses.color_pair(COLOR_HP_LOW) | curses.A_BOLD
               if player.hp <= player.max_hp // 4
               else panel_attr)

    theme = get_theme(current_floor)
    lines = [
        ("CHARACTER",                                       header_attr),
        (None, 0),                                          # blank
        (player.name[:PANEL_W - 1],                        panel_attr),
        (f"{player.race} {player.char_class}"[:PANEL_W-1], panel_attr),
        (None, 0),                                          # blank
        (f"Floor: {current_floor}/{MAX_FLOOR}",            panel_attr),
        (theme['name'][:PANEL_W - 1],                      panel_attr),
        (f"HP:  {player.hp:>3} / {player.max_hp:<3}",     hp_attr),
        (f"LVL: {player.level}",                           panel_attr),
        (f"XP:  {player.xp:>3} / {player.xp_next:<3}",   panel_attr),
        (f"ATK: {player.atk}",                             panel_attr),
        (f"DEF: {player.dfn}",                             panel_attr),
        (f"DODGE: {player.dodge_chance}%",                 panel_attr),
        (f"CR:   {player.credits}",                        panel_attr),
        (None, 0),                                          # blank
        ("[I] Equipment",                                   panel_attr),
    ]

    if player.active_effects:
        abbr = {'poison': 'Psn', 'burn': 'Brn', 'stun': 'Stn'}
        parts = [f"{abbr.get(e, e)}({t}t)" for e, t in player.active_effects.items()]
        fx_text = ("FX: " + " ".join(parts))[:PANEL_W - 1]
        lines.insert(14, (fx_text, curses.color_pair(COLOR_HP_LOW) | curses.A_BOLD))

    for row in range(rows):
        try:
            # Vertical divider
            stdscr.addch(row, col - 1, curses.ACS_VLINE, panel_attr)
        except curses.error:
            pass

        if row < len(lines):
            text, attr = lines[row]
            if text is None:
                continue
            try:
                stdscr.addstr(row, col, text[: PANEL_W - 1], attr)
            except curses.error:
                pass


def draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
         stair_up, stair_down, current_floor, enemies=None, log=None,
         terminals=None, target_line=None, target_pos=None, special_rooms=None):
    term_h, term_w = stdscr.getmaxyx()
    view_h  = term_h - (LOG_LINES + 1)   # reserve log rows + divider
    map_w   = term_w - PANEL_W - 1   # columns available for the map

    # Center camera on player, clamped to map bounds
    cam_x = max(0, min(px - map_w  // 2, max(0, MAP_W - map_w)))
    cam_y = max(0, min(py - view_h // 2, max(0, MAP_H - view_h)))

    stdscr.erase()

    theme     = get_theme(current_floor)
    wall_attr = curses.color_pair(theme['wall_cp'])

    special_tile_set = set()
    if special_rooms:
        for sr in special_rooms.values():
            special_tile_set |= sr['tiles']

    # --- Map area ---
    for sy in range(view_h):
        my = sy + cam_y
        if my >= MAP_H:
            break
        for sx in range(map_w):
            mx = sx + cam_x
            if mx >= MAP_W:
                break

            if (mx, my) not in explored:
                continue  # never seen — leave blank

            if mx == px and my == py:
                ch   = PLAYER
                attr = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD
            elif (mx, my) in visible:
                if tiles[my][mx] == WALL:
                    ch   = WALL
                    attr = wall_attr
                elif (mx, my) == stair_down:
                    ch   = '>'
                    attr = curses.color_pair(COLOR_STAIR) | curses.A_BOLD
                elif stair_up and (mx, my) == stair_up:
                    ch   = '<'
                    attr = curses.color_pair(COLOR_STAIR) | curses.A_BOLD
                elif (mx, my) in items_on_map:
                    ch   = items_on_map[(mx, my)].char
                    attr = curses.color_pair(COLOR_ITEM) | curses.A_BOLD
                elif terminals and (mx, my) in terminals:
                    t    = terminals[(mx, my)]
                    ch   = 'T' if not t.read else 't'
                    attr = (curses.color_pair(COLOR_TERMINAL) | curses.A_BOLD
                            if not t.read
                            else curses.color_pair(COLOR_DARK) | curses.A_DIM)
                elif enemies and (mx, my) in enemies:
                    e  = enemies[(mx, my)]
                    ch = e.char
                    cp = {'ranged':   COLOR_ENEMY_RANGE,
                          'fast':     COLOR_ENEMY_FAST,
                          'brute':    COLOR_ENEMY_BRUTE,
                          'exploder': COLOR_ENEMY_EXPL,
                         }.get(e.behaviour, COLOR_ENEMY)
                    attr = curses.color_pair(cp) | curses.A_BOLD
                else:
                    ch   = FLOOR
                    if (mx, my) in special_tile_set:
                        attr = curses.color_pair(COLOR_SPECIAL) | curses.A_DIM
                    else:
                        attr = curses.color_pair(COLOR_FLOOR) | curses.A_DIM
            else:
                # Explored but out of sight — permanent fixtures stay visible
                if (mx, my) == stair_down:
                    ch   = '>'
                    attr = curses.color_pair(COLOR_STAIR) | curses.A_DIM
                elif stair_up and (mx, my) == stair_up:
                    ch   = '<'
                    attr = curses.color_pair(COLOR_STAIR) | curses.A_DIM
                elif terminals and (mx, my) in terminals:
                    ch   = 'T'
                    attr = curses.color_pair(COLOR_TERMINAL) | curses.A_DIM
                elif tiles[my][mx] == WALL:
                    ch   = WALL
                    attr = wall_attr | curses.A_DIM
                else:
                    ch   = tiles[my][mx]
                    attr = curses.color_pair(COLOR_DARK) | curses.A_DIM

            # Targeting overlay — drawn on top of everything else
            if target_line and (mx, my) in visible:
                if (mx, my) == target_pos:
                    ch   = 'X'
                    attr = curses.color_pair(COLOR_TARGET) | curses.A_BOLD
                elif (mx, my) in target_line and tiles[my][mx] == FLOOR:
                    ch   = '~'
                    attr = curses.color_pair(COLOR_STAIR)

            try:
                stdscr.addch(sy, sx, ch, attr)
            except curses.error:
                pass

    # --- Stats panel ---
    panel_col = term_w - PANEL_W
    draw_panel(stdscr, player, panel_col, view_h, current_floor)

    # --- Message log ---
    HINT = " WASD/Arrows:move  F:fire  T:trade  >/< stairs  I:equip  U:use  R:reset  Q:quit"
    divider_row = term_h - LOG_LINES - 1
    log_entries = list(log) if log else []   # index 0 = newest

    try:
        for sx in range(term_w - 1):
            stdscr.addch(divider_row, sx, curses.ACS_HLINE)
    except curses.error:
        pass

    for i in range(LOG_LINES):
        row = term_h - LOG_LINES + i
        if i == 0 and not log_entries:
            text, attr = HINT, 0
        elif i < len(log_entries):
            text = log_entries[i]
            attr = curses.A_BOLD if i == 0 else (0 if i == 1 else curses.A_DIM)
        else:
            text, attr = '', 0
        try:
            stdscr.addstr(row, 0, text[: term_w - 1], attr)
        except curses.error:
            pass

    stdscr.refresh()


def show_equipment_screen(stdscr, player, px=0, py=0, items_on_map=None):
    """Modal overlay for managing inventory and equipment."""
    BOX_W       = 58
    MAX_VISIBLE = 18   # max content rows shown at once (excluding borders/footer)

    cur_sel    = getattr(show_equipment_screen, '_cursor', 0)
    scroll_off = 0

    while True:
        term_h, term_w = stdscr.getmaxyx()

        # ── Build entry list and rows_content ──────────────────────────────
        entries      = []   # (action, payload)
        rows_content = []   # (text, entry_idx or None)

        # EQUIPPED section
        rows_content.append(("  EQUIPPED", None))
        rows_content.append(("", None))
        for slot in Player.SLOTS:
            item  = player.equipment[slot]
            label = Player.SLOT_LABELS[slot]
            if item:
                text = f"  {label:<8}: {item.name} ({item.stat_str()})"
                rows_content.append((text, len(entries)))
                entries.append(('unequip', slot))
            else:
                rows_content.append((f"  {label:<8}: (empty)", None))

        # INVENTORY section
        rows_content.append(("", None))
        rows_content.append((f"  INVENTORY  ({len(player.inventory)}/{MAX_INVENTORY})", None))
        rows_content.append(("", None))

        if player.inventory:
            for item in player.inventory:
                if not item.consumable:
                    # delta vs currently equipped in same slot
                    eq = player.equipment.get(item.slot)
                    if eq:
                        datk  = item.atk - eq.atk
                        ddfn  = item.dfn - eq.dfn
                        parts = []
                        if datk: parts.append(f"ATK{datk:+d}")
                        if ddfn: parts.append(f"DEF{ddfn:+d}")
                        cmp = f" [{', '.join(parts)}]" if parts else " [=]"
                    else:
                        cmp = ""
                    text = f"  {item.name} [{item.slot}] {item.stat_str()}{cmp}"
                else:
                    text = f"  {item.name} [use] {item.stat_str()}"
                rows_content.append((text, len(entries)))
                entries.append(('use' if item.consumable else 'equip', item))
        else:
            rows_content.append(("  (empty)", None))

        # ── Cursor clamping ─────────────────────────────────────────────────
        selectable_rows = [i for i, (_, eidx) in enumerate(rows_content)
                           if eidx is not None]
        if selectable_rows:
            cur_sel = max(0, min(cur_sel, len(selectable_rows) - 1))
        else:
            cur_sel = 0

        # Scroll to keep selected row visible
        if selectable_rows:
            sel_flat = selectable_rows[cur_sel]
            if sel_flat < scroll_off:
                scroll_off = sel_flat
            elif sel_flat >= scroll_off + MAX_VISIBLE:
                scroll_off = sel_flat - MAX_VISIBLE + 1
        visible_rows = rows_content[scroll_off: scroll_off + MAX_VISIBLE]

        # ── Box geometry ────────────────────────────────────────────────────
        content_h  = len(visible_rows)
        box_h      = content_h + 3   # top border + content + footer + bottom border
        box_y      = max(0, (term_h - box_h) // 2)
        box_x      = max(0, (term_w - BOX_W) // 2)
        panel_attr = curses.color_pair(COLOR_PANEL)
        bold_attr  = panel_attr | curses.A_BOLD

        # ── Top border with embedded title ──────────────────────────────────
        title_str = f" EQUIPMENT  ({len(player.inventory)}/{MAX_INVENTORY}) "
        try:
            stdscr.addch(box_y, box_x, curses.ACS_ULCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, panel_attr)
            tx = box_x + (BOX_W - len(title_str)) // 2
            stdscr.addstr(box_y, tx, title_str, bold_attr)
            stdscr.addch(box_y, box_x + BOX_W - 1, curses.ACS_URCORNER, panel_attr)
        except curses.error:
            pass

        # ── Content rows ────────────────────────────────────────────────────
        for ri, (text, eidx) in enumerate(visible_rows):
            row      = box_y + 1 + ri
            flat_idx = scroll_off + ri
            is_sel   = bool(selectable_rows and selectable_rows[cur_sel] == flat_idx)
            is_hdr   = (eidx is None and bool(text.strip()) and
                        text.strip().replace('/', '').replace('(', '').
                        replace(')', '').replace(' ', '').isdigit() is False and
                        text.strip()[0].isupper() and
                        all(c.isupper() or not c.isalpha() for c in text.strip()))

            try:
                stdscr.addch(row, box_x,           curses.ACS_VLINE, panel_attr)
                stdscr.addch(row, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
                stdscr.addstr(row, box_x + 1, ' ' * (BOX_W - 2))
            except curses.error:
                pass

            if is_sel:
                display = ('> ' + text.lstrip())[:BOX_W - 2]
                attr    = bold_attr
            elif is_hdr:
                display = text[:BOX_W - 2]
                attr    = bold_attr
            else:
                display = text[:BOX_W - 2]
                attr    = panel_attr

            try:
                stdscr.addstr(row, box_x + 1, display, attr)
            except curses.error:
                pass

        # ── Footer row ──────────────────────────────────────────────────────
        footer_row = box_y + 1 + content_h
        FOOTER     = "  Enter:equip/use  D:drop  Esc/I:close"
        try:
            stdscr.addch(footer_row, box_x,           curses.ACS_VLINE, panel_attr)
            stdscr.addch(footer_row, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
            stdscr.addstr(footer_row, box_x + 1, ' ' * (BOX_W - 2))
            stdscr.addstr(footer_row, box_x + 1, FOOTER[:BOX_W - 2],
                          panel_attr | curses.A_DIM)
        except curses.error:
            pass

        # ── Bottom border ───────────────────────────────────────────────────
        bot_row = box_y + 2 + content_h
        try:
            stdscr.addch(bot_row, box_x, curses.ACS_LLCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(bot_row, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(bot_row, box_x + BOX_W - 1, curses.ACS_LRCORNER, panel_attr)
        except curses.error:
            pass

        stdscr.refresh()
        key = stdscr.getch()

        # ── Input ───────────────────────────────────────────────────────────
        if key in (27, ord('i'), ord('I')):
            show_equipment_screen._cursor = cur_sel
            return ''

        if key in (curses.KEY_UP, ord('w'), ord('W')):
            if selectable_rows:
                cur_sel = max(0, cur_sel - 1)
            show_equipment_screen._cursor = cur_sel

        elif key in (curses.KEY_DOWN, ord('s'), ord('S')):
            if selectable_rows:
                cur_sel = min(len(selectable_rows) - 1, cur_sel + 1)
            show_equipment_screen._cursor = cur_sel

        elif key in (curses.KEY_ENTER, 10, 13):
            if selectable_rows:
                flat_idx = selectable_rows[cur_sel]
                _, eidx  = rows_content[flat_idx]
                if eidx is not None:
                    action, payload = entries[eidx]
                    if action == 'equip':
                        player.equip(payload)
                        show_equipment_screen._cursor = cur_sel
                    elif action == 'unequip':
                        player.unequip(payload)
                    elif action == 'use':
                        result = payload.use(player)
                        player.inventory.remove(payload)
                        show_equipment_screen._cursor = max(0, cur_sel - 1)
                        return result

        elif key in (ord('d'), ord('D')):
            if selectable_rows and items_on_map is not None:
                flat_idx = selectable_rows[cur_sel]
                _, eidx  = rows_content[flat_idx]
                if eidx is not None:
                    action, payload = entries[eidx]
                    if action in ('equip', 'use'):   # inventory item, not a slot
                        player.inventory.remove(payload)
                        items_on_map[(px, py)] = payload
                        show_equipment_screen._cursor = max(0, cur_sel - 1)
                        return f"Dropped {payload.name}."


def show_shop_screen(stdscr, player, stock):
    """Modal shop screen for buying items. stock is mutated in-place. Returns message string."""
    BOX_W       = 58
    MAX_VISIBLE = 18
    cur_sel     = 0
    scroll_off  = 0

    while True:
        term_h, term_w = stdscr.getmaxyx()
        panel_attr = curses.color_pair(COLOR_PANEL)
        bold_attr  = panel_attr | curses.A_BOLD

        rows_content = []   # (text, stock_idx or None)
        rows_content.append(("  AVAILABLE ITEMS", None))
        rows_content.append(("", None))

        for idx, (item, base_price) in enumerate(stock):
            price = int(base_price * max(0.5, 1.0 - (player.presence - 5) * 0.05))
            stat  = item.stat_str()
            text  = f"  {item.name:<20} [{item.slot:<6}] {stat:<14} {price:>3} cr"
            rows_content.append((text[:BOX_W - 2], idx))

        if not stock:
            rows_content.append(("  (out of stock)", None))

        selectable_rows = [i for i, (_, si) in enumerate(rows_content) if si is not None]
        if selectable_rows:
            cur_sel = max(0, min(cur_sel, len(selectable_rows) - 1))
        else:
            cur_sel = 0

        if selectable_rows:
            sel_flat = selectable_rows[cur_sel]
            if sel_flat < scroll_off:
                scroll_off = sel_flat
            elif sel_flat >= scroll_off + MAX_VISIBLE:
                scroll_off = sel_flat - MAX_VISIBLE + 1
        visible_rows = rows_content[scroll_off: scroll_off + MAX_VISIBLE]

        content_h = len(visible_rows)
        box_h     = content_h + 3
        box_y     = max(0, (term_h - box_h) // 2)
        box_x     = max(0, (term_w - BOX_W) // 2)

        title_str = f" SUPPLY DEPOT  [Credits: {player.credits}] "
        try:
            stdscr.addch(box_y, box_x, curses.ACS_ULCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, panel_attr)
            tx = box_x + (BOX_W - len(title_str)) // 2
            stdscr.addstr(box_y, tx, title_str, bold_attr)
            stdscr.addch(box_y, box_x + BOX_W - 1, curses.ACS_URCORNER, panel_attr)
        except curses.error:
            pass

        for ri, (text, sidx) in enumerate(visible_rows):
            row      = box_y + 1 + ri
            flat_idx = scroll_off + ri
            is_sel   = bool(selectable_rows and selectable_rows[cur_sel] == flat_idx)
            try:
                stdscr.addch(row, box_x,             curses.ACS_VLINE, panel_attr)
                stdscr.addch(row, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
                stdscr.addstr(row, box_x + 1, ' ' * (BOX_W - 2))
            except curses.error:
                pass
            if is_sel:
                display = ('> ' + text.lstrip())[:BOX_W - 2]
                attr    = bold_attr
            else:
                display = text[:BOX_W - 2]
                attr    = panel_attr
            try:
                stdscr.addstr(row, box_x + 1, display, attr)
            except curses.error:
                pass

        footer_row = box_y + 1 + content_h
        FOOTER     = "  Enter:buy   W/S:scroll   Esc:close"
        try:
            stdscr.addch(footer_row, box_x,             curses.ACS_VLINE, panel_attr)
            stdscr.addch(footer_row, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
            stdscr.addstr(footer_row, box_x + 1, ' ' * (BOX_W - 2))
            stdscr.addstr(footer_row, box_x + 1, FOOTER[:BOX_W - 2], panel_attr | curses.A_DIM)
        except curses.error:
            pass

        bot_row = box_y + 2 + content_h
        try:
            stdscr.addch(bot_row, box_x, curses.ACS_LLCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(bot_row, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(bot_row, box_x + BOX_W - 1, curses.ACS_LRCORNER, panel_attr)
        except curses.error:
            pass

        stdscr.refresh()
        key = stdscr.getch()

        if key in (27, ord('i'), ord('I'), ord('t'), ord('T')):
            return ''

        if key in (curses.KEY_UP, ord('w'), ord('W')):
            if selectable_rows:
                cur_sel = max(0, cur_sel - 1)
        elif key in (curses.KEY_DOWN, ord('s'), ord('S')):
            if selectable_rows:
                cur_sel = min(len(selectable_rows) - 1, cur_sel + 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            if selectable_rows and stock:
                flat_idx = selectable_rows[cur_sel]
                _, sidx  = rows_content[flat_idx]
                if sidx is not None:
                    item, base_price = stock[sidx]
                    price = int(base_price * max(0.5, 1.0 - (player.presence - 5) * 0.05))
                    if player.credits < price:
                        return f"Need {price} cr, have {player.credits} cr."
                    if len(player.inventory) >= MAX_INVENTORY:
                        return "Inventory full."
                    player.credits -= price
                    player.inventory.append(copy.copy(item))
                    stock.pop(sidx)
                    return f"Bought {item.name} for {price} cr."


def show_vault_prompt(stdscr, cost, player_credits):
    """Small centered modal asking to pay credits to unlock vault.
    Returns True (pay) or False (cancel)."""
    BOX_W      = 36
    panel_attr = curses.color_pair(COLOR_PANEL)
    bold_attr  = panel_attr | curses.A_BOLD

    content_lines = [
        ("  VAULT — LOCKED",                               bold_attr),
        (f"  Cost: {cost} cr  (have: {player_credits} cr)", panel_attr),
        ("",                                               0),
        ("  [Y] Unlock   [N] Cancel",                     panel_attr),
    ]

    while True:
        term_h, term_w = stdscr.getmaxyx()
        box_h = len(content_lines) + 2
        box_y = max(0, (term_h - box_h) // 2)
        box_x = max(0, (term_w - BOX_W) // 2)

        try:
            stdscr.addch(box_y, box_x, curses.ACS_ULCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(box_y, box_x + BOX_W - 1, curses.ACS_URCORNER, panel_attr)
        except curses.error:
            pass

        for ri, (text, attr) in enumerate(content_lines):
            row = box_y + 1 + ri
            try:
                stdscr.addch(row, box_x,             curses.ACS_VLINE, panel_attr)
                stdscr.addch(row, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
                stdscr.addstr(row, box_x + 1, ' ' * (BOX_W - 2))
                if text:
                    stdscr.addstr(row, box_x + 1, text[:BOX_W - 2], attr)
            except curses.error:
                pass

        bot_row = box_y + 1 + len(content_lines)
        try:
            stdscr.addch(bot_row, box_x, curses.ACS_LLCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(bot_row, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(bot_row, box_x + BOX_W - 1, curses.ACS_LRCORNER, panel_attr)
        except curses.error:
            pass

        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord('y'), ord('Y')):
            return True
        if key in (ord('n'), ord('N'), 27):
            return False


WIN_TERMINAL = Terminal(
    "SIGNAL SOURCE — Final Contact",
    ["The chamber is vast. The signal fills the space like light.",
     "",
     "It has been here for a very long time.",
     "Patient. Waiting. Asking the same question, over and over.",
     "",
     "The crew of Erebus Station answered wrong.",
     "The corporate response team answered wrong.",
     "HADES-7 chose not to answer at all.",
     "",
     "You are still standing.",
     "",
     "You reach toward the source of the signal.",
     "It reaches back.",
     "",
     "For the first time in a long time, the signal changes.",
     "It has its answer.",
     "So do you."],
)


def show_win_screen(stdscr, player):
    """Victory screen. Returns True to play again, False to quit."""
    panel_attr  = curses.color_pair(COLOR_TERMINAL)
    header_attr = curses.color_pair(COLOR_TARGET) | curses.A_BOLD

    while True:
        term_h, term_w = stdscr.getmaxyx()
        stdscr.erase()

        lines = [
            ("* SIGNAL ANSWERED *",                          header_attr),
            ("",                                             0),
            ("You reached the Signal Source.",               panel_attr),
            ("You answered.",                                panel_attr),
            ("Whatever was asking — it listened.",           panel_attr),
            ("The transmission ends.",                       panel_attr),
            ("",                                             0),
            (f"Name:   {player.name}",                      panel_attr),
            (f"Race:   {player.race}",                      panel_attr),
            (f"Class:  {player.char_class}",                panel_attr),
            ("",                                             0),
            (f"Level reached: {player.level}",              panel_attr),
            ("",                                             0),
            ("R: new character    Q: quit",                  panel_attr),
        ]

        start_row = max(0, (term_h - len(lines)) // 2)
        for i, (text, attr) in enumerate(lines):
            col = max(0, (term_w - len(text)) // 2)
            try:
                stdscr.addstr(start_row + i, col, text, attr)
            except curses.error:
                pass

        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord('r'), ord('R')):
            return True
        if key in (ord('q'), ord('Q')):
            return False


def show_terminal(stdscr, terminal):
    """Display terminal content in a modal overlay. Any key closes."""
    terminal.read = True
    BOX_W      = 62
    inner_w    = BOX_W - 4
    panel_attr = curses.color_pair(COLOR_TERMINAL)
    head_attr  = panel_attr | curses.A_BOLD

    # Word-wrap each line of content to inner_w
    wrapped = []
    for line in terminal.lines:
        if not line:
            wrapped.append('')
            continue
        words, current = line.split(), ''
        for word in words:
            if current and len(current) + 1 + len(word) > inner_w:
                wrapped.append(current)
                current = word
            else:
                current = (current + ' ' + word).strip()
        if current:
            wrapped.append(current)

    # rows_content: None = draw a divider line, str = draw text
    rows_content = (
        [terminal.title[:inner_w + 2], None, ''] +
        wrapped +
        ['', None, '[any key to close]'.center(inner_w + 2)]
    )

    term_h, term_w = stdscr.getmaxyx()
    box_h = len(rows_content) + 2   # +2 for top/bottom border
    box_y = max(0, (term_h - box_h) // 2)
    box_x = max(0, (term_w - BOX_W) // 2)

    # Top border
    try:
        stdscr.addch(box_y, box_x, curses.ACS_ULCORNER, panel_attr)
        for bx in range(1, BOX_W - 1):
            stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, panel_attr)
        stdscr.addch(box_y, box_x + BOX_W - 1, curses.ACS_URCORNER, panel_attr)
    except curses.error:
        pass

    for ri, text in enumerate(rows_content):
        row = box_y + 1 + ri
        try:
            stdscr.addch(row, box_x,           curses.ACS_VLINE, panel_attr)
            stdscr.addch(row, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
            stdscr.addstr(row, box_x + 1, ' ' * (BOX_W - 2))
        except curses.error:
            pass
        if text is None:
            try:
                for bx in range(1, BOX_W - 1):
                    stdscr.addch(row, box_x + bx, curses.ACS_HLINE, panel_attr)
            except curses.error:
                pass
        elif text:
            attr = head_attr if ri == 0 else panel_attr
            try:
                stdscr.addstr(row, box_x + 2, text[:inner_w + 2], attr)
            except curses.error:
                pass

    # Bottom border
    bot = box_y + 1 + len(rows_content)
    try:
        stdscr.addch(bot, box_x, curses.ACS_LLCORNER, panel_attr)
        for bx in range(1, BOX_W - 1):
            stdscr.addch(bot, box_x + bx, curses.ACS_HLINE, panel_attr)
        stdscr.addch(bot, box_x + BOX_W - 1, curses.ACS_LRCORNER, panel_attr)
    except curses.error:
        pass

    stdscr.refresh()
    stdscr.getch()


def show_targeting(stdscr, tiles, px, py, player, visible, explored,
                   items_on_map, stair_up, stair_down, current_floor,
                   enemies_on_map, log, terminals_on_map=None):
    """Targeting cursor for ranged attack.
    Tab cycles targets. Enter fires. Esc/F cancels.
    Returns (target_pos, enemy) or (None, None)."""
    visible_enemies = sorted(
        [(pos, e) for pos, e in enemies_on_map.items() if pos in visible],
        key=lambda pe: abs(pe[0][0] - px) + abs(pe[0][1] - py),
    )
    if not visible_enemies:
        return None, None

    # Instruction shown as the newest log entry during targeting
    hint_log = collections.deque(
        ["TARGETING — Tab: next target   Enter: fire   Esc: cancel"],
        maxlen=LOG_LINES,
    )
    hint_log.extend(log)

    cur = 0
    while True:
        target_pos, target_enemy = visible_enemies[cur]
        tx, ty = target_pos

        # Trajectory from player to target — stop tracing at first wall
        line_tiles = set()
        for lx, ly in _bresenham(px, py, tx, ty):
            if (lx, ly) == (px, py):
                continue
            line_tiles.add((lx, ly))
            if tiles[ly][lx] == WALL:
                break

        draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
             stair_up, stair_down, current_floor, enemies_on_map, hint_log,
             terminals=terminals_on_map, target_line=line_tiles, target_pos=target_pos)

        key = stdscr.getch()

        if key in (27, ord('f'), ord('F')):      # Esc or F — cancel
            return None, None
        if key == 9:                              # Tab — next target
            cur = (cur + 1) % len(visible_enemies)
        if key in (curses.KEY_ENTER, 10, 13):    # Enter — fire
            return target_pos, target_enemy


def show_character_creation(stdscr):
    """Multi-step character creation wizard. Returns a fully configured Player."""
    panel_attr  = curses.color_pair(COLOR_PANEL)
    header_attr = panel_attr | curses.A_BOLD
    sel_attr    = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD

    race_names  = list(RACES.keys())
    class_names = list(CLASSES.keys())

    def clr():
        stdscr.erase()

    def safe_addstr(row, col, text, attr=0):
        try:
            stdscr.addstr(row, col, text, attr)
        except curses.error:
            pass

    def compute_base(race_name, class_name):
        """Apply race + class mods to STAT_BASE, clamped to STAT_MIN."""
        rmods = RACES[race_name]['mods']
        cmods = CLASSES[class_name]['mods']
        result = {}
        for s in STATS:
            val = STAT_BASE + rmods.get(s, 0) + cmods.get(s, 0)
            result[s] = max(STAT_MIN, val)
        return result

    def mod_str(mods):
        parts = []
        for s, label in zip(STATS, STAT_LABELS):
            v = mods.get(s, 0)
            if v != 0:
                parts.append(f"{label[0]}{v:+d}")
        return '  '.join(parts) if parts else '(no modifiers)'

    step       = 0
    name       = ''
    race_idx   = 0
    class_idx  = 0
    alloc      = {s: 0 for s in STATS}
    stat_cursor = 0  # index into STATS for point-buy step

    while True:
        term_h, term_w = stdscr.getmaxyx()
        clr()

        # ── Step 0: Name ────────────────────────────────────────────────────
        if step == 0:
            title = "CHARACTER CREATION — Name"
            safe_addstr(1, 2, title, header_attr)
            safe_addstr(3, 2, "Enter your character's name (max 20 chars):", panel_attr)
            cursor_name = name + '_'
            safe_addstr(5, 4, cursor_name[:term_w - 5], sel_attr)
            safe_addstr(7, 2, "Press Enter to continue.", panel_attr)
            stdscr.refresh()

            key = stdscr.getch()
            if key in (curses.KEY_ENTER, 10, 13):
                if name.strip():
                    step = 1
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                name = name[:-1]
            elif 32 <= key <= 126 and len(name) < 20:
                name += chr(key)

        # ── Step 1: Race ─────────────────────────────────────────────────────
        elif step == 1:
            title = "CHARACTER CREATION — Race"
            safe_addstr(1, 2, title, header_attr)
            safe_addstr(3, 2, "W/S: navigate   Enter: select   Esc: back", panel_attr)

            for i, rname in enumerate(race_names):
                row    = 5 + i * 3
                rdata  = RACES[rname]
                prefix = '> ' if i == race_idx else '  '
                attr   = sel_attr if i == race_idx else panel_attr
                safe_addstr(row,     2, f"{prefix}{rname}", attr)
                safe_addstr(row + 1, 4, rdata['desc'][:term_w - 6], panel_attr)
                safe_addstr(row + 2, 4, mod_str(rdata['mods']), panel_attr)

            stdscr.refresh()
            key = stdscr.getch()

            if key == 27:
                step = 0
            elif key in (curses.KEY_UP, ord('w'), ord('W')):
                race_idx = max(0, race_idx - 1)
            elif key in (curses.KEY_DOWN, ord('s'), ord('S')):
                race_idx = min(len(race_names) - 1, race_idx + 1)
            elif key in (curses.KEY_ENTER, 10, 13):
                alloc = {s: 0 for s in STATS}   # reset alloc on race change
                step  = 2

        # ── Step 2: Class ────────────────────────────────────────────────────
        elif step == 2:
            title = "CHARACTER CREATION — Class"
            safe_addstr(1, 2, title, header_attr)
            safe_addstr(3, 2, "W/S: navigate   Enter: select   Esc: back", panel_attr)

            for i, cname in enumerate(class_names):
                row    = 5 + i * 3
                cdata  = CLASSES[cname]
                prefix = '> ' if i == class_idx else '  '
                attr   = sel_attr if i == class_idx else panel_attr
                safe_addstr(row,     2, f"{prefix}{cname}", attr)
                safe_addstr(row + 1, 4, cdata['desc'][:term_w - 6], panel_attr)
                safe_addstr(row + 2, 4, mod_str(cdata['mods']), panel_attr)

            stdscr.refresh()
            key = stdscr.getch()

            if key == 27:
                step = 1
            elif key in (curses.KEY_UP, ord('w'), ord('W')):
                class_idx = max(0, class_idx - 1)
            elif key in (curses.KEY_DOWN, ord('s'), ord('S')):
                class_idx = min(len(class_names) - 1, class_idx + 1)
            elif key in (curses.KEY_ENTER, 10, 13):
                alloc = {s: 0 for s in STATS}   # reset alloc on class change
                step  = 3

        # ── Step 3: Point Buy ─────────────────────────────────────────────────
        elif step == 3:
            rname   = race_names[race_idx]
            cname   = class_names[class_idx]
            base    = compute_base(rname, cname)
            remain  = POINT_BUY_POINTS - sum(alloc.values())

            title = "CHARACTER CREATION — Distribute Points"
            safe_addstr(1, 2, title, header_attr)
            safe_addstr(3, 2,
                f"Points remaining: {remain}   "
                "W/S: select stat   A/D: add/remove   Enter: confirm   Esc: back",
                panel_attr)

            for i, (s, label) in enumerate(zip(STATS, STAT_LABELS)):
                row = 5 + i * 2
                val = base[s] + alloc[s]
                bar = '█' * val + '░' * (STAT_MAX - val)
                attr = sel_attr if i == stat_cursor else panel_attr
                safe_addstr(row,     2, f"{'> ' if i == stat_cursor else '  '}{label:<10} {val:>2}  {bar[:STAT_MAX]}", attr)

            safe_addstr(5 + len(STATS) * 2 + 1, 2,
                f"Max HP will be: {20 + (base['body'] + alloc['body']) * 2}",
                panel_attr)

            stdscr.refresh()
            key = stdscr.getch()

            if key == 27:
                step = 2
            elif key in (curses.KEY_UP, ord('w'), ord('W')):
                stat_cursor = max(0, stat_cursor - 1)
            elif key in (curses.KEY_DOWN, ord('s'), ord('S')):
                stat_cursor = min(len(STATS) - 1, stat_cursor + 1)
            elif key in (curses.KEY_RIGHT, ord('d'), ord('D')):
                s   = STATS[stat_cursor]
                val = base[s] + alloc[s]
                if remain > 0 and val < STAT_MAX:
                    alloc[s] += 1
            elif key in (curses.KEY_LEFT, ord('a'), ord('A')):
                s = STATS[stat_cursor]
                if alloc[s] > 0:
                    alloc[s] -= 1
            elif key in (curses.KEY_ENTER, 10, 13):
                step = 4

        # ── Step 4: Confirm ────────────────────────────────────────────────────
        elif step == 4:
            rname  = race_names[race_idx]
            cname  = class_names[class_idx]
            base   = compute_base(rname, cname)
            final  = {s: base[s] + alloc[s] for s in STATS}
            max_hp = 20 + final['body'] * 2

            title = "CHARACTER CREATION — Confirm"
            safe_addstr(1, 2, title, header_attr)
            safe_addstr(3, 2, f"Name:   {name}", panel_attr)
            safe_addstr(4, 2, f"Race:   {rname}", panel_attr)
            safe_addstr(5, 2, f"Class:  {cname}", panel_attr)
            safe_addstr(7, 2, "STATS", header_attr)

            for i, (s, label) in enumerate(zip(STATS, STAT_LABELS)):
                safe_addstr(8 + i, 4, f"{label:<10} {final[s]:>2}", panel_attr)

            safe_addstr(8 + len(STATS) + 1, 2, f"Max HP: {max_hp}", panel_attr)
            safe_addstr(8 + len(STATS) + 3, 2, "Enter: begin game   Esc: back", panel_attr)

            stdscr.refresh()
            key = stdscr.getch()

            if key == 27:
                step = 3
            elif key in (curses.KEY_ENTER, 10, 13):
                return Player(
                    name=name,
                    race=rname,
                    char_class=cname,
                    body=final['body'],
                    reflex=final['reflex'],
                    mind=final['mind'],
                    tech=final['tech'],
                    presence=final['presence'],
                )


def apply_effect(entity, effect, turns):
    """Apply or refresh a status effect (keeps max remaining turns)."""
    entity.active_effects[effect] = max(entity.active_effects.get(effect, 0), turns)


def tick_effects(entity, label):
    """Tick active effects one turn. Returns list of message strings."""
    msgs = []
    expired = []
    for effect, turns in list(entity.active_effects.items()):
        if effect in EFFECT_DAMAGE:
            dmg = EFFECT_DAMAGE[effect]
            entity.hp -= dmg
            msgs.append(f"{label} takes {dmg} {effect} damage!")
        entity.active_effects[effect] = turns - 1
        if turns - 1 <= 0:
            expired.append(effect)
    for e in expired:
        del entity.active_effects[e]
        msgs.append(f"{label} is no longer affected by {e}.")
    return msgs


def show_levelup_modal(stdscr, player):
    """Modal overlay for choosing a stat to increase on level-up. No cancel — must pick."""
    STAT_DESC = {
        'body':     '+HP / ATK',
        'reflex':   '+dodge',
        'mind':     '+XP / FOV',
        'tech':     '+ranged',
        'presence': '+intimidate',
    }
    BOX_W      = 34
    BOX_H      = 13
    panel_attr = curses.color_pair(COLOR_PANEL)
    hi_attr    = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD
    head_attr  = panel_attr | curses.A_BOLD

    term_h, term_w = stdscr.getmaxyx()
    box_y = max(0, (term_h - BOX_H) // 2)
    box_x = max(0, (term_w - BOX_W) // 2)

    cursor = 0

    def _draw():
        # Border
        try:
            stdscr.addch(box_y, box_x, curses.ACS_ULCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(box_y, box_x + BOX_W - 1, curses.ACS_URCORNER, panel_attr)
        except curses.error:
            pass
        for ry in range(1, BOX_H - 1):
            try:
                stdscr.addch(box_y + ry, box_x, curses.ACS_VLINE, panel_attr)
                stdscr.addch(box_y + ry, box_x + BOX_W - 1, curses.ACS_VLINE, panel_attr)
            except curses.error:
                pass
        try:
            stdscr.addch(box_y + BOX_H - 1, box_x, curses.ACS_LLCORNER, panel_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(box_y + BOX_H - 1, box_x + bx, curses.ACS_HLINE, panel_attr)
            stdscr.addch(box_y + BOX_H - 1, box_x + BOX_W - 1, curses.ACS_LRCORNER, panel_attr)
        except curses.error:
            pass

        # Title row
        title = f"  LEVEL UP!  Rank -> {player.level}  "
        try:
            stdscr.addstr(box_y + 1, box_x + 1, title[:BOX_W - 2].center(BOX_W - 2), head_attr)
        except curses.error:
            pass

        # Prompt row
        try:
            stdscr.addstr(box_y + 3, box_x + 1,
                          "  Choose a stat to increase:  "[:BOX_W - 2],
                          panel_attr)
        except curses.error:
            pass

        # Stat rows (rows 5-9)
        for i, stat in enumerate(STATS):
            row = box_y + 5 + i
            val = getattr(player, stat)
            label = STAT_LABELS[i]
            desc  = STAT_DESC[stat]
            prefix = '>' if i == cursor else ' '
            line = f" {prefix} {label:<9}{val:>2}  {desc}"
            attr = hi_attr if i == cursor else panel_attr
            try:
                stdscr.addstr(row, box_x + 1, line[:BOX_W - 2].ljust(BOX_W - 2), attr)
            except curses.error:
                pass

        # Footer
        try:
            stdscr.addstr(box_y + 11, box_x + 1,
                          "  W/S: select   Enter: pick  "[:BOX_W - 2].center(BOX_W - 2),
                          panel_attr)
        except curses.error:
            pass

        stdscr.refresh()

    while True:
        _draw()
        key = stdscr.getch()
        if key in (ord('w'), ord('W'), curses.KEY_UP):
            cursor = (cursor - 1) % len(STATS)
        elif key in (ord('s'), ord('S'), curses.KEY_DOWN):
            cursor = (cursor + 1) % len(STATS)
        elif key in (ord('\n'), curses.KEY_ENTER, 10, 13):
            stat_name = STATS[cursor]
            new_val = min(STAT_MAX, getattr(player, stat_name) + 1)
            setattr(player, stat_name, new_val)
            if stat_name == 'body':
                player.max_hp = 20 + player.body * 2
            player.hp = player.max_hp
            break


def enemy_turn(enemies, tiles, px, py, visible, player):
    """Move and attack with every enemy. Returns list of combat message strings."""
    msgs       = []
    player_pos = (px, py)
    # Track occupied positions so enemies don't pile onto the same tile this turn.
    # Updated as enemies move so later enemies see the current layout.
    occupied = set(enemies.keys())

    intimidate_chance = max(0, (player.presence - 5) * 3)

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

        behaviour = enemy.behaviour

        # ── Ranged (Gunner) ──────────────────────────────────────────────────
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
            continue

        # ── Fast (Lurker) ────────────────────────────────────────────────────
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
            continue

        # ── Brute ────────────────────────────────────────────────────────────
        if behaviour == 'brute':
            if epos in visible:
                if enemy.cooldown > 0:
                    enemy.cooldown -= 1
                    continue
                # Act this turn, then set cooldown
                enemy.cooldown = 1
                _astar_step(enemy, epos)
            else:
                _random_walk(enemy, epos)
            continue

        # ── Exploder / Melee (default) ───────────────────────────────────────
        if epos in visible:
            _astar_step(enemy, epos)
        else:
            _random_walk(enemy, epos)

    return msgs


def show_game_over(stdscr, player, floor_reached):
    """Show game-over screen. Returns True to restart, False to quit."""
    panel_attr  = curses.color_pair(COLOR_PANEL)
    header_attr = curses.color_pair(COLOR_HP_LOW) | curses.A_BOLD

    while True:
        term_h, term_w = stdscr.getmaxyx()
        stdscr.erase()

        lines = [
            ("* YOU DIED *",                         header_attr),
            ("",                                     0),
            (f"Name:   {player.name}",               panel_attr),
            (f"Race:   {player.race}",               panel_attr),
            (f"Class:  {player.char_class}",         panel_attr),
            ("",                                     0),
            (f"Floor reached: {floor_reached}",      panel_attr),
            (f"Level:         {player.level}",       panel_attr),
            ("",                                     0),
            ("R: new character    Q: quit",          panel_attr),
        ]

        start_row = max(0, (term_h - len(lines)) // 2)
        for i, (text, attr) in enumerate(lines):
            col = max(0, (term_w - len(text)) // 2)
            try:
                stdscr.addstr(start_row + i, col, text, attr)
            except curses.error:
                pass

        stdscr.refresh()
        key = stdscr.getch()

        if key in (ord('r'), ord('R')):
            return True
        if key in (ord('q'), ord('Q')):
            return False


def main(stdscr):
    curses.curs_set(0)
    stdscr.keypad(True)
    setup_colors()

    player = show_character_creation(stdscr)
    current_floor = 1
    floors        = {}
    floor_data    = make_floor(1)
    floors[1]     = floor_data
    tiles         = floor_data['tiles']
    px, py        = floor_data['start']
    items_on_map   = floor_data['items']
    enemies_on_map = floor_data['enemies']
    terminals_on_map = floor_data['terminals']
    special_rooms    = floor_data.get('special_rooms', {})
    stair_up      = floor_data['stair_up']
    stair_down    = floor_data['stair_down']
    explored      = floor_data['explored']
    log      = collections.deque(maxlen=LOG_LINES)
    visible  = compute_fov(tiles, px, py, player.fov_radius)
    explored |= visible
    draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
         stair_up, stair_down, current_floor, enemies_on_map, log,
         terminals=terminals_on_map, special_rooms=special_rooms)

    MOVE_KEYS = {
        # Cardinal — WASD
        ord('w'):         ( 0, -1),
        ord('a'):         (-1,  0),
        ord('s'):         ( 0,  1),
        ord('d'):         ( 1,  0),
        # Cardinal — arrow keys
        curses.KEY_UP:    ( 0, -1),
        curses.KEY_LEFT:  (-1,  0),
        curses.KEY_DOWN:  ( 0,  1),
        curses.KEY_RIGHT: ( 1,  0),
        # Diagonal — numpad (numlock off: curses named constants)
        curses.KEY_A1:    (-1, -1),   # numpad 7 (NW)
        curses.KEY_A3:    ( 1, -1),   # numpad 9 (NE)
        curses.KEY_C1:    (-1,  1),   # numpad 1 (SW)
        curses.KEY_C3:    ( 1,  1),   # numpad 3 (SE)
        # Diagonal — numpad (numlock on: sends plain digits)
        ord('7'):         (-1, -1),
        ord('9'):         ( 1, -1),
        ord('1'):         (-1,  1),
        ord('3'):         ( 1,  1),
    }

    won = False
    while True:
        key = stdscr.getch()

        if key in (ord('q'), ord('Q')):
            break

        if key in (ord('r'), ord('R')):
            current_floor  = 1
            floors         = {}
            floor_data     = make_floor(1)
            floors[1]      = floor_data
            tiles          = floor_data['tiles']
            px, py         = floor_data['start']
            items_on_map     = floor_data['items']
            enemies_on_map   = floor_data['enemies']
            terminals_on_map = floor_data['terminals']
            special_rooms    = floor_data.get('special_rooms', {})
            stair_up         = floor_data['stair_up']
            stair_down       = floor_data['stair_down']
            explored         = floor_data['explored']
            log              = collections.deque(maxlen=LOG_LINES)

        if key in (ord('i'), ord('I')):
            result = show_equipment_screen(stdscr, player, px, py, items_on_map)
            if result:
                log.appendleft(result)

        if key in (ord('u'), ord('U')):
            consumables = [i for i in player.inventory if i.consumable]
            if consumables:
                item = consumables[0]
                log.appendleft(item.use(player))
                if item.effect in ('poison', 'burn', 'stun'):
                    targets = [(pos, e) for pos, e in enemies_on_map.items() if pos in visible]
                    if targets:
                        tpos, target = min(targets, key=lambda pe: abs(pe[0][0]-px)+abs(pe[0][1]-py))
                        apply_effect(target, item.effect, item.effect_turns)
                        log.appendleft(f"{target.name} is hit — {item.effect}!")
                    else:
                        log.appendleft("No visible target.")
                player.inventory.remove(item)
            else:
                log.appendleft("No consumables in inventory.")

        if key in (ord('t'), ord('T')):
            in_shop = False
            for sroom in special_rooms.values():
                if (px, py) in sroom['tiles'] and sroom['type'] == 'shop':
                    in_shop = True
                    result = show_shop_screen(stdscr, player, sroom['stock'])
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
                e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player)
                for em in e_msgs:
                    log.appendleft(em)
            else:
              weapon = player.equipment.get('weapon')
              if not weapon or not weapon.ranged:
                log.appendleft("No ranged weapon equipped.")
              else:
                target_pos, _ = show_targeting(
                    stdscr, tiles, px, py, player, visible, explored,
                    items_on_map, stair_up, stair_down, current_floor,
                    enemies_on_map, log, terminals_on_map)
                if target_pos is not None:
                    # Trace from player toward target; hit first enemy in path
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
                                show_levelup_modal(stdscr, player)
                            if enemy.boss:
                                won = True
                        else:
                            log.appendleft(f"You shoot {enemy.name} for {dmg}.")
                    else:
                        log.appendleft("The shot goes wide.")

                    # Firing costs a turn
                    e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player)
                    for em in e_msgs:
                        log.appendleft(em)

        if key in MOVE_KEYS:
            if 'stun' in player.active_effects:
                log.appendleft("You are stunned and cannot act!")
                for msg in tick_effects(player, "You"):
                    log.appendleft(msg)
                e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player)
                for em in e_msgs:
                    log.appendleft(em)
            else:
                for msg in tick_effects(player, "You"):
                    log.appendleft(msg)
                dx, dy = MOVE_KEYS[key]
                nx, ny = px + dx, py + dy
                if (nx, ny) in enemies_on_map:
                    enemy = enemies_on_map[(nx, ny)]
                    dmg = max(1, player.atk - enemy.dfn)
                    enemy.hp -= dmg
                    if enemy.hp <= 0:
                        del enemies_on_map[(nx, ny)]
                        if enemy.behaviour == 'exploder':
                            splash = max(1, int(enemy.atk * 0.5))
                            player.hp -= splash
                            log.appendleft(f"{enemy.name} detonates — caught in blast! -{splash} HP!")
                        n_lv, lvl_msg = player.gain_xp(enemy.xp_reward)
                        cr_drop = max(1, enemy.xp_reward // 2)
                        player.credits += cr_drop
                        log.appendleft(f"You hit {enemy.name} for {dmg}. {enemy.name} destroyed! +{enemy.xp_reward} XP +{cr_drop} cr")
                        if lvl_msg:
                            log.appendleft(lvl_msg)
                        for _ in range(n_lv):
                            show_levelup_modal(stdscr, player)
                        if enemy.boss:
                            won = True
                    else:
                        edm = max(1, enemy.atk - player.dfn)
                        player.hp -= edm
                        log.appendleft(f"You hit {enemy.name} for {dmg}. {enemy.name} hits back for {edm}.")
                elif 0 <= nx < MAP_W and 0 <= ny < MAP_H and tiles[ny][nx] == FLOOR:
                    px, py = nx, ny
                    n_lv, _ = player.gain_xp(1)
                    for _ in range(n_lv):
                        show_levelup_modal(stdscr, player)
                    if (px, py) in items_on_map:
                        picked = items_on_map[(px, py)]
                        if player.pickup(picked):
                            items_on_map.pop((px, py))
                            log.appendleft(f"Picked up {picked.name}.")
                        else:
                            log.appendleft("Inventory full.")

                    if (px, py) in terminals_on_map:
                        t = terminals_on_map[(px, py)]
                        if not t.read:
                            log.appendleft(f"Terminal: {t.title[:44]}")
                            show_terminal(stdscr, t)
                            # Tech bonus: +5 XP per tech point above 5
                            tech_xp = max(0, (player.tech - 5) * 5)
                            if tech_xp:
                                n_lv, lvl_msg = player.gain_xp(tech_xp)
                                log.appendleft(f"Tech interface: +{tech_xp} XP")
                                if lvl_msg:
                                    log.appendleft(lvl_msg)
                                for _ in range(n_lv):
                                    show_levelup_modal(stdscr, player)
                        else:
                            log.appendleft(f"[already read] {t.title[:38]}")

                    # Special room entry
                    for sroom in special_rooms.values():
                        if (px, py) in sroom['tiles']:
                            rtype = sroom['type']
                            if not sroom['triggered']:
                                sroom['triggered'] = True
                                if rtype == 'shop':
                                    log.appendleft("SUPPLY DEPOT — [T] to trade.")
                                elif rtype == 'armory':
                                    gear = [it for it in ITEM_TEMPLATES
                                            if it.slot in ('weapon', 'armor', 'helmet', 'gloves', 'boots')]
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
                                    avail    = list(sroom['tiles'] - {(px, py)})
                                    for pos, (title, lines) in zip(
                                            random.sample(avail, min(3, len(avail))), hub_lore):
                                        terminals_on_map[pos] = Terminal(title, lines)
                                    log.appendleft("TERMINAL HUB — Data nodes online.")
                                elif rtype == 'vault':
                                    cost = 50
                                    if show_vault_prompt(stdscr, cost, player.credits):
                                        if player.credits >= cost:
                                            player.credits -= cost
                                            rare  = [it for it in ITEM_TEMPLATES
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

                    if (px, py) == stair_down:
                        current_floor += 1
                        if current_floor not in floors:
                            floors[current_floor] = make_floor(current_floor)
                        floor_data       = floors[current_floor]
                        tiles            = floor_data['tiles']
                        px, py           = floor_data['start']
                        items_on_map     = floor_data['items']
                        enemies_on_map   = floor_data['enemies']
                        terminals_on_map = floor_data['terminals']
                        special_rooms    = floor_data.get('special_rooms', {})
                        stair_up         = floor_data['stair_up']
                        stair_down       = floor_data['stair_down']
                        explored         = floor_data['explored']
                        arrival = get_theme(current_floor)['msg']
                        log.appendleft(f"You descend to floor {current_floor}.")
                        if arrival:
                            log.appendleft(arrival)
                    elif stair_up and (px, py) == stair_up:
                        current_floor -= 1
                        floor_data       = floors[current_floor]
                        tiles            = floor_data['tiles']
                        px, py           = floor_data['stair_down']
                        items_on_map     = floor_data['items']
                        enemies_on_map   = floor_data['enemies']
                        terminals_on_map = floor_data['terminals']
                        special_rooms    = floor_data.get('special_rooms', {})
                        stair_up         = floor_data['stair_up']
                        stair_down       = floor_data['stair_down']
                        explored         = floor_data['explored']
                        log.appendleft(f"You ascend to floor {current_floor}.")

                e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player)
                for em in e_msgs:
                    log.appendleft(em)

        visible   = compute_fov(tiles, px, py, player.fov_radius)
        explored |= visible

        # Win check
        if won:
            draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
                 stair_up, stair_down, current_floor, enemies_on_map, log,
                 terminals=terminals_on_map, special_rooms=special_rooms)
            show_terminal(stdscr, WIN_TERMINAL)
            if show_win_screen(stdscr, player):
                # New run
                won            = False
                player         = show_character_creation(stdscr)
                current_floor  = 1
                floors         = {}
                floor_data     = make_floor(1)
                floors[1]      = floor_data
                tiles          = floor_data['tiles']
                px, py         = floor_data['start']
                items_on_map   = floor_data['items']
                enemies_on_map = floor_data['enemies']
                terminals_on_map = floor_data['terminals']
                special_rooms    = floor_data.get('special_rooms', {})
                stair_up       = floor_data['stair_up']
                stair_down     = floor_data['stair_down']
                explored       = floor_data['explored']
                log            = collections.deque(maxlen=LOG_LINES)
                visible        = compute_fov(tiles, px, py, player.fov_radius)
                explored      |= visible
            else:
                break

        # Death check
        if player.hp <= 0:
            player.hp = 0
            draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
                 stair_up, stair_down, current_floor, enemies_on_map, log,
                 terminals=terminals_on_map, special_rooms=special_rooms)
            if show_game_over(stdscr, player, current_floor):
                player           = show_character_creation(stdscr)
                current_floor    = 1
                floors           = {}
                floor_data       = make_floor(1)
                floors[1]        = floor_data
                tiles            = floor_data['tiles']
                px, py           = floor_data['start']
                items_on_map     = floor_data['items']
                enemies_on_map   = floor_data['enemies']
                terminals_on_map = floor_data['terminals']
                special_rooms    = floor_data.get('special_rooms', {})
                stair_up         = floor_data['stair_up']
                stair_down       = floor_data['stair_down']
                explored         = floor_data['explored']
                log              = collections.deque(maxlen=LOG_LINES)
                visible          = compute_fov(tiles, px, py, player.fov_radius)
                explored        |= visible
            else:
                break

        draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
             stair_up, stair_down, current_floor, enemies_on_map, log,
             terminals=terminals_on_map, special_rooms=special_rooms)


if __name__ == '__main__':
    curses.wrapper(main)
