-- A tiny fake of the Civ 6 Lua API, enough to execute the mentor's queries
-- unchanged. Method names mirror the shipped UI Lua; behaviour is minimal.
-- 6x6 map, plot index = y * 6 + x, distance = Chebyshev (good enough here).

OUT = {}
print = function(s) table.insert(OUT, tostring(s)) end

local W, H = 6, 6
local hashSeq = 1000

local function gameinfo(rows, key)
  local t = { _rows = rows }
  for i, r in ipairs(rows) do
    r.Index = i - 1
    hashSeq = hashSeq + 1
    r.Hash = hashSeq
    t[r.Index] = r
    t[r[key]] = r
  end
  return setmetatable(t, {
    __call = function(self)
      local i = 0
      return function() i = i + 1; return rows[i] end
    end,
    __index = function(self, k)
      if type(k) == "number" then
        for _, r in ipairs(rows) do if r.Hash == k then return r end end
      end
      return nil
    end,
  })
end

GameInfo = {
  Units = gameinfo({
    { UnitType = "UNIT_SETTLER", FormationClass = "FORMATION_CLASS_CIVILIAN", BaseMoves = 2 },
    { UnitType = "UNIT_BUILDER", FormationClass = "FORMATION_CLASS_CIVILIAN", BaseMoves = 2 },
    { UnitType = "UNIT_WARRIOR", FormationClass = "FORMATION_CLASS_LAND_COMBAT", BaseMoves = 2 },
    { UnitType = "UNIT_SCOUT", FormationClass = "FORMATION_CLASS_LAND_COMBAT", PromotionClass = "PROMOTION_CLASS_RECON", BaseMoves = 3 },
  }, "UnitType"),
  Buildings = gameinfo({ { BuildingType = "BUILDING_MONUMENT" }, { BuildingType = "BUILDING_ARENA" } }, "BuildingType"),
  Districts = gameinfo({
    { DistrictType = "DISTRICT_CITY_CENTER", RequiresPopulation = false, CityCenter = true },
    { DistrictType = "DISTRICT_CAMPUS", RequiresPopulation = true, CityCenter = false },
    { DistrictType = "DISTRICT_HIDDEN_ENCAMPMENT", RequiresPopulation = true, CityCenter = false },
    { DistrictType = "DISTRICT_COMMERCIAL_HUB", RequiresPopulation = true, CityCenter = false },
  }, "DistrictType"),
  Boosts = gameinfo({
    { BoostID = "B_MILENG", TechnologyType = "TECH_MILITARY_ENGINEERING", Boost = 40, TriggerDescription = "Build a quarry" },
  }, "BoostID"),
  Projects = gameinfo({ { ProjectType = "PROJECT_BREAD_AND_CIRCUSES" } }, "ProjectType"),
  Technologies = gameinfo({ { TechnologyType = "TECH_POTTERY" }, { TechnologyType = "TECH_MILITARY_ENGINEERING" } }, "TechnologyType"),
  Civics = gameinfo({ { CivicType = "CIVIC_CODE_OF_LAWS" } }, "CivicType"),
  Governments = gameinfo({ { GovernmentType = "GOVERNMENT_CHIEFDOM" } }, "GovernmentType"),
  Governors = gameinfo({ { GovernorType = "GOVERNOR_THE_DEFENDER" } }, "GovernorType"),
  Improvements = gameinfo({
    { ImprovementType = "IMPROVEMENT_BARBARIAN_CAMP" },
    { ImprovementType = "IMPROVEMENT_HIDDEN_FORT" },
    { ImprovementType = "IMPROVEMENT_PLANTATION" },
  }, "ImprovementType"),
  Resources = gameinfo({
    { ResourceType = "RESOURCE_SILK", ResourceClassType = "RESOURCECLASS_LUXURY" },
    { ResourceType = "RESOURCE_HIDDEN_URANIUM", ResourceClassType = "RESOURCECLASS_STRATEGIC" },
    { ResourceType = "RESOURCE_HIDDEN_NITER", ResourceClassType = "RESOURCECLASS_STRATEGIC", PrereqTech = "TECH_MILITARY_ENGINEERING" },
  }, "ResourceType"),
  Religions = gameinfo({ { ReligionType = "RELIGION_BUDDHISM", Name = "Buddhism" }, { ReligionType = "RELIGION_HIDDEN_CATHOLIC", Name = "HIDDEN_RELIGION_CATHOLIC" } }, "ReligionType"),
  Terrains = gameinfo({ { TerrainType = "TERRAIN_GRASS" }, { TerrainType = "TERRAIN_DESERT" } }, "TerrainType"),
  Features = gameinfo({ { FeatureType = "FEATURE_HIDDEN_FOREST" } }, "FeatureType"),
}

