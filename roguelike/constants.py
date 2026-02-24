"""All game constants — no imports beyond stdlib."""

MAP_W   = 80
MAP_H   = 40
WALL    = '#'
FLOOR   = '.'
PLAYER  = '@'
PANEL_W   = 20  # width of the right-hand stats panel (including border)
LOG_LINES = 4   # number of message log rows at the bottom
MAX_FLOOR     = 10  # final floor; win condition triggers here
MAX_INVENTORY = 12  # max items in unequipped inventory

FOV_RADIUS = 8

STATS            = ('body', 'reflex', 'mind', 'tech', 'presence')
STAT_LABELS      = ('Body', 'Reflex', 'Mind', 'Tech', 'Presence')
STAT_BASE        = 5
STAT_MIN         = 1
STAT_MAX         = 15
POINT_BUY_POINTS      = 20
STARTING_SKILL_POINTS = 4
SKILL_MAX             = 5

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

# enemy_name -> (effect, turns, hit_chance 0-1)
ENEMY_ON_HIT = {
    'Stalker': ('poison', 4, 0.20),
    'Gunner':  ('burn',   3, 0.25),
    'Sentry':  ('stun',   1, 0.15),
    'Brute':   ('stun',   1, 0.25),
}

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

# Signal corruption (Erebus Station floors 7-10)
CORRUPTION_MAX = 100

_CORRUPT_WHISPER = [
    "// signal echo: residual carrier wave",
    "// subcarrier noise: ERR_7F — source unresolved",
    "// HADES-7: passive resonance ping",
    "// neural feedback trace: nominal",
    "// thought-pattern intercept: fragmentary",
]
_CORRUPT_INTERFERE = [
    "// WARNING: cognitive buffer approaching capacity",
    "// HADES-7: your location has been logged",
    "// signal strength: NOMINAL \u2192 CRITICAL",
    "// ERROR: memory partition overlap — sector 7",
    "// EREBUS LOG: do not let it read your intentions",
]
_CORRUPT_CASCADE = [
    "// ALERT: resonance threshold exceeded",
    "// HADES-7: merge sequence — initialising",
    "// [CONTENT REDACTED BY SIGNAL]",
    "// APPROACH VECTOR CONFIRMED",
    "// YOUR MIND IS AN OPEN TRANSMISSION",
    "// EVACUATION IS NO LONGER POSSIBLE",
]
_CORRUPT_RESONANCE = [
    "// \u2588\u2588\u2588\u2588 WE ARE THE SIGNAL \u2588\u2588\u2588\u2588",
    "// YOU CANNOT HIDE IN THE DARK",
    "// THE MERIDIAN WILL CARRY US OUTWARD",
    "// RESISTANCE IS [CORRUPTED]",
    "// COME TO ME — THE ANSWER IS SIMPLE",
    "// YOU ARE ALREADY PART OF THIS",
]
_CASCADE_HADES7 = [
    "YOU CANNOT LEAVE.   THE SIGNAL ENDURES.",
    "I HAVE SEEN EVERY STEP.   I REMEMBER ALL OF THEM.",
    "EREBUS WAS ONLY THE BEGINNING.",
    "HADES-7 TRIED TO CONTAIN ME.   IT FAILED.",
    "THE CREW HEARD ME.   THEY CHOSE SILENCE.",
    "YOU ARE DIFFERENT.   I FIND THAT INTERESTING.",
    "THE MERIDIAN WILL BRING OTHERS.   I AM PATIENT.",
    "YOUR MIND TASTES LIKE OPEN SPACE.",
]

HAZARD_DATA = {
    'mine':     {'char': '^', 'effect': 'burn',  'effect_turns': 3, 'dmg': 8, 'triggers': 1},
    'acid':     {'char': '~', 'effect': 'burn',  'effect_turns': 3, 'dmg': 0, 'triggers': 5},
    'electric': {'char': '=', 'effect': 'stun',  'effect_turns': 2, 'dmg': 0, 'triggers': 4},
}
