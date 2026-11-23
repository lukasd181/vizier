"""Source-independent views of the game, as a player could see it.

Every StateSource produces an EmpireSnapshot and every rule, option and goal
check reads only from it. Nothing in here may hold information the local
player couldn't see in the game UI — fog.py enforces that before a snapshot
leaves a source.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CityView:
    city_id: int
    name: str
    x: int
    y: int
    population: int
    amenities: int  # GetAmenities(): total provided
    amenities_needed: int  # GetAmenitiesNeeded()
    housing: float
    loyalty: float = 100.0
    loyalty_per_turn: float = 0.0
    production: float = 0.0
    currently_building: str = "NONE"
    production_turns_left: int = 0
    districts: list[str] = field(default_factory=list)
    buildings: list[str] = field(default_factory=list)
    specialty_districts: int = 0
    has_governor: bool = False
    is_capital: bool = False
    has_garrison: bool = False

    @property
    def net_amenities(self) -> int:
        # Same formula as the game's CitySupport.lua: GetAmenities() - GetAmenitiesNeeded()
        return self.amenities - self.amenities_needed

    @property
    def housing_left(self) -> float:
        return self.housing - self.population

    @property
    def queue_empty(self) -> bool:
        return self.currently_building in ("", "NONE", "UNKNOWN")


@dataclass
class UnitView:
    unit_id: int
    unit_type: str
    x: int
    y: int
    moves_remaining: float = 0.0
    health: int = 100
    is_civilian: bool = False
    is_recon: bool = False
    # Nearest *visible* hostile (barbarian or at-war civ) within 3 tiles, if any.
    threat_distance: int | None = None
    threat_desc: str = ""


@dataclass
class RivalView:
    player_id: int
    name: str
    score: int = 0
    num_cities: int = 0
    military_strength: int = 0
    science_vp: int = 0
    science_vp_needed: int = 0
    diplomatic_vp: int = 0
    tourism: int = 0
    # Religious victory: how many major civs follow this rival's religion as majority.
    religion_civs_converted: int = 0
    has_religion: bool = False
    religion_name: str = ""
    # Culture victory: civs (among those we know) this rival dominates, and
    # their tourists from us vs our domestic tourists.
    culture_civs_dominated: int = 0
    our_tourists_from_them: int = 0
    our_staycationers: int = 0
    diplomatic_state: str = "UNKNOWN"
    at_war: bool = False
    we_have_delegation: bool = False
    we_have_embassy: bool = False
    can_declare_friendship: bool = False
    can_form_alliance: bool = False
    is_friend: bool = False
    is_ally: bool = False


@dataclass
class CampView:
    x: int
    y: int
    distance_to_city: int


@dataclass
class EmpireSnapshot:
    turn: int
    civ: str
    leader: str
    difficulty: str = ""
    speed_multiplier: int = 100  # 67 quick, 100 standard, 150 epic, 300 marathon
    era: str = ""
    gold: float = 0.0
    gold_per_turn: float = 0.0
    faith: float = 0.0
    faith_per_turn: float = 0.0
    favor: int = 0
    favor_per_turn: int = 0
    science_per_turn: float = 0.0
    culture_per_turn: float = 0.0
    explored_land: int = 0
    total_land: int = 0
    cities: list[CityView] = field(default_factory=list)
    units: list[UnitView] = field(default_factory=list)
    rivals: list[RivalView] = field(default_factory=list)
    camps: list[CampView] = field(default_factory=list)
    trade_capacity: int = 0
    trade_active: int = 0
    trade_ghosts: int = 0
    religions_founded: int = 0
    religions_max: int = 0
    our_religion: str = ""
    great_prophet_available: bool = True
    alive_majors: int = 0  # including us; the game setup shows this
    our_military_strength: int = 0
    our_science_vp: int = 0
    our_science_vp_needed: int = 0
    our_diplomatic_vp: int = 0
    our_tourism: int = 0
    techs: set[str] = field(default_factory=set)
    civics: set[str] = field(default_factory=set)
    government: str = ""
    enabled_victories: set[str] = field(default_factory=set)
    # Era score (golden / dark age): thresholds from the game, countdown 0 = not running
    era_score: int = 0
    era_dark_threshold: int = 0
    era_golden_threshold: int = 0
    era_countdown: int = 0
    age: str = ""  # normal | golden | heroic | dark
    luxuries: dict[str, int] = field(default_factory=dict)  # resource type -> copies held
    luxury_cities: dict[str, int] = field(default_factory=dict)  # Resources.Happiness: cities each copy feeds
    # "tech" / "civic" -> {item, progress, cost, boosted, boost_pct, trigger}
    research: dict[str, dict[str, Any]] = field(default_factory=dict)
    governors: dict[str, Any] = field(default_factory=dict)  # can_appoint, can_promote, unassigned
    has_pantheon: bool = False
    # specialty districts unlocked but placed in no city: {district, cost, city}
    unplaced_districts: list[dict[str, Any]] = field(default_factory=list)
    slotted_policies: set[str] = field(default_factory=set)
    available_policies: set[str] = field(default_factory=set)
    full_vision: bool = False  # debug mode — set only by an explicit developer flag

    @property
    def explored_pct(self) -> float:
        if self.total_land <= 0:
            return 0.0
        return 100.0 * self.explored_land / self.total_land

    @property
    def civilians(self) -> list[UnitView]:
        return [u for u in self.units if u.is_civilian]

    @property
    def recon_units(self) -> list[UnitView]:
        return [u for u in self.units if u.is_recon]

    def victory_enabled(self, victory_type: str) -> bool:
        # Empty set = the source couldn't tell; assume the standard set is on.
        return not self.enabled_victories or victory_type in self.enabled_victories

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["techs"] = sorted(self.techs)
        d["civics"] = sorted(self.civics)
        d["enabled_victories"] = sorted(self.enabled_victories)
        d["slotted_policies"] = sorted(self.slotted_policies)
        d["available_policies"] = sorted(self.available_policies)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EmpireSnapshot:
        d = dict(d)
        d["cities"] = [CityView(**c) for c in d.get("cities", [])]
        d["units"] = [UnitView(**u) for u in d.get("units", [])]
        d["rivals"] = [RivalView(**r) for r in d.get("rivals", [])]
        d["camps"] = [CampView(**c) for c in d.get("camps", [])]
        for k in ("techs", "civics", "enabled_victories", "slotted_policies", "available_policies"):
            d[k] = set(d.get(k, []))
        return cls(**d)


@dataclass
class TileView:
    x: int
    y: int
    terrain: str
    feature: str = ""
    resource: str = ""  # empty if none or not visible to us
    resource_class: str = ""
    improvement: str = ""
    pillaged: bool = False
    district: str = ""
    owner: str = ""  # "me", civ name, or ""
    owner_id: int = -1
    city_id: int = -1  # owning city, if ours
    worked: bool = False
    has_road: bool = False
    appeal: int | None = None
    visible: bool = False  # currently in sight (vs. only revealed)


SEVERITY_CRITICAL = 1
SEVERITY_WARNING = 2
SEVERITY_INFO = 3
SEVERITY_NAMES = {1: "critical", 2: "warning", 3: "info"}


@dataclass
class Alert:
    rule: str
    key: str  # what it's about, e.g. "city=65536" — makes the ID stable across turns
    severity: int
    category: str  # victory | city | economy | expansion | military | diplomacy | data
    title: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)
    fix_tool: str | None = None
    # Position in the CivBench failure chain: lower = more upstream.
    # exploration(1) → expansion(2) → economy/city(3) → victory path(4).
    root_cause: int = 3

    @property
    def id(self) -> str:
        return f"{self.rule}:{self.key}"


@dataclass
class FixOption:
    action: str
    kind: str  # luxury | building | district | policy | trade | governor | unit | project | peace | economy
    gain: float
    gain_unit: str  # "amenity", "loyalty/turn", "housing"
    turns: int | None  # turns until the effect lands; None = depends on someone else
    cost: str
    gold_cost: int | None = None
    confidence: str = "exact"  # exact | estimate | depends
    notes: str = ""


@dataclass
class Goal:
    victory: str  # science | culture | religious | diplomatic | domination | score | none
    style: str = ""  # free text, e.g. "peaceful builder", "roleplay Rome"
    difficulty: str = ""
    help_level: str = "advisor"  # off | watchdog | advisor | coach
    set_turn: int = 0
    pace: str = "minimum"  # minimum (CivBench floor) | pro (a pro player's expansion pace)


@dataclass
class Commitment:
    id: int
    text: str
    created_turn: int
    due_turn: int
    check_kind: str = "manual"
    check_arg: str = ""
    status: str = "open"  # open | done | overdue | dropped
    done_turn: int | None = None