Locale = { Lookup = function(s) return s end }

-- Plots ---------------------------------------------------------------------
local plots = {}
local Plot = {}
Plot.__index = Plot
function Plot:GetIndex() return self.idx end
function Plot:GetX() return self.x end
function Plot:GetY() return self.y end
function Plot:GetTerrainType() return self.terrain or 0 end
function Plot:GetResourceType() return self.res or -1 end
function Plot:GetFeatureType() return self.feature or -1 end
function Plot:GetImprovementType() return self.imp or -1 end
function Plot:IsImprovementPillaged() return self.pillaged or false end
function Plot:GetDistrictType() return self.district or -1 end
function Plot:GetOwner() return self.owner or -1 end
function Plot:GetWorkerCount() return self.worked and 1 or 0 end
function Plot:GetRouteType() return self.road and 0 or -1 end
function Plot:GetAppeal() return self.appeal or 0 end
for y = 0, H - 1 do
  for x = 0, W - 1 do
    local p = setmetatable({ x = x, y = y, idx = y * W + x }, Plot)
    plots[p.idx] = p
  end
end
local function P(x, y) return plots[y * W + x] end

Map = {
  GetPlotCount = function() return W * H end,
  GetPlotByIndex = function(i) return plots[i] end,
  GetPlot = function(x, y) if x < 0 or y < 0 or x >= W or y >= H then return nil end return P(x, y) end,
  GetPlotDistance = function(x1, y1, x2, y2) return math.max(math.abs(x1 - x2), math.abs(y1 - y2)) end,
}

-- Visibility for player 0: everything revealed except the bottom-right corner;
-- visible = within 2 of (1,1).
local function idxOf(a, b) if b ~= nil then return b * W + a end return a end
PlayersVisibility = {
  [0] = {
    IsRevealed = function(self, a, b) local i = idxOf(a, b); return not (plots[i].x >= 4 and plots[i].y >= 4) end,
    IsVisible = function(self, a, b) local i = idxOf(a, b); local p = plots[i]; return math.abs(p.x - 1) <= 2 and math.abs(p.y - 1) <= 2 end,
  },
}

-- Units -----------------------------------------------------------------------
local function unit(owner, id, typeName, x, y, extra)
  local u = { owner = owner, id = id, t = GameInfo.Units[typeName].Index, x = x, y = y, charges = 0 }
  for k, v in pairs(extra or {}) do u[k] = v end
  function u:GetID() return self.id end
  function u:GetType() return self.t end
  function u:GetX() return self.x end
  function u:GetY() return self.y end
  function u:GetOwner() return self.owner end
  function u:GetMovesRemaining() return 2 end
  function u:GetMaxDamage() return 100 end
  function u:GetDamage() return 0 end
  function u:GetBuildCharges() return self.charges end
  return u
end
local function members(list) return { Members = function() return ipairs(list) end } end

