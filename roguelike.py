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


def make_sites():
    """Create a fresh list of Site objects for a new run."""
    return [
        Site('Erebus Station',   'E', depth=10, fuel_cost=0,
             desc='ISC research station. Origin of the signal.'),

        Site('Frontier Town',    'T', depth=1,  fuel_cost=1,
             desc='Rough settlement. Supplies available.',
             enemy_density=0.0,
             theme_fn=lambda f: {**get_theme(1), 'name': 'Frontier Town'}),

        Site('Wreck: ISC Calyx', 'W', depth=4,  fuel_cost=2,
             desc='Drifting hulk. Security drones still active.',
             enemy_density=1.4,
             theme_fn=lambda f: {**get_theme(min(f, 3)),
                                 'name': ['Cargo Hold', 'Crew Deck',
                                          'Bridge', 'Reactor'][f - 1]}),

        Site('Colony Ruin KE-7', 'C', depth=6,  fuel_cost=2,
             desc='Abandoned colony. Something moved in.',
             theme_fn=lambda f: {**get_theme(min(f + 1, 9)),
                                 'name': ['Surface', 'Sub-Level 1', 'Sub-Level 2',
                                          'Bunker', 'Lab', 'Core'][f - 1]}),
    ]


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
    Item('Sensor Kit',     'use',    char='?', consumable=True, effect='scan'),
    Item('Fuel Cell',      'use',    char='%', consumable=True, fuel=1),
    # New consumables
    Item('Smoke Grenade',  'use', char='!', consumable=True, effect='smoke'),
    Item('EMP Charge',     'use', char='!', consumable=True, effect='emp'),
    Item('Scanner Chip',   'use', char='?', consumable=True, effect='scanner'),
    Item('Stimpack',       'use', char='+', consumable=True, effect='stim'),
    Item('Proximity Mine', 'use', char='*', consumable=True, effect='prox_mine'),
    # Tools — active equipment slot
    Item('Bypass Kit',    'tool', char='[', tool_effect='bypass',
         charges=3, max_charges=3, skill_req='engineering', skill_level=1),
    Item('Signal Jammer', 'tool', char='[', tool_effect='jammer',
         charges=2, max_charges=2, skill_req='electronics', skill_level=1),
    Item('Grapple Line',  'tool', char='[', tool_effect='grapple',
         charges=1, max_charges=1),
    Item('Repair Drone',  'tool', char='[', tool_effect='repair_drone',
         charges=2, max_charges=2, skill_req='engineering', skill_level=1),
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
    (Item('Sensor Kit',      'use',    char='?', consumable=True, effect='scan'), 20),
    # New consumables
    (Item('Smoke Grenade',  'use', char='!', consumable=True, effect='smoke'),    25),
    (Item('EMP Charge',     'use', char='!', consumable=True, effect='emp'),      35),
    (Item('Scanner Chip',   'use', char='?', consumable=True, effect='scanner'),  30),
    (Item('Stimpack',       'use', char='+', consumable=True, effect='stim'),     40),
    (Item('Proximity Mine', 'use', char='*', consumable=True, effect='prox_mine'), 30),
    # Tools
    (Item('Bypass Kit',    'tool', char='[', tool_effect='bypass',
          charges=3, max_charges=3, skill_req='engineering', skill_level=1),      45),
    (Item('Signal Jammer', 'tool', char='[', tool_effect='jammer',
          charges=2, max_charges=2, skill_req='electronics', skill_level=1),      60),
    (Item('Grapple Line',  'tool', char='[', tool_effect='grapple',
          charges=1, max_charges=1),                                               50),
    (Item('Repair Drone',  'tool', char='[', tool_effect='repair_drone',
          charges=2, max_charges=2, skill_req='engineering', skill_level=1),      55),
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
POINT_BUY_POINTS      = 20          # was 10
STARTING_SKILL_POINTS = 4           # free skill points allocated in Step 4 of creation
SKILL_MAX             = 5           # maximum level for any skill

SKILLS = {
    'melee':        {'name': 'Melee',        'cat': 'Combat',     'desc': 'Close-quarters combat.',           'effect': '+1 ATK/lv'},
    'firearms':     {'name': 'Firearms',     'cat': 'Combat',     'desc': 'Ranged weapon proficiency.',       'effect': '+1 rATK/lv'},
    'tactics':      {'name': 'Tactics',      'cat': 'Combat',     'desc': 'Tactical positioning and timing.', 'effect': '+2% dodge/lv'},
    'engineering':  {'name': 'Engineering',  'cat': 'Technical',  'desc': 'Repair, craft, disarm traps.',     'effect': 'See traps(1) Disarm(2)'},
    'hacking':      {'name': 'Hacking',      'cat': 'Technical',  'desc': 'Terminal intrusion depth.',        'effect': 'Terminals (see levels)'},
    'electronics':  {'name': 'Electronics',  'cat': 'Technical',  'desc': 'Sensor arrays and drone control.', 'effect': 'Radar (future)'},
    'pilot':        {'name': 'Pilot',        'cat': 'Navigation', 'desc': 'Ship handling and navigation.',    'effect': '-1 fuel/2 lv'},
    'cartography':  {'name': 'Cartography',  'cat': 'Navigation', 'desc': 'Spatial awareness and mapping.',   'effect': '+1 FOV/2 lv'},
    'survival':     {'name': 'Survival',     'cat': 'Navigation', 'desc': 'Hazard resistance and endurance.', 'effect': '-1 effect turn/lv'},
    'intimidation': {'name': 'Intimidation', 'cat': 'Social',     'desc': 'Projecting dominance and fear.',   'effect': '+3% hesitate/lv'},
    'barter':       {'name': 'Barter',       'cat': 'Social',     'desc': 'Negotiating prices and deals.',    'effect': '-5% shop price/lv'},
    'medicine':     {'name': 'Medicine',     'cat': 'Medicine',   'desc': 'First aid and field surgery.',     'effect': '+2 HP/use/lv'},
}

