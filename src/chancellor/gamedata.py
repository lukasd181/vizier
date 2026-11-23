"""Game rules the mentor computes with, verified against the shipped game.

Every table here was read with REA (`inspect_sqlite_database`) from the
game's compiled gameplay database:

    ~/Library/Application Support/Sid Meier's Civilization VI/Firaxis Games/
        Sid Meier's Civilization VI/Cache/DebugGameplay.sqlite
    sha256 7d1acb3aaa494c00c220de1fc6045bfcb568682f1a09e6f2afb5103cd981941f
    (Gathering Storm ruleset: DISTRICT_DAM, DISTRICT_CANAL, DISTRICT_PRESERVE present)

The evidence ID next to each table is the REA record it came from; see
docs/game-data-evidence.md. Live values (a city's actual amenities, a
building's actual cost after modifiers) always come from the running game —
these tables are only for reasoning about *options* the game won't price.

The cache is rewritten whenever the game loads a different ruleset, and REA
showed rulesets do differ (Palace amenities 1 vs 2; see
docs/game-data-evidence.md). A live game therefore reads the entertainment,
housing and luxury tables from GameInfo (lua_queries.build_rules_query); these
constants are the fallback for fixtures and replays.
"""

from __future__ import annotations

from dataclasses import dataclass

RULESET_SHA256 = "7d1acb3aaa494c00c220de1fc6045bfcb568682f1a09e6f2afb5103cd981941f"


@dataclass(frozen=True)
class HappinessLevel:
    key: str
    min_net: int | None  # net amenities (have - needed), inclusive
    max_net: int | None
    growth_pct: int
    non_food_pct: int


# Happinesses table — ev_8f9f51aa611124297fb398b00b06e0627b3c374d892afd30a4fe6caeb6da5f00
HAPPINESS_LEVELS: tuple[HappinessLevel, ...] = (
    HappinessLevel("REVOLT", None, -7, -100, -40),
    HappinessLevel("UNREST", -6, -5, -100, -30),
    HappinessLevel("UNHAPPY", -4, -3, -30, -20),
    HappinessLevel("DISPLEASED", -2, -1, -15, -10),
    HappinessLevel("CONTENT", 0, 2, 0, 0),
    HappinessLevel("HAPPY", 3, 4, 10, 10),
    HappinessLevel("ECSTATIC", 5, None, 20, 20),
)


def happiness_for(net_amenities: int) -> HappinessLevel:
    for level in HAPPINESS_LEVELS:
        lo = level.min_net if level.min_net is not None else -(10**9)
        hi = level.max_net if level.max_net is not None else 10**9
        if lo <= net_amenities <= hi:
            return level
    return HAPPINESS_LEVELS[4]


# LoyaltyLevels table — ev_ea34e64837db14d5c8191af412cb23e947f85047f4a93c190c75fc0575f6b867
# (min loyalty, max loyalty, YieldChange multiplier): at 0-25 loyalty a city's
# yields are cut by 100%, at 26-50 by 50%, at 51-75 by 25%.
LOYALTY_LEVELS: tuple[tuple[int, int, float], ...] = (
    (0, 25, -1.0),
    (26, 50, -0.5),
    (51, 75, -0.25),
    (76, 100, 0.0),
)

# Victories.CriticalPercentage — the share of progress at which the game itself
# starts warning. ev_2706ec8b2548f6cb4e6554f6af628512eee41400bb3c537704bba30abd2cffe7
VICTORY_CRITICAL_PCT: dict[str, int] = {
    "VICTORY_CONQUEST": 50,
    "VICTORY_CULTURE": 75,
    "VICTORY_RELIGIOUS": 80,
    "VICTORY_TECHNOLOGY": 60,
    "VICTORY_DIPLOMATIC": 90,
}

# GlobalParameters — ev_90be58dc3b9ad2654d01d079831b166168fd765aa88ceebfae1a2535cfa27bdc
DIPLOMATIC_VICTORY_POINTS_REQUIRED = 20
CITY_POP_PER_AMENITY = 2
NATIONAL_PARK_AMENITIES_OWNING_CITY = 2
NATIONAL_PARK_NUM_OTHER_AMENITY_CITIES = 4
TRADE_ROUTE_TURN_DURATION_BASE = 20
LOYALTY_MAXIMUM = 100
BARBARIAN_CAMP_MINIMUM_DISTANCE_CITY = 4