-- Cities ----------------------------------------------------------------------
local function city(id, name, x, y, cfg)
  local c = { id = id, name = name, x = x, y = y, cfg = cfg }
  function c:GetID() return self.id end
  function c:GetName() return self.name end
  function c:GetX() return self.x end
  function c:GetY() return self.y end
  function c:GetPopulation() return cfg.pop end
  function c:IsCapital() return cfg.capital end
  function c:GetYield(i) return 7 end
  function c:GetGrowth()
    local g = {}
    function g:GetAmenities() return cfg.amen end
    function g:GetAmenitiesNeeded() return cfg.need end
    function g:GetHousing() return cfg.housing end
    function g:GetAmenitiesFromLuxuries() return cfg.amen end
    function g:GetAmenitiesLostFromWarWeariness() return 0 end
    function g:GetHousingFromWater() return 3 end
    return g
  end
  function c:GetCulturalIdentity()
    return {
      GetLoyalty = function() return cfg.loy end,
      GetLoyaltyPerTurn = function() return cfg.lpt end,
      GetTurnsToConversion = function() return 9 end,
      GetIdentitySourcesDetailedBreakdown = function() return { { ["Pressure from Korea"] = -6 }, { ["Your citizens"] = 3 } } end,
    }
  end
  function c:GetBuildQueue()
    return {
      GetCurrentProductionTypeHash = function() return cfg.building and GameInfo.Buildings[cfg.building].Hash or 0 end,
      GetTurnsLeft = function() return 4 end,
      HasBeenPlaced = function(self, hash) return false end,
      CanProduce = function(self, hash, flag)
        local d = GameInfo.Districts[hash]
        return d ~= nil and d.DistrictType == "DISTRICT_COMMERCIAL_HUB"
      end,
      GetDistrictCost = function(self, idx) return 97 end,
    }
  end
  function c:GetDistricts()
    local ds = {}
    for _, d in ipairs(cfg.districts) do
      table.insert(ds, { GetType = function() return GameInfo.Districts[d].Index end, IsComplete = function() return true end })
    end
    return members(ds)
  end
  function c:GetBuildings()
    return { HasBuilding = function(self, i) return GameInfo.Buildings[i].BuildingType == "BUILDING_MONUMENT" and cfg.capital end }
  end
  return c
end

local myUnits = {
  unit(0, 11, "UNIT_BUILDER", 1, 1, { charges = 3 }),
  unit(0, 12, "UNIT_WARRIOR", 0, 0),
}
local barbUnits = {
  unit(63, 91, "UNIT_WARRIOR", 2, 2),          -- visible, 1 tile from the builder
  unit(63, 92, "UNIT_WARRIOR", 5, 5),          -- in fog: must not count
}
local spainUnits = { unit(2, 81, "UNIT_WARRIOR", 1, 0) } -- visible but not hostile (not at war)
local myCities = {
  city(65536, "Kyoto", 0, 0, { pop = 5, amen = 2, need = 3, housing = 6, loy = 90, lpt = 1, capital = true,
    building = "BUILDING_ARENA", districts = { "DISTRICT_CITY_CENTER", "DISTRICT_CAMPUS" } }),
}

-- Map contents
P(0, 0).owner = 0
P(1, 0).owner = 0; P(1, 0).res = GameInfo.Resources["RESOURCE_SILK"].Index        -- unimproved luxury
P(2, 1).owner = 0; P(2, 1).res = GameInfo.Resources["RESOURCE_HIDDEN_NITER"].Index -- needs a tech we lack
P(3, 3).imp = GameInfo.Improvements["IMPROVEMENT_BARBARIAN_CAMP"].Index            -- visible camp
P(5, 0).imp = GameInfo.Improvements["IMPROVEMENT_BARBARIAN_CAMP"].Index            -- revealed, not visible
P(4, 0).imp = GameInfo.Improvements["IMPROVEMENT_HIDDEN_FORT"].Index               -- revealed, not visible
P(4, 0).feature = GameInfo.Features["FEATURE_HIDDEN_FOREST"].Index
P(4, 0).district = GameInfo.Districts["DISTRICT_HIDDEN_ENCAMPMENT"].Index
P(4, 0).owner = 2
P(5, 5).res = GameInfo.Resources["RESOURCE_HIDDEN_URANIUM"].Index                  -- unrevealed
P(0, 1).owner = 0; P(0, 1).worked = true; P(0, 1).road = true

