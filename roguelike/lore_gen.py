"""Procedural lore generation for Erebus Station terminals.

Generates ambient log entries that scale in tone with dungeon depth.
No curses dependency — pure logic, safe to edit independently.
"""

import random

# ---------------------------------------------------------------------------
# Word banks
# ---------------------------------------------------------------------------

CREW_NAMES = [
    'Vasquez', 'Osei', 'Harlow', 'Nakamura', 'Reyes',
    'Bosch', 'Chen', 'Okafor', 'Nauth', 'Leblanc',
    'Kovacs', 'Adeyemi', 'Strauss', 'Yilmaz', 'Petrov',
    'Moreau', 'Diallo', 'Ishikawa', 'Andrade', 'Volkov',
    'Ekwueme', 'Szymanski', 'Ortega', 'Bergström', 'Tanaka',
]

RANKS = ['Dr.', 'Cpl.', 'Sgt.', 'Lt.', 'Tech.', 'Eng.', 'Spec.']

LOCATIONS = [
    'Sublevel 2', 'Lab C', 'Junction 7', 'Corridor B-12',
    'Crew Quarters Alpha', 'Engineering Bay', 'Medical Wing',
    'Comms Array', 'Server Room', 'Lower Processing',
    'Storage Deck 4', 'Reactor Anteroom', 'Observation Blister',
    'Maintenance Shaft 9', 'Pressurisation Hub',
]

EQUIPMENT = [
    'relay junction', 'cooling system', 'pressure seal',
    'atmospheric processor', 'data node', 'ventilation shaft',
    'power conduit', 'hull sensor array', 'thermal regulator',
    'secondary comms relay', 'emergency beacon', 'life-support module',
]

DEPTS = ['Engineering', 'Research', 'Security', 'Medical', 'Command']


# ---------------------------------------------------------------------------
# Depth tier
# ---------------------------------------------------------------------------

def _tier(floor_num):
    """Return tone tier: 0=mundane, 1=concerned/anomalous, 2=disturbed/desperate."""
    if floor_num <= 3:
        return 0
    if floor_num <= 6:
        return 1
    return 2


def _day(tier):
    if tier == 0:
        return random.randint(1, 20)
    if tier == 1:
        return random.randint(21, 50)
    return random.randint(51, 80)


# ---------------------------------------------------------------------------
# Template definitions
# Each template is a function that returns (title, body_sections, sign_offs).
# body_sections: list of sections; each section is [tier0_opts, tier1_opts, tier2_opts].
# sign_offs: [tier0_opts, tier1_opts, tier2_opts] — pick 0 or 1.
# ---------------------------------------------------------------------------

def _personal_log(name, rank, loc, day, n, dept, dept2, equip, tier):
    title = f"PERSONAL LOG — {rank} {name} — Day {day}"
    sections = [
        [  # opening
            [
                f"Settling into the routine. {loc} is quieter than I expected.",
                f"Day {day} aboard. Shift runs smooth. No complaints worth logging.",
                f"Crew morale is good. Hot meals twice a day and the comms lag is manageable.",
            ],
            [
                f"Something feels off today. Can't pin it down.",
                f"The atmosphere on {loc} has changed. People aren't talking like they used to.",
                f"I keep noticing things I can't explain. Small things. But they add up.",
            ],
            [
                f"I don't sleep anymore. Not really.",
                f"I write this in case I don't wake up. Day {day}. I'm still here. For now.",
                f"The sounds from below started again. I think I recognize one of the voices.",
            ],
        ],
        [  # middle
            [
                f"Ran diagnostics on the {equip}. All nominal. Filed report per standard.",
                f"Team meeting went long. Resource allocation disputes, nothing serious.",
                f"Caught up on backlogs from last rotation. Everything accounted for.",
            ],
            [
                f"I submitted a query about the {equip} anomaly. No response from Command.",
                f"Twice now the {equip} has failed during the same time window. Not random.",
                f"Found a notation in the maintenance log I didn't write. Date checks out.",
            ],
            [
                f"The {equip} in {loc} is beyond repair. I've stopped trying.",
                f"Found markings on the wall near {loc}. Looked like writing. I couldn't read it.",
                f"I've been sealing doors. It buys time. Not much.",
            ],
        ],
    ]
    sign_offs = [
        [
            f"Standard shift. Nothing to report. — {rank} {name}",
            f"Signing off. Back on deck in six. — {name}",
        ],
        [
            f"I'll raise it with the supervisor tomorrow. — {name}",
            f"Keeping this between me and the log for now. — {rank} {name}",
        ],
        [
            f"If anyone reads this — the lower levels are not safe.",
            f"Don't come looking for me.",
        ],
    ]
    return title, sections, sign_offs