# Buildings.Entertainment (amenities) — ev_b440c3861ca4a726fbadb7790c3c1d66adb8ef9a29e2823bcb622453e1d06b8d
# Wonders are included because they show up as production options too.
ENTERTAINMENT_BUILDINGS: dict[str, int] = {
    "BUILDING_PALACE": 1,
    "BUILDING_ARENA": 2,
    "BUILDING_TLACHTLI": 2,
    "BUILDING_ZOO": 1,
    "BUILDING_THERMAL_BATH": 2,
    "BUILDING_STADIUM": 1,
    "BUILDING_FERRIS_WHEEL": 2,
    "BUILDING_AQUARIUM": 1,
    "BUILDING_AQUATICS_CENTER": 1,
    "BUILDING_SHOPPING_MALL": 1,
    "BUILDING_STUPA": 1,
    "BUILDING_COLOSSEUM": 2,
    "BUILDING_ALHAMBRA": 2,
    "BUILDING_ESTADIO_DO_MARACANA": 2,
    "BUILDING_GREAT_BATH": 1,
    "BUILDING_GOLDEN_GATE_BRIDGE": 3,
}

# Buildings with RegionalRange > 0: their amenity also reaches nearby cities.
REGIONAL_ENTERTAINMENT: frozenset[str] = frozenset(
    {
        "BUILDING_ZOO",
        "BUILDING_STADIUM",
        "BUILDING_THERMAL_BATH",
        "BUILDING_AQUARIUM",
        "BUILDING_AQUATICS_CENTER",
        "BUILDING_COLOSSEUM",
    }
)

# Buildings.Housing — same evidence record.
HOUSING_BUILDINGS: dict[str, int] = {
    "BUILDING_PALACE": 1,
    "BUILDING_GRANARY": 2,
    "BUILDING_SEWER": 2,
    "BUILDING_PALGUM": 1,
    "BUILDING_BARRACKS": 1,
    "BUILDING_STABLE": 1,
    "BUILDING_BASILIKOI_PAIDES": 1,
    "BUILDING_ORDU": 1,
    "BUILDING_MILITARY_ACADEMY": 1,
    "BUILDING_LIGHTHOUSE": 1,
    "BUILDING_SEAPORT": 1,
    "BUILDING_UNIVERSITY": 1,
    "BUILDING_MADRASA": 1,
    "BUILDING_NAVIGATION_SCHOOL": 1,
    "BUILDING_GURDWARA": 1,
    "BUILDING_HANGING_GARDENS": 2,
    "BUILDING_TEMPLE_ARTEMIS": 3,
    "BUILDING_GREAT_BATH": 3,
}

# Districts.Entertainment / Districts.Housing — ev_1c8fbd61adf18952754d9c50f35d4ad0856f1b0d3040cac647e957da6e3546dd
ENTERTAINMENT_DISTRICTS: dict[str, int] = {
    "DISTRICT_ENTERTAINMENT_COMPLEX": 1,
    "DISTRICT_WATER_ENTERTAINMENT_COMPLEX": 1,
    "DISTRICT_STREET_CARNIVAL": 2,
    "DISTRICT_WATER_STREET_CARNIVAL": 2,
    "DISTRICT_HIPPODROME": 3,
    "DISTRICT_BATH": 1,
    "DISTRICT_DAM": 1,
}
HOUSING_DISTRICTS: dict[str, int] = {
    "DISTRICT_NEIGHBORHOOD": 4,  # base; the game scales it by appeal
    "DISTRICT_MBANZA": 5,
    "DISTRICT_DAM": 3,
    "DISTRICT_BATH": 2,
    "DISTRICT_IKANDA": 1,
    "DISTRICT_PRESERVE": 1,
}


@dataclass(frozen=True)
class PolicyAmenity:
    amount: int
    condition: str  # plain-language summary of the card's requirement set