-- Players -----------------------------------------------------------------------
local function player(id, opts)
  local p = { id = id }
  function p:IsMajor() return opts.major end
  function p:IsAlive() return true end
  function p:IsBarbarian() return id == 63 end
  function p:GetUnits() return members(opts.units or {}) end
  function p:GetCities() return members(opts.cities or {}) end
  function p:GetDiplomacy()
    return {
      HasMet = function(self, other) return other == 1 or other == 0 end,  -- met Korea only
      IsAtWarWith = function(self, other) return false end,
    }
  end
  function p:GetResources()
    return {
      IsResourceVisible = function(self, hash)
        local r = GameInfo.Resources[hash]
        return r and r.ResourceType ~= "RESOURCE_HIDDEN_NITER"
      end,
      GetResourceAmount = function(self, i)
        local r = GameInfo.Resources[i]
        return (r and r.ResourceType == "RESOURCE_SILK") and 2 or 0
      end,
    }
  end
  function p:GetTechs()
    return {
      HasTech = function(self, i) return i == 0 end,
      GetResearchingTech = function() return 1 end,           -- TECH_MILITARY_ENGINEERING
      GetResearchProgress = function(self, i) return 70 end,
      GetResearchCost = function(self, i) return 100 end,
      HasBoostBeenTriggered = function(self, i) return false end,
    }
  end
  function p:GetCulture()
    return {
      GetCurrentGovernment = function() return 0 end,
      HasCivic = function(self, i) return i == 0 end,
      IsDominantOver = function(self, j) return opts.dominates or false end,
      GetTouristsFrom = function(self, j) return opts.tourists or 0 end,
      GetStaycationers = function() return 5 end,
      GetProgressingCivic = function() return 0 end,          -- CIVIC_CODE_OF_LAWS (no boost row)
      GetCulturalProgress = function(self, i) return 10 end,
      GetCultureCost = function(self, i) return 50 end,
      HasBoostBeenTriggered = function(self, i) return false end,
    }
  end
  function p:GetReligion()
    return {
      GetFaithYield = function() return 3.5 end,
      GetReligionTypeCreated = function() return opts.religion or -1 end,
      GetReligionInMajorityOfCities = function() return opts.majority or -1 end,
      GetPantheon = function() return id == 0 and 0 or -1 end,
    }
  end
  function p:GetGovernors()
    return {
      HasGovernor = function() return false end,
      CanAppoint = function() return true end,
      CanPromote = function() return false end,
    }
  end
  return p
end

Players = {
  [0] = player(0, { major = true, units = myUnits, cities = myCities, majority = 0 }),
  [1] = player(1, { major = true, religion = 0, majority = 0, tourists = 2 }),                   -- Korea, met
  [2] = player(2, { major = true, religion = 1, majority = 1, units = spainUnits, dominates = true, tourists = 9 }), -- unmet
  [63] = player(63, { major = false, units = barbUnits }),
}
PlayerConfigurations = {
  [0] = { GetCivilizationShortDescription = function() return "Japan" end },
  [1] = { GetCivilizationShortDescription = function() return "Korea" end },
  [2] = { GetCivilizationShortDescription = function() return "HIDDEN_CIV_SPAIN" end },
  [63] = { GetCivilizationShortDescription = function() return "Barbarians" end },
}
Game = {
  GetLocalPlayer = function() return 0 end,
  GetNationalParks = function()
    return { GetPossibleParkTiles = function(self, pid) return { P(1, 0).idx, P(5, 5).idx } end }
  end,
  GetEras = function()
    return {
      GetNextEraCountdown = function() return 6 end,  -- 7 turns left after the UI's +1
      HasHeroicGoldenAge = function(self, p) return false end,
      HasGoldenAge = function(self, p) return true end,
      HasDarkAge = function(self, p) return false end,
    }
  end,
}
Map.GetUnitsAt = function(x, y)
  local here = {}
  for _, u in ipairs(myUnits) do if u.x == x and u.y == y then table.insert(here, u) end end
  return { Units = function() local i = 0; return function() i = i + 1; return here[i] end end }