def _maintenance_log(name, rank, loc, day, n, dept, dept2, equip, tier):
    title = f"MAINTENANCE LOG — {loc} — Day {day}"
    sections = [
        [  # fault description
            [
                f"Routine inspection of {equip} completed. No faults detected.",
                f"Replaced worn seals on the {equip}. Two-hour job, within schedule.",
                f"Calibration check: all sensors within tolerance. Logging as cleared.",
            ],
            [
                f"Unexplained power draw recorded near the {equip}. Source unconfirmed.",
                f"The {equip} in {loc} is cycling without input. Third occurrence.",
                f"Thermal variance in {loc} exceeds rated maximum. No obvious cause.",
            ],
            [
                f"The {equip} is non-functional. Cause: unknown. Recommend abandonment.",
                f"Something interfered with the {equip}. No tool I have can fix it.",
                f"Stopped logging faults. There are too many. The system is failing.",
            ],
        ],
        [  # action taken
            [
                f"Maintenance completed per schedule. Next inspection: Day {day + 14}.",
                f"All readings logged. Flagged for next quarterly review.",
                f"Crew notified. No disruption to operations.",
            ],
            [
                f"Submitted fault report. Awaiting authorisation to investigate further.",
                f"I've isolated the {equip} and notified {dept}. They haven't responded.",
                f"Attempting manual override. Results inconclusive.",
            ],
            [
                f"No action possible. I'm logging this for the record.",
                f"I tried. It didn't work.",
                f"Filed nothing. There's nobody left to file it with.",
            ],
        ],
    ]
    sign_offs = [
        [
            f"— {rank} {name}, {dept}",
            f"Signed: {name} / {dept}",
        ],
        [
            f"— {rank} {name} (flagged for follow-up)",
            f"This needs senior review. — {name}",
        ],
        [
            "",
            f"[ENTRY TRUNCATED]",
        ],
    ]
    return title, sections, sign_offs


def _security_report(name, rank, loc, day, n, dept, dept2, equip, tier):
    title = f"SECURITY REPORT — {loc} — Day {day}"
    sections = [
        [  # incident
            [
                f"Patrol of {loc} completed without incident. All checkpoints clear.",
                f"Minor altercation in crew quarters. Resolved. No injuries.",
                f"Access log review complete. No unauthorised entries this period.",
            ],
            [
                f"Unidentified personnel reported near {loc}. Unable to confirm identity.",
                f"Door sensor at {loc} tripped at 0300 hours. No one logged in that corridor.",
                f"Three crew members reported hearing voices in {loc}. Investigation ongoing.",
            ],
            [
                f"We've lost contact with the patrol assigned to {loc}.",
                f"The locks are not holding. I don't understand how it's getting through.",
                f"Something moved past the camera at {loc} at 0214. It wasn't crew.",
            ],
        ],
        [  # response
            [
                f"Standard patrol schedule maintained. No escalation required.",
                f"Crew reminded of access protocols. Incident closed.",
                f"Logging complete. No further action at this time.",
            ],
            [
                f"Increased patrol frequency near {loc}. Crew advised to travel in pairs.",
                f"Requested backup from {dept}. Awaiting authorisation.",
                f"Sealed section pending investigation. Crew access suspended.",
            ],
            [
                f"I've sealed what I can. It's not enough.",
                f"Evacuation protocol failed. Exits are compromised.",
                f"Arming remaining crew. Pray it helps.",
            ],
        ],
    ]
    sign_offs = [
        [
            f"— {rank} {name}, Security",
            f"Submitted per protocol. — {name}",
        ],
        [
            f"Escalating to Command. — {rank} {name}",
            f"This is above my clearance. — {name}",
        ],
        [
            f"— {name} [last patrol]",
            "",
        ],
    ]
    return title, sections, sign_offs