SKILL_ORDER = ['melee', 'firearms', 'tactics',
               'engineering', 'hacking', 'electronics',
               'pilot', 'cartography', 'survival',
               'intimidation', 'barter', 'medicine']

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
                 'mods': {'body': 3, 'reflex': 2, 'mind': -1, 'tech': -1, 'presence': -1},
                 'skills': {'melee': 1, 'tactics': 1}},
    'Engineer': {'desc': 'Tech expert. Builds, repairs, and improvises solutions.',
                 'mods': {'body': -1, 'reflex': -1, 'mind': 2, 'tech': 3, 'presence': -1},
                 'skills': {'engineering': 1, 'electronics': 1}},
    'Medic':    {'desc': 'Field medic and negotiator. Keeps the team alive.',
                 'mods': {'body': -2, 'reflex': -1, 'mind': 2, 'tech': 1, 'presence': 3},
                 'skills': {'medicine': 1, 'survival': 1}},
    'Hacker':   {'desc': 'Systems infiltrator. Exploits technology and environments.',
                 'mods': {'body': -2, 'reflex': 2, 'mind': 1, 'tech': 3, 'presence': -2},
                 'skills': {'hacking': 1, 'cartography': 1}},
}


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
        self.max_hp     = 20 + body * 2   # body=5 → 30 HP (matches old default)
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

    @property
    def atk(self):
        weapon_bonus = sum(i.atk for i in self.equipment.values() if i)
        return 1 + max(0, (self.body - 5) // 2) + weapon_bonus + self.skills.get('melee', 0)
        # body=5 → 1 (same as before); body=7 → 2; body=10 → 3

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
        """XP multiplier from mind stat (mind=5 → 1.0x, mind=10 → 1.25x)."""
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


HAZARD_DATA = {
    'mine':     {'char': '^', 'effect': 'burn',  'effect_turns': 3, 'dmg': 8, 'triggers': 1},
    'acid':     {'char': '~', 'effect': 'burn',  'effect_turns': 3, 'dmg': 0, 'triggers': 5},
    'electric': {'char': '=', 'effect': 'stun',  'effect_turns': 2, 'dmg': 0, 'triggers': 4},
}


def scatter_hazards(tiles, floor_num, n=0, exclude=()):
    """Place hazard tiles. Returns {(x,y): hazard_dict} or {} if n=0."""
    if n <= 0:
        return {}
    hazard_types   = ['mine', 'acid', 'electric']
    hazard_weights = [40, 30, 30]
    floors    = [(x, y) for y in range(MAP_H) for x in range(MAP_W)
                 if tiles[y][x] == FLOOR and (x, y) not in exclude]
    positions = random.sample(floors, min(n, len(floors)))
    result = {}
    for pos in positions:
        htype = random.choices(hazard_types, weights=hazard_weights)[0]
        hdata = HAZARD_DATA[htype]
        result[pos] = {
            'type':          htype,
            'char':          hdata['char'],
            'triggers_left': hdata['triggers'],
            'revealed':      False,
        }
    return result


def scatter_special_rooms(tiles, rooms, floor_num, is_final=False):
    """Pick interior rooms and assign special types. Returns dict keyed by int -> spec dict."""
    if is_final:
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


def make_floor(floor_num, theme_fn=None, enemy_density=1.0, is_final=False, place_boss=False):
    theme_fn = theme_fn or get_theme
    theme    = theme_fn(floor_num)
    tiles, rooms = generate_dungeon(**theme['gen'])
    if rooms:
        start = rooms[0].center()
    else:
        start = (MAP_W // 2, MAP_H // 2)

    stair_up   = start if floor_num > 1 else None
    stair_down = None if is_final else (rooms[-1].center() if rooms else start)

    exclude_set = {stair_up, stair_down, start} - {None}
    n_enemies = int((3 + floor_num * 2) * enemy_density)
    if n_enemies > 0:
        enemies = scatter_enemies(tiles, floor_num, n=n_enemies,
                                  exclude=exclude_set, weights=theme['weights'])
    else:
        enemies = {}

    # Boss floor: place the boss in the last room
    if place_boss and rooms:
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

    special_rooms = scatter_special_rooms(tiles, rooms, floor_num, is_final=is_final)

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

    if floor_num <= 2:
        n_hazards = 0
    elif floor_num <= 5:
        n_hazards = random.randint(0, 2)
    else:
        n_hazards = random.randint(1, 3)
    hazards = scatter_hazards(
        tiles, floor_num, n=n_hazards,
        exclude=exclude_set | set(enemies) | set(items) | all_special_tiles)

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
        'hazards':       hazards,
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
COLOR_HAZARD       = 20 # red         — danger tiles


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
    curses.init_pair(COLOR_HAZARD,       curses.COLOR_RED,     -1)


def draw_panel(stdscr, player, col, rows, current_floor, max_floor=MAX_FLOOR, floor_name=None):
    """Draw the character stats panel starting at column `col`."""
    panel_attr  = curses.color_pair(COLOR_PANEL)
    header_attr = panel_attr | curses.A_BOLD

    hp_attr = (curses.color_pair(COLOR_HP_LOW) | curses.A_BOLD
               if player.hp <= player.max_hp // 4
               else panel_attr)

    if floor_name is None:
        floor_name = get_theme(current_floor)['name']

    lines = [
        ("CHARACTER",                                       header_attr),
        (None, 0),                                          # blank
        (player.name[:PANEL_W - 1],                        panel_attr),
        (f"{player.race} {player.char_class}"[:PANEL_W-1], panel_attr),
        (None, 0),                                          # blank
        (f"Floor: {current_floor}/{max_floor}",            panel_attr),
        (floor_name[:PANEL_W - 1],                         panel_attr),
        (f"HP:  {player.hp:>3} / {player.max_hp:<3}",     hp_attr),
        (f"LVL: {player.level}",                           panel_attr),
        (f"XP:  {player.xp:>3} / {player.xp_next:<3}",   panel_attr),
        (f"ATK: {player.atk}",                             panel_attr),
        (f"DEF: {player.dfn}",                             panel_attr),
        (f"DODGE: {player.dodge_chance}%",                 panel_attr),
        (f"CR:   {player.credits}",                        panel_attr),
        (f"Fuel: {player.fuel}",                           panel_attr),
        (None, 0),                                          # blank
        ("[I]Equip [K]Skills [X]Tool",                     panel_attr),
    ]

    if player.skill_points:
        lines.insert(-1, (f"SP:   {player.skill_points}",
                          curses.color_pair(COLOR_PLAYER) | curses.A_BOLD))

    tool = player.equipment.get('tool')
    if tool:
        tool_text = f"Tool: {tool.name} [{tool.charges}/{tool.max_charges}]"
        lines.insert(-1, (tool_text[:PANEL_W - 1], curses.color_pair(COLOR_ITEM)))

    if player.active_effects:
        abbr = {'poison': 'Psn', 'burn': 'Brn', 'stun': 'Stn',
                'repair': 'Rep', 'stim': 'Stm'}
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
         terminals=None, target_line=None, target_pos=None, special_rooms=None,
         max_floor=MAX_FLOOR, theme_override=None, hazards=None, smoke_tiles=None):
    term_h, term_w = stdscr.getmaxyx()
    view_h  = term_h - (LOG_LINES + 1)   # reserve log rows + divider
    map_w   = term_w - PANEL_W - 1   # columns available for the map

    # Center camera on player, clamped to map bounds
    cam_x = max(0, min(px - map_w  // 2, max(0, MAP_W - map_w)))
    cam_y = max(0, min(py - view_h // 2, max(0, MAP_H - view_h)))

    stdscr.erase()

    theme     = theme_override if theme_override is not None else get_theme(current_floor)
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
                elif hazards and (mx, my) in hazards:
                    h = hazards[(mx, my)]
                    if player.skills.get('engineering', 0) >= 1 or h['revealed']:
                        ch   = h['char']
                        attr = curses.color_pair(COLOR_HAZARD) | curses.A_BOLD
                    else:
                        ch   = FLOOR
                        attr = (curses.color_pair(COLOR_SPECIAL) | curses.A_DIM
                                if (mx, my) in special_tile_set
                                else curses.color_pair(COLOR_FLOOR) | curses.A_DIM)
                elif smoke_tiles and (mx, my) in smoke_tiles:
                    ch   = '%'
                    attr = curses.color_pair(COLOR_DARK) | curses.A_DIM
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
                elif hazards and (mx, my) in hazards:
                    h = hazards[(mx, my)]
                    if player.skills.get('engineering', 0) >= 1 or h['revealed']:
                        ch   = h['char']
                        attr = curses.color_pair(COLOR_HAZARD) | curses.A_DIM
                    else:
                        ch   = tiles[my][mx]
                        attr = curses.color_pair(COLOR_DARK) | curses.A_DIM
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
    draw_panel(stdscr, player, panel_col, view_h, current_floor,
               max_floor=max_floor, floor_name=theme['name'])

    # --- Message log ---
    HINT = " WASD/Arrows:move  F:fire  T:trade  >/< stairs  B:back  I:equip  K:skills  H:hack  E:disarm  U:use  X:tool  R:reset  Q:quit"
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
            barter_discount = player.skills.get('barter', 0) * 0.05
            price = int(base_price * max(0.4, 1.0 - (player.presence - 5) * 0.05 - barter_discount))
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
                    barter_discount = player.skills.get('barter', 0) * 0.05
                    price = int(base_price * max(0.4, 1.0 - (player.presence - 5) * 0.05 - barter_discount))
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
                   enemies_on_map, log, terminals_on_map=None, hazards_on_map=None,
                   smoke_tiles=None):
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
             terminals=terminals_on_map, target_line=line_tiles, target_pos=target_pos,
             hazards=hazards_on_map, smoke_tiles=smoke_tiles)

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
        """Apply race + class mods to STAT_BASE, clamped to STAT_MIN.
        Also returns background skill allocations from the class."""
        rmods = RACES[race_name]['mods']
        cmods = CLASSES[class_name]['mods']
        result = {}
        for s in STATS:
            val = STAT_BASE + rmods.get(s, 0) + cmods.get(s, 0)
            result[s] = max(STAT_MIN, val)
        bg_skills = dict(CLASSES[class_name].get('skills', {}))
        return result, bg_skills

    def mod_str(mods):
        parts = []
        for s, label in zip(STATS, STAT_LABELS):
            v = mods.get(s, 0)
            if v != 0:
                parts.append(f"{label[0]}{v:+d}")
        return '  '.join(parts) if parts else '(no modifiers)'

    step        = 0
    name        = ''
    race_idx    = 0
    class_idx   = 0
    alloc       = {s: 0 for s in STATS}
    stat_cursor  = 0   # index into STATS for point-buy step
    skill_alloc  = {k: 0 for k in SKILL_ORDER}   # extra free points beyond background
    skill_cursor = 0   # index into SKILL_ORDER for skill allocation step

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

        # ── Step 2: Background ───────────────────────────────────────────────
        elif step == 2:
            title = "CHARACTER CREATION — Background"
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
                alloc       = {s: 0 for s in STATS}      # reset alloc on class change
                skill_alloc = {k: 0 for k in SKILL_ORDER}  # reset skill alloc
                step = 3

        # ── Step 3: Point Buy ─────────────────────────────────────────────────
        elif step == 3:
            rname      = race_names[race_idx]
            cname      = class_names[class_idx]
            base, _bg  = compute_base(rname, cname)
            remain     = POINT_BUY_POINTS - sum(alloc.values())

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
                skill_alloc = {k: 0 for k in SKILL_ORDER}   # reset skill alloc entering step 4
                step = 4

        # ── Step 4: Skill Allocation ──────────────────────────────────────────
        elif step == 4:
            rname      = race_names[race_idx]
            cname      = class_names[class_idx]
            _base, bg_skills = compute_base(rname, cname)
            remaining_sp = STARTING_SKILL_POINTS - sum(skill_alloc.values())

            title = "CHARACTER CREATION — Allocate Skills"
            safe_addstr(1, 2, title, header_attr)
            safe_addstr(3, 2,
                f"Free points: {remaining_sp}   "
                "W/S: select   D: add   A: remove (free only)   Enter: continue   Esc: back",
                panel_attr)

            # Group skills by category for display
            cur_cat = None
            row = 5
            for i, sk in enumerate(SKILL_ORDER):
                sdata = SKILLS[sk]
                cat   = sdata['cat']
                if cat != cur_cat:
                    safe_addstr(row, 2, cat.upper(), panel_attr | curses.A_BOLD)
                    row += 1
                    cur_cat = cat
                bg_lv    = bg_skills.get(sk, 0)
                extra_lv = skill_alloc.get(sk, 0)
                total_lv = bg_lv + extra_lv
                bar      = '█' * total_lv + '░' * (SKILL_MAX - total_lv)
                attr     = sel_attr if i == skill_cursor else panel_attr
                prefix   = '> ' if i == skill_cursor else '  '
                line = f"{prefix}{sdata['name']:<14} {bar}  {total_lv}/{SKILL_MAX}  {sdata['effect']}"
                safe_addstr(row, 2, line[:term_w - 4], attr)
                if bg_lv > 0:
                    safe_addstr(row, 2 + len(prefix) + 14 + 1 + bg_lv - 1, '',  # just mark bg portion
                                panel_attr)  # background skills already filled by char
                row += 1

            stdscr.refresh()
            key = stdscr.getch()

            if key == 27:
                step = 3
            elif key in (curses.KEY_UP, ord('w'), ord('W')):
                skill_cursor = (skill_cursor - 1) % len(SKILL_ORDER)
            elif key in (curses.KEY_DOWN, ord('s'), ord('S')):
                skill_cursor = (skill_cursor + 1) % len(SKILL_ORDER)
            elif key in (curses.KEY_RIGHT, ord('d'), ord('D')):
                sk       = SKILL_ORDER[skill_cursor]
                bg_lv    = bg_skills.get(sk, 0)
                total_lv = bg_lv + skill_alloc.get(sk, 0)
                if remaining_sp > 0 and total_lv < SKILL_MAX:
                    skill_alloc[sk] = skill_alloc.get(sk, 0) + 1
            elif key in (curses.KEY_LEFT, ord('a'), ord('A')):
                sk = SKILL_ORDER[skill_cursor]
                if skill_alloc.get(sk, 0) > 0:
                    skill_alloc[sk] -= 1
            elif key in (curses.KEY_ENTER, 10, 13):
                step = 5

        # ── Step 5: Confirm ────────────────────────────────────────────────────
        elif step == 5:
            rname      = race_names[race_idx]
            cname      = class_names[class_idx]
            base, bg_skills = compute_base(rname, cname)
            final  = {s: base[s] + alloc[s] for s in STATS}
            max_hp = 20 + final['body'] * 2
            # Build final skills: background + free allocations
            final_skills = {k: 0 for k in SKILL_ORDER}
            for k, v in bg_skills.items():
                final_skills[k] = final_skills.get(k, 0) + v
            for k, v in skill_alloc.items():
                final_skills[k] = final_skills.get(k, 0) + v

            title = "CHARACTER CREATION — Confirm"
            safe_addstr(1, 2, title, header_attr)
            safe_addstr(3, 2, f"Name:       {name}", panel_attr)
            safe_addstr(4, 2, f"Race:       {rname}", panel_attr)
            safe_addstr(5, 2, f"Background: {cname}", panel_attr)
            safe_addstr(7, 2, "STATS", header_attr)

            for i, (s, label) in enumerate(zip(STATS, STAT_LABELS)):
                safe_addstr(8 + i, 4, f"{label:<10} {final[s]:>2}", panel_attr)

            safe_addstr(8 + len(STATS) + 1, 2, f"Max HP: {max_hp}", panel_attr)

            # Show non-zero skills
            nz_skills = [(k, v) for k, v in final_skills.items() if v > 0]
            if nz_skills:
                safe_addstr(8 + len(STATS) + 3, 2, "SKILLS", header_attr)
                for si, (sk, lv) in enumerate(nz_skills):
                    safe_addstr(8 + len(STATS) + 4 + si, 4,
                                f"{SKILLS[sk]['name']:<14} {lv}", panel_attr)
                conf_row = 8 + len(STATS) + 5 + len(nz_skills)
            else:
                conf_row = 8 + len(STATS) + 3

            safe_addstr(conf_row, 2, "Enter: begin game   Esc: back", panel_attr)

            stdscr.refresh()
            key = stdscr.getch()

            if key == 27:
                step = 4
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
                    skills=final_skills,
                )


def apply_effect(entity, effect, turns):
    """Apply or refresh a status effect (keeps max remaining turns).
    Player's Survival skill reduces duration by 1 per skill level (min 1)."""
    if hasattr(entity, 'skills'):
        turns = max(1, turns - entity.skills.get('survival', 0))
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
        elif effect == 'repair':
            if hasattr(entity, 'max_hp') and entity.hp < entity.max_hp:
                heal = min(5, entity.max_hp - entity.hp)
                entity.hp += heal
                msgs.append(f"Repair Drone: +{heal} HP.")
        entity.active_effects[effect] = turns - 1
        if turns - 1 <= 0:
            expired.append(effect)
    for e in expired:
        del entity.active_effects[e]
        if e == 'stim':
            apply_effect(entity, 'stun', 1)
            msgs.append(f"{label}: stimpack crash — stunned!")
        elif e == 'repair':
            pass   # no expiry message for repair drone
        else:
            msgs.append(f"{label} is no longer affected by {e}.")
    return msgs


def show_skill_levelup_modal(stdscr, player, points=2):
    """Modal for spending skill points after levelling up.
    points: how many the player may spend now; any unspent are banked to player.skill_points."""
    BOX_W      = 56
    panel_attr = curses.color_pair(COLOR_PANEL)
    hi_attr    = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD
    head_attr  = panel_attr | curses.A_BOLD

    remaining  = points
    allocated  = {k: 0 for k in SKILL_ORDER}   # points spent THIS modal (removable)
    cursor     = 0

    while True:
        term_h, term_w = stdscr.getmaxyx()
        # BOX_H: title row + blank + 12 skill rows + blank + footer + borders = 18
        BOX_H  = 3 + len(SKILL_ORDER) + 3
        box_y  = max(0, (term_h - BOX_H) // 2)
        box_x  = max(0, (term_w - BOX_W) // 2)

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

        # Title
        title = f"  SKILL POINTS — {remaining} to spend  "
        try:
            stdscr.addstr(box_y + 1, box_x + 1, title[:BOX_W - 2].center(BOX_W - 2), head_attr)
        except curses.error:
            pass

        # Skill rows
        for i, sk in enumerate(SKILL_ORDER):
            row      = box_y + 3 + i
            sdata    = SKILLS[sk]
            cur_lv   = player.skills.get(sk, 0) + allocated.get(sk, 0)
            bar      = '█' * cur_lv + '░' * (SKILL_MAX - cur_lv)
            prefix   = '>' if i == cursor else ' '
            attr     = hi_attr if i == cursor else panel_attr
            line     = f" {prefix} {sdata['name']:<14} {bar}  {cur_lv}/{SKILL_MAX}  {sdata['effect']}"
            try:
                stdscr.addstr(row, box_x + 1, line[:BOX_W - 2].ljust(BOX_W - 2), attr)
            except curses.error:
                pass

        # Footer
        footer = "  W/S:select  D:add  A:remove  Enter:done  "
        try:
            stdscr.addstr(box_y + BOX_H - 2, box_x + 1, footer[:BOX_W - 2].center(BOX_W - 2),
                          panel_attr)
        except curses.error:
            pass

        stdscr.refresh()
        key = stdscr.getch()

        if key in (ord('w'), ord('W'), curses.KEY_UP):
            cursor = (cursor - 1) % len(SKILL_ORDER)
        elif key in (ord('s'), ord('S'), curses.KEY_DOWN):
            cursor = (cursor + 1) % len(SKILL_ORDER)
        elif key in (ord('d'), ord('D'), curses.KEY_RIGHT):
            sk     = SKILL_ORDER[cursor]
            cur_lv = player.skills.get(sk, 0) + allocated.get(sk, 0)
            if remaining > 0 and cur_lv < SKILL_MAX:
                allocated[sk] = allocated.get(sk, 0) + 1
                remaining    -= 1
        elif key in (ord('a'), ord('A'), curses.KEY_LEFT):
            sk = SKILL_ORDER[cursor]
            if allocated.get(sk, 0) > 0:
                allocated[sk] -= 1
                remaining     += 1
        elif key in (ord('\n'), curses.KEY_ENTER, 10, 13, 27):
            # Apply allocations
            for sk, lv in allocated.items():
                player.skills[sk] = player.skills.get(sk, 0) + lv
            # Bank unspent points
            player.skill_points += remaining
            break


def show_skills_screen(stdscr, player):
    """Read-only skills overview; allows spending banked skill_points if any."""
    BOX_W      = 58
    panel_attr = curses.color_pair(COLOR_PANEL)
    hi_attr    = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD
    head_attr  = panel_attr | curses.A_BOLD

    cursor  = 0
    can_spend = player.skill_points > 0

    while True:
        term_h, term_w = stdscr.getmaxyx()

        # Count rows needed: category headers + skill rows
        rows_content = []   # (text, attr, skill_key_or_None)
        cur_cat = None
        for sk in SKILL_ORDER:
            sdata = SKILLS[sk]
            cat   = sdata['cat']
            if cat != cur_cat:
                rows_content.append((cat.upper(), head_attr, None))
                cur_cat = cat
            lv   = player.skills.get(sk, 0)
            bar  = '█' * lv + '░' * (SKILL_MAX - lv)
            eff  = sdata['effect'] if lv > 0 else '—'
            line = f"  {sdata['name']:<14} {bar}  {lv}/{SKILL_MAX}   {eff}"
            attr = hi_attr if (can_spend and SKILL_ORDER.index(sk) == cursor) else panel_attr
            rows_content.append((line, attr, sk))

        BOX_H  = len(rows_content) + 4   # title + content + blank + footer + borders
        box_y  = max(0, (term_h - BOX_H) // 2)
        box_x  = max(0, (term_w - BOX_W) // 2)

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

        # Title with SP count
        sp_str = f"[SP: {player.skill_points} unspent]" if player.skill_points else ""
        title  = f"  SKILLS  {sp_str}"
        try:
            stdscr.addstr(box_y + 1, box_x + 1, title[:BOX_W - 2].ljust(BOX_W - 2), head_attr)
        except curses.error:
            pass

        # Content rows
        for ri, (text, attr, sk) in enumerate(rows_content):
            row = box_y + 2 + ri
            try:
                stdscr.addstr(row, box_x + 1, ' ' * (BOX_W - 2))
                stdscr.addstr(row, box_x + 1, text[:BOX_W - 2], attr)
            except curses.error:
                pass

        # Footer
        if can_spend:
            footer = "  W/S:select  D:spend point  K/Esc:close  "
        else:
            footer = "  K/Esc:close  "
        try:
            stdscr.addstr(box_y + BOX_H - 2, box_x + 1, footer[:BOX_W - 2].center(BOX_W - 2),
                          panel_attr | curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()
        key = stdscr.getch()

        if key in (27, ord('k'), ord('K')):
            break
        if can_spend:
            if key in (ord('w'), ord('W'), curses.KEY_UP):
                # Navigate only to skill rows
                sk_indices = [i for i, (_, _, s) in enumerate(rows_content) if s is not None]
                cur_sk_pos = next((p for p, idx in enumerate(sk_indices)
                                   if SKILL_ORDER.index(rows_content[idx][2]) == cursor), 0)
                if cur_sk_pos > 0:
                    cursor = SKILL_ORDER.index(rows_content[sk_indices[cur_sk_pos - 1]][2])
            elif key in (ord('s'), ord('S'), curses.KEY_DOWN):
                sk_indices = [i for i, (_, _, s) in enumerate(rows_content) if s is not None]
                cur_sk_pos = next((p for p, idx in enumerate(sk_indices)
                                   if SKILL_ORDER.index(rows_content[idx][2]) == cursor), 0)
                if cur_sk_pos < len(sk_indices) - 1:
                    cursor = SKILL_ORDER.index(rows_content[sk_indices[cur_sk_pos + 1]][2])
            elif key in (ord('d'), ord('D')):
                sk    = SKILL_ORDER[cursor]
                cur_lv = player.skills.get(sk, 0)
                if player.skill_points > 0 and cur_lv < SKILL_MAX:
                    player.skills[sk]  = cur_lv + 1
                    player.skill_points -= 1
                    can_spend = player.skill_points > 0


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


def enemy_turn(enemies, tiles, px, py, visible, player,
               smoke_tiles=None, hazards_on_map=None):
    """Move and attack with every enemy. Returns list of combat message strings."""
    msgs       = []
    player_pos = (px, py)
    # Track occupied positions so enemies don't pile onto the same tile this turn.
    # Updated as enemies move so later enemies see the current layout.
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
            _check_mine(enemy)
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
            _check_mine(enemy)
            continue

        # ── Brute ────────────────────────────────────────────────────────────
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

        # ── Exploder / Melee (default) ───────────────────────────────────────
        if epos in visible:
            _astar_step(enemy, epos)
        else:
            _random_walk(enemy, epos)
        _check_mine(enemy)

    return msgs


def show_game_over(stdscr, player, site_name):
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
            (f"Last site: {site_name}",              panel_attr),
            (f"Level:     {player.level}",           panel_attr),
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


def show_hacking_interface(stdscr, player, terminal, current_floor, explored,
                           enemies_on_map, items_on_map, special_rooms,
                           tiles, px, py, visible, log, terminals_on_map,
                           current_theme):
    """Hacking terminal interface. Returns True if a turn was consumed."""
    hack_lv = player.skills.get('hacking', 0)
    BOX_W   = 62
    inner_w = BOX_W - 4

    ACTIONS = [
        (0, "Read log",         "always available"),
        (1, "Map fragment",     "Hacking 1"),
        (2, "Disable units",    "Hacking 2"),
        (3, "Unlock vault",     "Hacking 3"),
        (4, "Alert protocol",   "Hacking 4"),
        (5, "Remote access",    "Hacking 5"),
    ]

    # Success rate for levels 1-5
    def _success_rate():
        return max(15, min(90, 60 + (player.tech - 5) * 8 - current_floor * 3))

    def _draw_box(sel):
        term_h, term_w = stdscr.getmaxyx()
        box_h = 2 + 3 + len(ACTIONS) + 2   # borders + header rows + actions + footer row + dividers
        box_y = max(0, (term_h - box_h) // 2)
        box_x = max(0, (term_w - BOX_W) // 2)

        term_attr  = curses.color_pair(COLOR_TERMINAL) | curses.A_BOLD
        panel_attr = curses.color_pair(COLOR_PANEL)
        dark_attr  = curses.color_pair(COLOR_DARK) | curses.A_DIM
        sel_attr   = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD

        def hline(row):
            try:
                stdscr.addch(row, box_x, curses.ACS_LTEE, term_attr)
                for bx in range(1, BOX_W - 1):
                    stdscr.addch(row, box_x + bx, curses.ACS_HLINE, term_attr)
                stdscr.addch(row, box_x + BOX_W - 1, curses.ACS_RTEE, term_attr)
            except curses.error:
                pass

        def border_row(row):
            try:
                stdscr.addch(row, box_x, curses.ACS_VLINE, term_attr)
                stdscr.addch(row, box_x + BOX_W - 1, curses.ACS_VLINE, term_attr)
                stdscr.addstr(row, box_x + 1, ' ' * (BOX_W - 2))
            except curses.error:
                pass

        # Top border
        try:
            title_str = " TERMINAL ACCESS "
            pad = BOX_W - 2 - len(title_str)
            left = pad // 2
            right = pad - left
            stdscr.addch(box_y, box_x, curses.ACS_ULCORNER, term_attr)
            for bx in range(1, left + 1):
                stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, term_attr)
            stdscr.addstr(box_y, box_x + left + 1, title_str, term_attr)
            for bx in range(left + 1 + len(title_str), BOX_W - 1):
                stdscr.addch(box_y, box_x + bx, curses.ACS_HLINE, term_attr)
            stdscr.addch(box_y, box_x + BOX_W - 1, curses.ACS_URCORNER, term_attr)
        except curses.error:
            pass

        # Terminal title row
        row = box_y + 1
        border_row(row)
        tname = terminal.title[:inner_w + 2]
        try:
            stdscr.addstr(row, box_x + 2, tname, term_attr)
        except curses.error:
            pass

        # Info row
        row = box_y + 2
        border_row(row)
        info = f"  Tech: {player.tech}   Hacking: {hack_lv}   Floor: {current_floor}"
        try:
            stdscr.addstr(row, box_x + 2, info[:inner_w + 2], panel_attr)
        except curses.error:
            pass

        hline(box_y + 3)

        # Action rows
        sr = _success_rate()
        for i, (req_lv, name, hint) in enumerate(ACTIONS):
            row = box_y + 4 + i
            border_row(row)
            locked   = (req_lv > hack_lv)
            selected = (i == sel) and not locked
            if locked:
                prefix = "---"
                rate_s = "[locked]"
                attr   = dark_attr
            elif req_lv == 0:
                prefix = "  >"  if selected else "   "
                rate_s = hint
                attr   = sel_attr if selected else panel_attr
            else:
                prefix = "  >" if selected else "   "
                rate_s = f"[{sr}% success]"
                attr   = sel_attr if selected else panel_attr

            line = f"{prefix} [{req_lv}] {name:<18} {hint:<14} {rate_s}"
            try:
                stdscr.addstr(row, box_x + 2, line[:inner_w + 2], attr)
            except curses.error:
                pass

        hline(box_y + 4 + len(ACTIONS))

        # Footer row
        row = box_y + 4 + len(ACTIONS) + 1
        border_row(row)
        footer = "W/S: select   Enter: execute   Esc: cancel"
        try:
            stdscr.addstr(row, box_x + 2, footer[:inner_w + 2], panel_attr)
        except curses.error:
            pass

        # Bottom border
        bot = box_y + 4 + len(ACTIONS) + 2
        try:
            stdscr.addch(bot, box_x, curses.ACS_LLCORNER, term_attr)
            for bx in range(1, BOX_W - 1):
                stdscr.addch(bot, box_x + bx, curses.ACS_HLINE, term_attr)
            stdscr.addch(bot, box_x + BOX_W - 1, curses.ACS_LRCORNER, term_attr)
        except curses.error:
            pass

        stdscr.refresh()

    def _fail_spawn():
        scale = 1 + (current_floor - 1) * 0.2
        floors_avail = [(x, y) for y in range(MAP_H) for x in range(MAP_W)
                        if tiles[y][x] == FLOOR
                        and (x, y) not in enemies_on_map and (x, y) != (px, py)]
        if floors_avail:
            for pos in random.sample(floors_avail, min(2, len(floors_avail))):
                t = random.choices(ENEMY_TEMPLATES, weights=current_theme['weights'])[0]
                enemies_on_map[pos] = Enemy(
                    name=t['name'], char=t['char'],
                    hp=max(1, int(t['hp'] * scale)), atk=max(1, int(t['atk'] * scale)),
                    dfn=int(t['dfn'] * scale), xp_reward=int(t['xp'] * scale),
                    behaviour=t.get('behaviour', 'melee'))
        log.appendleft("HACK FAILED — security alert triggered!")

    # Find the initially selected row (first unlocked)
    sel = 0

    while True:
        _draw_box(sel)
        key = stdscr.getch()

        if key == 27:           # Esc
            return False
        if key in (ord('w'), curses.KEY_UP):
            for step in range(1, len(ACTIONS)):
                nsel = (sel - step) % len(ACTIONS)
                if ACTIONS[nsel][0] <= hack_lv:
                    sel = nsel
                    break
        elif key in (ord('s'), curses.KEY_DOWN):
            for step in range(1, len(ACTIONS)):
                nsel = (sel + step) % len(ACTIONS)
                if ACTIONS[nsel][0] <= hack_lv:
                    sel = nsel
                    break
        elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
            req_lv = ACTIONS[sel][0]
            if req_lv > hack_lv:
                continue   # locked row, ignore

            # ── Level 0: Read log ─────────────────────────────────────────────
            if req_lv == 0:
                show_terminal(stdscr, terminal)
                tech_xp = max(0, (player.tech - 5) * 5)
                if tech_xp:
                    n_lv, lvl_msg = player.gain_xp(tech_xp)
                    log.appendleft(f"Tech interface: +{tech_xp} XP")
                    if lvl_msg:
                        log.appendleft(lvl_msg)
                return False   # no turn consumed

            # ── Levels 1-5: roll success ──────────────────────────────────────
            sr = _success_rate()
            success = random.randint(1, 100) <= sr

            if not success:
                _fail_spawn()
                return True   # turn consumed

            # ── Level 1: Map fragment ──────────────────────────────────────────
            if req_lv == 1:
                for dy in range(-15, 16):
                    for dx in range(-15, 16):
                        tx2, ty2 = px + dx, py + dy
                        if 0 <= tx2 < MAP_W and 0 <= ty2 < MAP_H and tiles[ty2][tx2] == FLOOR:
                            explored.add((tx2, ty2))
                log.appendleft("Map fragment downloaded.")
                return True

            # ── Level 2: Disable units ────────────────────────────────────────
            if req_lv == 2:
                count = 0
                for pos, e in enemies_on_map.items():
                    if pos in visible and e.name in ('Sentry', 'Drone'):
                        apply_effect(e, 'stun', 3)
                        count += 1
                log.appendleft(f"Disabled {count} unit(s) in sensor range.")
                return True

            # ── Level 3: Unlock vault ─────────────────────────────────────────
            if req_lv == 3:
                vault = next((sr2 for sr2 in special_rooms.values()
                              if sr2['type'] == 'vault' and not sr2['triggered']), None)
                if vault:
                    vault['triggered'] = True
                    rare = [it for it in ITEM_TEMPLATES if it.atk >= 3 or it.dfn >= 3]
                    if rare:
                        avail = list(vault['tiles'])
                        for pos in random.sample(avail, min(4, len(avail))):
                            items_on_map[pos] = copy.copy(random.choice(rare))
                    log.appendleft("Vault override successful. Rare gear inside.")
                else:
                    log.appendleft("No vault found on this floor.")
                return True

            # ── Level 4: Alert protocol ───────────────────────────────────────
            if req_lv == 4:
                scale = 1 + (current_floor - 1) * 0.2
                candidates = sorted(
                    [(x, y) for y in range(MAP_H) for x in range(MAP_W)
                     if tiles[y][x] == FLOOR
                     and (x, y) not in enemies_on_map and (x, y) != (px, py)],
                    key=lambda pos: abs(pos[0] - px) + abs(pos[1] - py)
                )
                for pos in candidates[:3]:
                    t = random.choices(ENEMY_TEMPLATES, weights=current_theme['weights'])[0]
                    enemies_on_map[pos] = Enemy(
                        name=t['name'], char=t['char'],
                        hp=max(1, int(t['hp'] * scale)), atk=max(1, int(t['atk'] * scale)),
                        dfn=int(t['dfn'] * scale), xp_reward=int(t['xp'] * scale),
                        behaviour=t.get('behaviour', 'melee'))
                rare = [it for it in ITEM_TEMPLATES if it.atk >= 3 or it.dfn >= 3]
                if rare:
                    items_on_map[(px, py)] = copy.copy(random.choice(rare))
                log.appendleft("ALERT PROTOCOL — reinforcements converging. Rare cache unlocked.")
                return True

            # ── Level 5: Remote access ────────────────────────────────────────
            if req_lv == 5:
                others = [(pos, t2) for pos, t2 in terminals_on_map.items()
                          if not t2.read and pos != (px, py)]
                if not others:
                    log.appendleft("No unread terminals on this floor.")
                    return False
                # Show remote picker sub-menu
                rpick = 0
                while True:
                    term_h, term_w = stdscr.getmaxyx()
                    pbox_h = 2 + 2 + len(others) + 1
                    pbox_y = max(0, (term_h - pbox_h) // 2)
                    pbox_x = max(0, (term_w - BOX_W) // 2)
                    term_attr  = curses.color_pair(COLOR_TERMINAL) | curses.A_BOLD
                    panel_attr = curses.color_pair(COLOR_PANEL)
                    sel_attr   = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD

                    def _prow(row):
                        try:
                            stdscr.addch(row, pbox_x, curses.ACS_VLINE, term_attr)
                            stdscr.addch(row, pbox_x + BOX_W - 1, curses.ACS_VLINE, term_attr)
                            stdscr.addstr(row, pbox_x + 1, ' ' * (BOX_W - 2))
                        except curses.error:
                            pass

                    try:
                        rtitle = " REMOTE ACCESS — Select Terminal "
                        rpad   = BOX_W - 2 - len(rtitle)
                        rleft  = rpad // 2
                        stdscr.addch(pbox_y, pbox_x, curses.ACS_ULCORNER, term_attr)
                        for bx in range(1, rleft + 1):
                            stdscr.addch(pbox_y, pbox_x + bx, curses.ACS_HLINE, term_attr)
                        stdscr.addstr(pbox_y, pbox_x + rleft + 1, rtitle, term_attr)
                        for bx in range(rleft + 1 + len(rtitle), BOX_W - 1):
                            stdscr.addch(pbox_y, pbox_x + bx, curses.ACS_HLINE, term_attr)
                        stdscr.addch(pbox_y, pbox_x + BOX_W - 1, curses.ACS_URCORNER, term_attr)
                    except curses.error:
                        pass

                    _prow(pbox_y + 1)
                    try:
                        stdscr.addstr(pbox_y + 1, pbox_x + 2,
                                      "W/S: select   Enter: read   Esc: cancel"[:inner_w + 2],
                                      panel_attr)
                    except curses.error:
                        pass

                    try:
                        stdscr.addch(pbox_y + 2, pbox_x, curses.ACS_LTEE, term_attr)
                        for bx in range(1, BOX_W - 1):
                            stdscr.addch(pbox_y + 2, pbox_x + bx, curses.ACS_HLINE, term_attr)
                        stdscr.addch(pbox_y + 2, pbox_x + BOX_W - 1, curses.ACS_RTEE, term_attr)
                    except curses.error:
                        pass

                    for oi, (opos, ot) in enumerate(others):
                        orow = pbox_y + 3 + oi
                        _prow(orow)
                        prefix = "  >" if oi == rpick else "   "
                        label  = f"{prefix} {ot.title[:inner_w - 1]}"
                        attr   = sel_attr if oi == rpick else panel_attr
                        try:
                            stdscr.addstr(orow, pbox_x + 2, label[:inner_w + 2], attr)
                        except curses.error:
                            pass

                    pbot = pbox_y + 3 + len(others)
                    try:
                        stdscr.addch(pbot, pbox_x, curses.ACS_LLCORNER, term_attr)
                        for bx in range(1, BOX_W - 1):
                            stdscr.addch(pbot, pbox_x + bx, curses.ACS_HLINE, term_attr)
                        stdscr.addch(pbot, pbox_x + BOX_W - 1, curses.ACS_LRCORNER, term_attr)
                    except curses.error:
                        pass

                    stdscr.refresh()
                    pk = stdscr.getch()

                    if pk == 27:
                        return False
                    if pk in (ord('w'), curses.KEY_UP):
                        rpick = (rpick - 1) % len(others)
                    elif pk in (ord('s'), curses.KEY_DOWN):
                        rpick = (rpick + 1) % len(others)
                    elif pk in (curses.KEY_ENTER, ord('\n'), ord('\r')):
                        chosen_t = others[rpick][1]
                        tech_xp  = max(0, (player.tech - 5) * 5)
                        show_terminal(stdscr, chosen_t)
                        if tech_xp:
                            n_lv, lvl_msg = player.gain_xp(tech_xp)
                            log.appendleft(f"Tech interface: +{tech_xp} XP")
                            if lvl_msg:
                                log.appendleft(lvl_msg)
                        log.appendleft("Remote access successful.")
                        return True


def run_site(stdscr, site, player):
    """Run the dungeon game loop for a site.
    Returns 'escaped' (left via B), 'dead', or 'restart' (R pressed)."""
    current_floor = 1

    smoke_tiles = {}   # {(x,y): turns_remaining} — player-deployed smoke

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

    log     = collections.deque(maxlen=LOG_LINES)
    visible = compute_fov(tiles, px, py, player.fov_radius)
    explored |= visible

    theme_fn = site.theme_fn or get_theme
    current_theme = theme_fn(current_floor)

    draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
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
            result = show_equipment_screen(stdscr, player, px, py, items_on_map)
            if result:
                log.appendleft(result)

        if key in (ord('k'), ord('K')):
            show_skills_screen(stdscr, player)

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
                    consumed = show_hacking_interface(
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
                                consumed2 = show_hacking_interface(
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

        # ── X key: activate equipped tool ────────────────────────────────────
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
                        draw(stdscr, tiles, px, py, player, visible, explored,
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
                e_msgs = enemy_turn(enemies_on_map, tiles, px, py, visible, player,
                                    smoke_tiles=smoke_tiles, hazards_on_map=hazards_on_map)
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
                        enemies_on_map, log, terminals_on_map, hazards_on_map,
                        smoke_tiles=smoke_tiles)
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
                                    show_skill_levelup_modal(stdscr, player, points=2)
                                if enemy.boss:
                                    draw(stdscr, tiles, px, py, player, visible, explored,
                                         items_on_map, stair_up, stair_down, current_floor,
                                         enemies_on_map, log, terminals=terminals_on_map,
                                         special_rooms=special_rooms, max_floor=site.depth,
                                         theme_override=current_theme, hazards=hazards_on_map,
                                         smoke_tiles=smoke_tiles)
                                    show_terminal(stdscr, WIN_TERMINAL)
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
                                show_levelup_modal(stdscr, player)
                                show_skill_levelup_modal(stdscr, player, points=2)
                            if en2.boss:
                                draw(stdscr, tiles, px, py, player, visible, explored,
                                     items_on_map, stair_up, stair_down, current_floor,
                                     enemies_on_map, log, terminals=terminals_on_map,
                                     special_rooms=special_rooms, max_floor=site.depth,
                                     theme_override=current_theme, hazards=hazards_on_map,
                                     smoke_tiles=smoke_tiles)
                                show_terminal(stdscr, WIN_TERMINAL)
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
                            show_levelup_modal(stdscr, player)
                            show_skill_levelup_modal(stdscr, player, points=2)
                        if (px, py) in items_on_map:
                            picked2 = items_on_map[(px, py)]
                            if player.pickup(picked2):
                                items_on_map.pop((px, py))
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
                                        if show_vault_prompt(stdscr, cost, player.credits):
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

                # Stim: bonus move on same floor
                if 'stim' in player.active_effects and move_result != 'stairs':
                    v_stim = compute_fov(tiles, px, py, player.fov_radius)
                    explored |= v_stim
                    draw(stdscr, tiles, px, py, player, v_stim, explored,
                         items_on_map, stair_up, stair_down, current_floor,
                         enemies_on_map, log, terminals=terminals_on_map,
                         special_rooms=special_rooms, max_floor=site.depth,
                         theme_override=current_theme, hazards=hazards_on_map,
                         smoke_tiles=smoke_tiles)
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

        if player.hp <= 0:
            player.hp = 0
            draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
                 stair_up, stair_down, current_floor, enemies_on_map, log,
                 terminals=terminals_on_map, special_rooms=special_rooms,
                 max_floor=site.depth, theme_override=current_theme,
                 hazards=hazards_on_map, smoke_tiles=smoke_tiles)
            return 'dead'

        draw(stdscr, tiles, px, py, player, visible, explored, items_on_map,
             stair_up, stair_down, current_floor, enemies_on_map, log,
             terminals=terminals_on_map, special_rooms=special_rooms,
             max_floor=site.depth, theme_override=current_theme,
             hazards=hazards_on_map, smoke_tiles=smoke_tiles)


def show_ship_screen(stdscr, player, sites):
    """Hub screen showing ship status. Returns 'nav', 'restart', or 'quit'."""
    panel_attr  = curses.color_pair(COLOR_PANEL)
    header_attr = panel_attr | curses.A_BOLD

    while True:
        term_h, term_w = stdscr.getmaxyx()
        stdscr.erase()

        lines = [
            ("THE MERIDIAN",                                    header_attr),
            ("",                                                0),
            (f"  Pilot: {player.name}",                        panel_attr),
            (f"  {player.race} {player.char_class}  Lvl {player.level}", panel_attr),
            ("",                                                0),
            (f"  HP:    {player.hp} / {player.max_hp}",        panel_attr),
            (f"  CR:    {player.credits}",                      panel_attr),
            (f"  Fuel:  {player.fuel}",                         panel_attr),
            ("",                                                0),
            ("  Sites:",                                        header_attr),
        ]

        for site in sites:
            status = "[cleared]" if site.cleared else "[available]"
            lines.append((f"  [{site.char}] {site.name:<22} {status}", panel_attr))

        lines += [
            ("",                                                0),
            ("  [N] Navigation Computer",                      panel_attr),
            ("  [R] New run   [Q] Quit",                       panel_attr),
        ]

        start_row = max(0, (term_h - len(lines)) // 2)
        col_off   = max(0, (term_w - 44) // 2)
        for i, (text, attr) in enumerate(lines):
            try:
                stdscr.addstr(start_row + i, col_off, text[:term_w - col_off - 1], attr)
            except curses.error:
                pass

        stdscr.refresh()
        key = stdscr.getch()

        if key in (ord('n'), ord('N')):
            return 'nav'
        if key in (ord('r'), ord('R')):
            return 'restart'
        if key in (ord('q'), ord('Q')):
            return 'quit'


def show_nav_computer(stdscr, player, sites):
    """Site selection menu. W/S navigate, Enter travel, Esc back.
    Returns selected Site or None."""
    panel_attr  = curses.color_pair(COLOR_PANEL)
    header_attr = panel_attr | curses.A_BOLD
    dim_attr    = panel_attr | curses.A_DIM
    sel_attr    = curses.color_pair(COLOR_PLAYER) | curses.A_BOLD
    err_attr    = curses.color_pair(COLOR_HP_LOW)

    cur = 0
    msg = ""

    while True:
        term_h, term_w = stdscr.getmaxyx()
        stdscr.erase()

        title    = "NAV COMPUTER — Choose destination"
        nav_hint = "W/S: navigate   Enter: travel   Esc: back"
        try:
            stdscr.addstr(1, max(0, (term_w - len(title)) // 2), title, header_attr)
            stdscr.addstr(2, max(0, (term_w - len(nav_hint)) // 2), nav_hint, dim_attr)
        except curses.error:
            pass

        start_col = max(0, (term_w - 62) // 2)
        for i, site in enumerate(sites):
            row        = 4 + i * 2
            can_afford = player.fuel >= site.fuel_cost
            if site.cleared:
                status = "[cleared]"
            elif not can_afford:
                need   = site.fuel_cost - player.fuel
                status = f"[need {need} more fuel]"
            else:
                status = "[available]"
            cost_str = f"cost: {site.fuel_cost}"
            text = f"[{site.char}] {site.name:<22} {cost_str:<10} {status}"
            prefix = "> " if i == cur else "  "
            attr   = sel_attr if i == cur else (dim_attr if not can_afford else panel_attr)
            try:
                stdscr.addstr(row, start_col, (prefix + text)[:term_w - start_col - 1], attr)
                if site.desc:
                    stdscr.addstr(row + 1, start_col + 4,
                                  site.desc[:term_w - start_col - 5], dim_attr)
            except curses.error:
                pass

        if msg:
            msg_row = 4 + len(sites) * 2 + 1
            try:
                stdscr.addstr(msg_row, start_col, msg[:term_w - start_col - 1], err_attr)
            except curses.error:
                pass

        stdscr.refresh()
        key = stdscr.getch()

        if key == 27:
            return None
        if key in (curses.KEY_UP, ord('w'), ord('W')):
            cur = max(0, cur - 1)
            msg = ""
        elif key in (curses.KEY_DOWN, ord('s'), ord('S')):
            cur = min(len(sites) - 1, cur + 1)
            msg = ""
        elif key in (curses.KEY_ENTER, 10, 13):
            site = sites[cur]
            if player.fuel < site.fuel_cost:
                msg = f"Not enough fuel. Need {site.fuel_cost}, have {player.fuel}."
            else:
                return site


def main(stdscr):
    curses.curs_set(0)
    stdscr.keypad(True)
    setup_colors()

    while True:   # outer loop: new run on restart
        player = show_character_creation(stdscr)
        sites  = make_sites()

        while True:   # inner loop: ship <-> site
            action = show_ship_screen(stdscr, player, sites)

            if action == 'quit':
                return
            if action == 'restart':
                break   # break inner -> outer -> new character creation

            # action == 'nav'
            site = show_nav_computer(stdscr, player, sites)
            if site is None:
                continue   # player pressed Esc

            player.fuel -= max(0, site.fuel_cost - player.fuel_discount)
            result = run_site(stdscr, site, player)

            if result == 'dead':
                if show_game_over(stdscr, player, site.name):
                    break   # new run
                else:
                    return  # quit

            if result == 'restart':
                break   # new run
            # result == 'escaped': loop back to ship screen


if __name__ == '__main__':
    curses.wrapper(main)