end
Map.GetCityPlots = function()
  return { GetPurchasedPlots = function(self, c) return { P(0, 0).idx, P(1, 0).idx, P(0, 1).idx, P(2, 1).idx } end }
end
Cities = { GetPlotPurchaseCity = function(plot) if plot:GetOwner() == 0 then return myCities[1] end return nil end }
CityManager = { GetCity = function(pid, id) for _, c in ipairs(myCities) do if c.id % 65536 == id then return c end end return nil end }

-- ---------------------------------------------------------------------------
-- Extras for the identity / empire / policies / production queries
-- ---------------------------------------------------------------------------
GameInfo.Governments[0].Tier = "GOVERNMENT_TIER_1"
GameInfo.Eras = gameinfo({ { EraType = "ERA_ANCIENT", Name = "Ancient Era" } }, "EraType")
GameInfo.Difficulties = gameinfo({ { DifficultyType = "DIFFICULTY_PRINCE", Name = "Prince" } }, "DifficultyType")
GameInfo.GameSpeeds = gameinfo({ { GameSpeedType = "GAMESPEED_STANDARD", CostMultiplier = 100 } }, "GameSpeedType")
GameInfo.Victories = gameinfo({
  { VictoryType = "VICTORY_TECHNOLOGY" }, { VictoryType = "VICTORY_CULTURE" }, { VictoryType = "VICTORY_SCORE" },
}, "VictoryType")
GameInfo.Policies = gameinfo({
  { PolicyType = "POLICY_GOD_KING", Name = "God King", GovernmentSlotType = "SLOT_ECONOMIC" },
  { PolicyType = "POLICY_SURVEY", Name = "Survey", GovernmentSlotType = "SLOT_MILITARY" },
  { PolicyType = "POLICY_HIDDEN_LOCKED", Name = "Locked", GovernmentSlotType = "SLOT_ECONOMIC" },
}, "PolicyType")
GameInfo.Yields = gameinfo({ { YieldType = "YIELD_FOOD" }, { YieldType = "YIELD_GOLD" } }, "YieldType")
MilitaryFormationTypes = { STANDARD_MILITARY_FORMATION = 0 }
GameConfiguration = {
  GetValue = function(k) if k == "GAME_SYNC_RANDOM_SEED" then return -2096689920 end return nil end,
  MakeHash = function(s) return #s end,
}
PlayerConfigurations[0].GetCivilizationTypeName = function() return "CIVILIZATION_AMERICA" end
for pid, cfg in pairs(PlayerConfigurations) do
  cfg.GetLeaderName = function() return pid == 0 and "Teddy Roosevelt" or "Leader" .. pid end
  cfg.GetHandicapTypeID = function() return #"DIFFICULTY_PRINCE" end
end
Game.GetCurrentGameTurn = function() return 11 end
Game.GetGameSpeedType = function() return 0 end
Game.IsVictoryEnabled = function(idx) return GameInfo.Victories[idx].VictoryType ~= "VICTORY_CULTURE" end
Game.GetEras = (function(orig)
  return function()
    local e = orig()
    e.GetCurrentEra = function() return 0 end
    e.GetPlayerCurrentScore = function(self, p) return 2 end
    e.GetPlayerDarkAgeThreshold = function(self, p) return 11 end
    e.GetPlayerGoldenAgeThreshold = function(self, p) return 25 end
    return e
  end
end)(Game.GetEras)
Plot.IsWater = function(self) return self.terrain == nil and self.x >= 5 and self.y == 0 end