def _research_note(name, rank, loc, day, n, dept, dept2, equip, tier):
    title = f"RESEARCH NOTE — {name} — Entry {n}"
    sections = [
        [  # observation
            [
                f"Baseline readings from the {equip} logged at 0600. All within expected range.",
                f"Sample collection completed in {loc}. Catalogued and refrigerated.",
                f"Literature review complete. No comparable findings in the record.",
            ],
            [
                f"The readings don't fit any model I can apply.",
                f"Repeating the experiment with different parameters yields the same result.",
                f"I've cross-referenced six databases. Nothing accounts for this.",
            ],
            [
                f"I've stopped trying to explain it. I'm just documenting now.",
                f"The data is coherent. The implications are not.",
                f"Every measurement confirms what I don't want to confirm.",
            ],
        ],
        [  # interpretation
            [
                f"Preliminary analysis suggests normal variance. Further observation warranted.",
                f"Consistent with prior data. Hypothesis remains supported.",
                f"Requesting additional equipment from {dept} to continue analysis.",
            ],
            [
                f"Working hypothesis: the source is below {loc}. Depth unknown.",
                f"The pattern is not random. I'm increasingly certain of it.",
                f"Submitting findings to {dept} under restricted access. They won't like it.",
            ],
            [
                f"It knows we're looking. I can't prove that. I know it anyway.",
                f"The question was never whether it's real. The question is what it wants.",
                f"My notes are the only record. I'm keeping them hidden.",
            ],
        ],
    ]
    sign_offs = [
        [
            f"— {name}, {dept}",
            f"Next entry scheduled for Day {day + 3}.",
        ],
        [
            f"— {name} (restricted distribution)",
            f"Do not share without authorisation. — {name}",
        ],
        [
            f"[ENTRY ENDS]",
            f"— {name}",
        ],
    ]
    return title, sections, sign_offs


def _comms_fragment(name, rank, loc, day, n, dept, dept2, equip, tier):
    title = f"COMMS LOG — FRAGMENT — Day {day}"
    sections = [
        [  # fragment opening
            [
                f"[PARTIAL TRANSCRIPT — CHANNEL 4]",
                f"[AUTOMATED RECORD — {loc} RELAY]",
                f"[RECOVERED TRANSMISSION — QUALITY: GOOD]",
            ],
            [
                f"[PARTIAL TRANSCRIPT — CHANNEL 4 — DEGRADED]",
                f"[RECOVERED TRANSMISSION — QUALITY: POOR]",
                f"[AUTOMATED RECORD — {loc} RELAY — CORRUPTION DETECTED]",
            ],
            [
                f"[RECOVERED FRAGMENT — SOURCE UNKNOWN]",
                f"[PARTIAL RECORD — ORIGIN: SUBLEVEL — TIMESTAMP CORRUPT]",
                f"[EMERGENCY CHANNEL — FRAGMENT — UNVERIFIED]",
            ],
        ],
        [  # content
            [
                f"{name.upper()}: Confirm receipt of supply manifest. Over.",
                f"{rank} {name}: Shift handover complete. All clear on my end.",
                f"DISPATCH: Routine check-in from {loc}. Crew status nominal.",
            ],
            [
                f"{name.upper()}: Something's wrong with the {equip}. I need someone down here.",
                f"{rank} {name}: Don't — [static] — just get away from {loc} —",
                f"UNKNOWN: If you can hear this, do not come to {loc}.",
            ],
            [
                f"[UNINTELLIGIBLE] — please — [UNINTELLIGIBLE] — still here —",
                f"{name.upper()}: It's not [CORRUPTED]. It was never [CORRUPTED]. Run.",
                f"VOICE: I see you reading this. I've always seen you.",
            ],
        ],
        [  # closing
            [
                f"[END TRANSMISSION]",
                f"[CONNECTION CLOSED — NORMAL TERMINATION]",
            ],
            [
                f"[SIGNAL LOST]",
                f"[END OF RECOVERED SEGMENT]",
            ],
            [
                f"[RECORD ENDS]",
                f"[FURTHER DATA UNRECOVERABLE]",
            ],
        ],
    ]
    return title, sections, []  # no sign-offs for comms fragments