# PolicyModifiers ⋈ Modifiers ⋈ ModifierArguments where ModifierType is
# MODIFIER_PLAYER_CITIES_ADJUST_POLICY_AMENITY.
# ev_bf72ecd25a5946f2722ecfc461e141013622f9b55bfb8c5449e3020456a181e1 (PolicyModifiers)
# ev_a3846477fa103da834b4435a112964174377a4c41876e839d71957576a7cb79e (Modifiers)
# ev_1b44225b0c0b626b1ba98dad48a26df06ea4d8683d24db086d3541a336aae831 (ModifierArguments)
# Amounts are observed; conditions are summarised from the card text and are the
# part to confirm in-game (requirement sets were not decoded).
POLICY_AMENITIES: dict[str, PolicyAmenity] = {
    "POLICY_RETAINERS": PolicyAmenity(1, "cities with a garrisoned unit"),
    "POLICY_LIBERALISM": PolicyAmenity(1, "cities with 2+ specialty districts"),
    "POLICY_NEW_DEAL": PolicyAmenity(2, "cities with 3+ specialty districts"),
    "POLICY_CIVIL_PRESTIGE": PolicyAmenity(1, "cities with an established governor"),
    "POLICY_SPORTS_MEDIA": PolicyAmenity(1, "extra amenity from each Stadium"),
    "POLICY_GOV_CLASSICAL_REPUBLIC": PolicyAmenity(1, "Classical Republic legacy bonus"),
    "POLICY_ROBBER_BARONS": PolicyAmenity(-2, "cost of the card"),
    "POLICY_MUSIC_CENSORSHIP": PolicyAmenity(-1, "cost of the card"),
    "POLICY_AUTOMATED_WORKFORCE": PolicyAmenity(-1, "cost of the card"),
}

# Happinesses_XP1.IdentityPerTurnChange: amenity level feeds loyalty.
# ev_b95e1cde7b46812574294ea76b1fe2e336e4d39d7c5f8ab1a7db8e772aa3a711
HAPPINESS_LOYALTY: dict[str, int] = {
    "REVOLT": -6,
    "UNREST": -6,
    "UNHAPPY": -6,
    "DISPLEASED": -3,
    "CONTENT": 0,
    "HAPPY": 3,
    "ECSTATIC": 6,
}

# Loyalty per turn from policies/buildings (MODIFIER_*_ADJUST_IDENTITY_PER_TURN).
# Policies: same PolicyModifiers/Modifiers/ModifierArguments evidence as above.
# Buildings: BuildingModifiers ev_8e009036debf9a901ea23556b90b94f2e962ddbd65f51168322ae3eea8c49caa
POLICY_LOYALTY: dict[str, tuple[int, str]] = {
    "POLICY_LIMITANEI": (2, "cities with a garrisoned unit"),
    "POLICY_PRAETORIUM": (2, "cities with a governor"),
    "POLICY_COLONIAL_OFFICES": (3, "cities not on your capital's continent"),
    "POLICY_MARTIAL_LAW": (4, "cities with a garrisoned unit"),
    "POLICY_AUTOMATED_WORKFORCE": (-5, "cost of the card"),
}
BUILDING_LOYALTY: dict[str, int] = {
    "BUILDING_MONUMENT": 1,
    "BUILDING_COLOSSEUM": 2,  # all cities within its regional range
}
# GlobalParameters: IDENTITY_PER_TURN_FROM_RELIGION_(MIS)MATCHING_FOUNDED = ±3,
# IDENTITY_PER_TURN_FROM_STARVATION = -4, GOVERNOR_BASE_TURNS_TO_ESTABLISH = 5.
RELIGION_LOYALTY = 3
STARVATION_LOYALTY = -4
GOVERNOR_TURNS_TO_ESTABLISH = 5
# The governor's own +8 loyalty is not in the gameplay database (no modifier or
# parameter carries it) — it appears to be an engine constant. Treat as an estimate.
GOVERNOR_LOYALTY_ESTIMATE = 8

CIVILIAN_UNIT_TYPES: frozenset[str] = frozenset(
    {
        "UNIT_SETTLER",
        "UNIT_BUILDER",
        "UNIT_TRADER",
        "UNIT_MILITARY_ENGINEER",
        "UNIT_ARCHAEOLOGIST",
        "UNIT_NATURALIST",
        "UNIT_ROCK_BAND",
    }
)

RECON_UNIT_TYPES: frozenset[str] = frozenset(
    {"UNIT_SCOUT", "UNIT_SKIRMISHER", "UNIT_RANGER", "UNIT_SPEC_OPS", "UNIT_OKIHTCITAW"}
)

SPECIALTY_DISTRICTS: frozenset[str] = frozenset(
    {
        "DISTRICT_CAMPUS",
        "DISTRICT_THEATER",
        "DISTRICT_HOLY_SITE",
        "DISTRICT_COMMERCIAL_HUB",
        "DISTRICT_HARBOR",
        "DISTRICT_INDUSTRIAL_ZONE",
        "DISTRICT_ENCAMPMENT",
        "DISTRICT_ENTERTAINMENT_COMPLEX",
        "DISTRICT_WATER_ENTERTAINMENT_COMPLEX",
        "DISTRICT_AERODROME",
        "DISTRICT_GOVERNMENT",
        "DISTRICT_DIPLOMATIC_QUARTER",
        "DISTRICT_PRESERVE",
    }
)