local function extend(pid, extra)
  local p = Players[pid]
  local base = { GetTechs = p.GetTechs, GetCulture = p.GetCulture, GetReligion = p.GetReligion, GetDiplomacy = p.GetDiplomacy }
  p.GetScore = function() return extra.score end
  p.GetFavor = function() return 7 end
  p.GetTreasury = function()
    return { GetGoldBalance = function() return 60 end, GetGoldYield = function() return 6 end, GetTotalMaintenance = function() return 1 end }
  end
  p.GetTechs = function(self) local t = base.GetTechs(self); t.GetScienceYield = function() return 2.5 end; return t end
  p.GetCulture = function(self)
    local c = base.GetCulture(self)
    c.GetCultureYield = function() return 1.3 end
    c.GetNumPolicySlots = function() return 2 end
    c.GetSlotType = function(_, s) return s == 0 and 0 or 1 end
    c.GetSlotPolicy = function(_, s) return s == 0 and 0 or -1 end
    c.IsPolicyUnlocked = function(_, i) return i <= 1 end
    c.CanSlotPolicy = function(_, i, s) return i <= 1 end
    return c
  end
  p.GetReligion = function(self) local r = base.GetReligion(self); r.GetFaithBalance = function() return 0 end; return r end
  p.GetDiplomacy = function(self)
    local d = base.GetDiplomacy(self)
    d.HasDelegationAt = function(_, o) return false end
    d.HasEmbassyAt = function(_, o) return false end
    d.IsDiplomaticActionValid = function(_, a, o) return a == "DIPLOACTION_DECLARE_FRIENDSHIP" end
    d.GetAllianceType = function() return -1 end
    d.GetAllianceLevel = function() return 0 end
    return d
  end
  p.GetDiplomaticAI = function() return { GetDiplomaticStateIndex = function(_, o) return 3 end } end
  p.GetStats = function()
    return {
      GetMilitaryStrength = function() return extra.mil end,
      GetScienceVictoryPoints = function() return extra.svp end,
      GetScienceVictoryPointsTotalNeeded = function() return 50 end,
      GetDiplomaticVictoryPoints = function() return extra.dvp end,
      GetTourism = function() return 1 end,
    }
  end
  p.GetInfluence = function() return { CanReceiveInfluence = function() return false end } end
  p.GetTrade = function() return { GetOutgoingRouteCapacity = function() return extra.cap or 0 end } end
end
extend(0, { score = 30, mil = 20, svp = 0, dvp = 2, cap = 1 })
extend(1, { score = 40, mil = 45, svp = 3, dvp = 9 })
extend(2, { score = 999, mil = 9999, svp = 40, dvp = 19 })   -- unmet: must never appear
myCities[1].GetTrade = function() return { GetOutgoingRoutes = function() return { { TraderUnitID = 999, DestinationCityPlayer = 0, DestinationCityID = 1 } } end } end
myCities[1].GetGold = function() return { GetPurchaseCost = function(_, y, h, f) return 240 end } end
local bqOrig = myCities[1].GetBuildQueue
myCities[1].GetBuildQueue = function(self)
  local bq = bqOrig(self)
  bq.CanProduce = function(_, hash, flag)
    local u = GameInfo.Units[hash]; local b = GameInfo.Buildings[hash]; local d = GameInfo.Districts[hash]
    return (u and u.UnitType == "UNIT_SETTLER") or (b and b.BuildingType == "BUILDING_MONUMENT")
        or (d and d.DistrictType == "DISTRICT_COMMERCIAL_HUB") or false
  end
  bq.GetProductionCost = function(_, hash) return 80 end
  bq.GetTurnsLeft = function(_, hash) return 8 end
  return bq
end