def _internal_memo(name, rank, loc, day, n, dept, dept2, equip, tier):
    title = f"INTERNAL MEMO — {dept} TO {dept2}"
    sections = [
        [  # subject line
            [
                f"RE: {equip.upper()} MAINTENANCE SCHEDULE",
                f"RE: CREW ROTATION — {loc.upper()}",
                f"RE: QUARTERLY RESOURCE ALLOCATION",
            ],
            [
                f"RE: UNEXPLAINED INCIDENTS — {loc.upper()} — RESTRICTED",
                f"RE: PROTOCOL DEVIATION — {dept2.upper()} STAFF",
                f"RE: ANOMALY REPORT SUPPRESSION — EYES ONLY",
            ],
            [
                f"RE: TOTAL COMMS BLACKOUT — IMMEDIATE EFFECT",
                f"RE: CONTAINMENT FAILURE — DO NOT FORWARD",
                f"RE: SURVIVAL PRIORITY — LAST RESORT PROTOCOLS",
            ],
        ],
        [  # body
            [
                f"Please ensure the {equip} inspection is completed by end of cycle.",
                f"Crew rotation for {loc} is confirmed. No changes to current schedule.",
                f"Resource requests for this period have been reviewed and approved.",
            ],
            [
                f"Three separate reports from {loc} have been escalated. Do not share externally.",
                f"All documentation related to the {equip} anomaly is to be centralised here.",
                f"Staff in {dept2} are asking questions we cannot answer. Redirect them.",
            ],
            [
                f"Standard protocols are no longer applicable. Use your judgement.",
                f"We cannot wait for authorisation. Act on this immediately.",
                f"Disregard previous guidance. Survival takes priority.",
            ],
        ],
        [  # sign-off
            [
                f"— {dept} Operations, Day {day}",
                f"Regards, {name} / {dept}",
            ],
            [
                f"— {rank} {name}, Acting {dept} Lead",
                f"This does not go in the public record. — {name}",
            ],
            [
                f"[SENDER UNVERIFIED]",
                f"— {name}",
            ],
        ],
    ]
    return title, sections, []  # sign-off is baked into last section


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_TEMPLATES = [
    _personal_log,
    _maintenance_log,
    _security_report,
    _research_note,
    _comms_fragment,
    _internal_memo,
]


def generate_terminal(floor_num=1):
    """Return (title_str, lines_list) — same shape as LORE_POOL entries."""
    tier  = _tier(floor_num)
    day   = _day(tier)
    n     = random.randint(1, 12)
    name  = random.choice(CREW_NAMES)
    rank  = random.choice(RANKS)
    loc   = random.choice(LOCATIONS)
    equip = random.choice(EQUIPMENT)
    depts = random.sample(DEPTS, 2)
    dept, dept2 = depts[0], depts[1]

    template_fn = random.choice(_TEMPLATES)
    title, sections, sign_offs = template_fn(
        name=name, rank=rank, loc=loc, day=day,
        n=n, dept=dept, dept2=dept2, equip=equip, tier=tier,
    )

    lines = []
    for i, section in enumerate(sections):
        tier_opts = section[min(tier, len(section) - 1)]
        sentence = random.choice(tier_opts)
        if i > 0 and sentence:
            lines.append("")
        if sentence:
            lines.append(sentence)

    # Optional sign-off (skip about 30% of the time)
    if sign_offs and random.random() < 0.7:
        tier_opts = sign_offs[min(tier, len(sign_offs) - 1)]
        sign = random.choice(tier_opts)
        if sign:
            lines.append("")
            lines.append(sign)

    return (title, lines)
