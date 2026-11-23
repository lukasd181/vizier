"""Vizier's Lua queries, sent to the game over FireTuner (chancellor.tuner).

Each build_* returns Lua source that prints pipe-delimited lines and ends
with the sentinel; each parse_* turns those lines into plain dicts. All of
these run in the InGame context (GameConnection.execute_write), which is
where the game's own UI code calls the same APIs. The identity, empire,
policy and production queries are adapted from civ6-mcp's (MIT, see NOTICE).

Fog rules applied here, at the source (fog.py re-applies them in Python):
  * tiles: only plots PlayersVisibility:IsRevealed; anything that can change
    after you last looked (improvement, owner, district, pillage, road) is
    only reported for plots you can currently see.
  * resources: only if Players[me]:GetResources():IsResourceVisible(hash),
    the same check the game's plot tooltip uses.
  * foreign units: only on plots PlayersVisibility:IsVisible.
  * camps: only on visible plots; the store remembers ones seen earlier.
  * rivals: only players we have met.

Every API name used here appears in the shipped UI Lua under
Civ6.app/Contents/Assets (see docs/game-data-evidence.md).
"""

from __future__ import annotations

from chancellor.tuner import SENTINEL


def _lua_str_list(items: list[str]) -> str:
    return "{" + ",".join(f'"{s}"' for s in items) + "}"


_LUA_PRELUDE = """
local me = Game.GetLocalPlayer()
local pMe = Players[me]
local vis = PlayersVisibility[me]
local pDiplo = pMe:GetDiplomacy()
local pRes = pMe:GetResources()
local function clean(s) return (tostring(s or ""):gsub("|", "/")) end
local function resVisible(row)
    local ok, v = pcall(function() return pRes:IsResourceVisible(row.Hash) end)
    if ok then return v end
    if not row.PrereqTech then return true end
    local t = GameInfo.Technologies[row.PrereqTech]
    return t ~= nil and pMe:GetTechs():HasTech(t.Index)
end
local function isHostile(pid)
    if pid == me then return false end
    local p = Players[pid]
    if not p or not p:IsAlive() then return false end
    local okB, barb = pcall(function() return p:IsBarbarian() end)
    if okB and barb then return true end
    local okW, war = pcall(function() return pDiplo:IsAtWarWith(pid) end)
    return okW and war
end
"""


# ---------------------------------------------------------------------------
# Empire state (cities, units, camps, techs, rivals' visible victory facts)
# ---------------------------------------------------------------------------


def build_mentor_state_query(known_camps: list[tuple[int, int]] | None = None) -> str:
    """Cities, units, camps, techs, eras, research and districts — one round-trip.
    build_empire_query covers the overview, rivals, trade and policies.

    known_camps: camps remembered from earlier turns; for each one on a plot
    we can see now, prints CAMPGONE if it has been cleared.
    """
    camps = known_camps or []
    camp_list = "{" + ",".join(f"{{{x},{y}}}" for x, y in camps) + "}"
    return (
        _LUA_PRELUDE
        + """
local hashName = {}
for row in GameInfo.Units() do hashName[row.Hash] = row.UnitType end
for row in GameInfo.Buildings() do hashName[row.Hash] = row.BuildingType end
for row in GameInfo.Districts() do hashName[row.Hash] = row.DistrictType end
for row in GameInfo.Projects() do hashName[row.Hash] = row.ProjectType end

-- Government, faith, techs, civics
pcall(function()
    local g = GameInfo.Governments[pMe:GetCulture():GetCurrentGovernment()]
    print("GOV|" .. (g and g.GovernmentType or "NONE"))
end)
pcall(function() print("FAITHPT|" .. string.format("%.1f", pMe:GetReligion():GetFaithYield())) end)
local techs, civics = {}, {}
for row in GameInfo.Technologies() do
    if pMe:GetTechs():HasTech(row.Index) then table.insert(techs, row.TechnologyType) end
end
for row in GameInfo.Civics() do
    if pMe:GetCulture():HasCivic(row.Index) then table.insert(civics, row.CivicType) end
end
print("TECHS|" .. table.concat(techs, ";"))
print("CIVICS|" .. table.concat(civics, ";"))

-- Majors alive (the setup screen and World Rankings show this count)
local majors = 0
for i = 0, 62 do
    local p = Players[i]
    if p and p:IsMajor() and p:IsAlive() then majors = majors + 1 end
end
print("MAJORS|" .. majors)

-- Era: turns left and current age type, as ActionPanel_Expansion1.lua reads them
-- (GetNextEraCountdown() + 1 = turns remaining; 0 = no countdown running)
pcall(function()
    local eras = Game.GetEras()
    local age = "normal"
    if eras:HasHeroicGoldenAge(me) then age = "heroic"
    elseif eras:HasGoldenAge(me) then age = "golden"
    elseif eras:HasDarkAge(me) then age = "dark" end
    print("ERA|" .. (eras:GetNextEraCountdown() + 1) .. "|" .. age)
end)

-- Luxury copies held (for surplus / sell advice)
local lux = {}
for row in GameInfo.Resources() do
    if row.ResourceClassType == "RESOURCECLASS_LUXURY" then
        local okA, n = pcall(function() return pRes:GetResourceAmount(row.Index) end)
        if okA and n and n > 0 then table.insert(lux, row.ResourceType .. "=" .. n) end
    end
end
print("LUXHELD|" .. table.concat(lux, ";"))

-- Current research / civic and their eurekas (TechAndCivicSupport.lua / LaunchBar.lua)
local function boostFor(col, key)
    for b in GameInfo.Boosts() do
        if b[col] == key then return b end
    end
    return nil
end
pcall(function()
    local pT = pMe:GetTechs()
    local t = pT:GetResearchingTech()
    if t and t >= 0 then
        local row = GameInfo.Technologies[t]
        local b = boostFor("TechnologyType", row.TechnologyType)
        print("RESEARCH|tech|" .. row.TechnologyType .. "|" .. pT:GetResearchProgress(t) .. "|" .. pT:GetResearchCost(t)
            .. "|" .. (pT:HasBoostBeenTriggered(t) and "1" or "0") .. "|" .. (b and (b.Boost or 40) or 0)
            .. "|" .. (b and b.TriggerDescription and clean(Locale.Lookup(b.TriggerDescription)) or ""))
    end
end)
pcall(function()
    local pC = pMe:GetCulture()
    local c = pC:GetProgressingCivic()
    if c and c >= 0 then
        local row = GameInfo.Civics[c]
        local b = boostFor("CivicType", row.CivicType)
        print("RESEARCH|civic|" .. row.CivicType .. "|" .. pC:GetCulturalProgress(c) .. "|" .. pC:GetCultureCost(c)
            .. "|" .. (pC:HasBoostBeenTriggered(c) and "1" or "0") .. "|" .. (b and (b.Boost or 40) or 0)
            .. "|" .. (b and b.TriggerDescription and clean(Locale.Lookup(b.TriggerDescription)) or ""))
    end
end)

-- Governors (LaunchBar_Expansion1.lua) and pantheon
pcall(function()
    local pGovs = pMe:GetGovernors()
    local idle = 0
    for row in GameInfo.Governors() do
        if pGovs:HasGovernor(row.Hash) and pGovs:GetGovernor(row.Hash):GetAssignedCity() == nil then idle = idle + 1 end
    end
    print("GOVCAN|" .. (pGovs:CanAppoint() and "1" or "0") .. "|" .. (pGovs:CanPromote() and "1" or "0") .. "|" .. idle)
end)
pcall(function() print("PANTHEON|" .. ((pMe:GetReligion():GetPantheon() or -1) >= 0 and "1" or "0")) end)

-- Specialty districts unlocked but not placed in any city: their cost keeps
-- rising with tech/civic progress until one is placed (ProductionPanel.lua)
pcall(function()
    for row in GameInfo.Districts() do
        if row.RequiresPopulation and not row.CityCenter and row.DistrictType ~= "DISTRICT_WONDER" then
            local placed, canAt, cost = false, nil, 0
            for _, c in pMe:GetCities():Members() do
                local bq = c:GetBuildQueue()
                for _, d in c:GetDistricts():Members() do
                    local di = GameInfo.Districts[d:GetType()]
                    if di and (di.DistrictType == row.DistrictType) then placed = true end
                end
                if not placed and bq:HasBeenPlaced(row.Hash) then placed = true end
                if canAt == nil and bq:CanProduce(row.Hash, true) then
                    canAt = c
                    cost = bq:GetDistrictCost(row.Index)
                end
            end
            if canAt and not placed then
                print("DISTUNLOCK|" .. row.DistrictType .. "|" .. math.floor(cost) .. "|" .. clean(Locale.Lookup(canAt:GetName())))
            end
        end
    end
end)

-- Governor per city
local govCity = {}
pcall(function()
    local pGovs = pMe:GetGovernors()
    for row in GameInfo.Governors() do
        if pGovs:HasGovernor(row.Hash) then
            local g = pGovs:GetGovernor(row.Hash)
            local c = g:GetAssignedCity()
            if c and g:IsEstablished() then govCity[c:GetID()] = true end
        end
    end
end)

-- Visible hostile military units (for civilian-at-risk)
local hostiles = {}
for i = 0, 63 do
    if isHostile(i) then
        local units = Players[i]:GetUnits()
        if units then
            for _, u in units:Members() do
                local ux, uy = u:GetX(), u:GetY()
                if ux >= 0 and vis:IsVisible(ux, uy) then
                    local info = GameInfo.Units[u:GetType()]
                    if info and info.FormationClass ~= "FORMATION_CLASS_CIVILIAN" then
                        local who = (i == 63) and "Barbarian" or clean(Locale.Lookup(PlayerConfigurations[i]:GetCivilizationShortDescription()))
                        table.insert(hostiles, {x = ux, y = uy, desc = who .. " " .. info.UnitType})
                    end
                end
            end
        end
    end
end

-- Cities
local cityXY = {}
for _, c in pMe:GetCities():Members() do
    local ok, err = pcall(function()
        local g = c:GetGrowth()
        local loy, loyPT = 100, 0
        pcall(function()
            local ci = c:GetCulturalIdentity()
            loy = ci:GetLoyalty()
            loyPT = ci:GetLoyaltyPerTurn()
        end)
        local bq = c:GetBuildQueue()
        local h = bq:GetCurrentProductionTypeHash()
        local building = "NONE"
        local turnsLeft = 0
        if h and h ~= 0 then
            building = hashName[h] or "UNKNOWN"
            turnsLeft = bq:GetTurnsLeft()
        end
        local dists, specialty = {}, 0
        for _, d in c:GetDistricts():Members() do
            local info = GameInfo.Districts[d:GetType()]
            if info and d:IsComplete() then
                table.insert(dists, info.DistrictType)
                if info.RequiresPopulation and not info.CityCenter then specialty = specialty + 1 end
            end
        end
        local blds = {}
        local pBld = c:GetBuildings()
        for row in GameInfo.Buildings() do
            if pBld:HasBuilding(row.Index) then table.insert(blds, row.BuildingType) end
        end
        local garrison = "0"
        local at = Map.GetUnitsAt(c:GetX(), c:GetY())
        if at then
            for gu in at:Units() do
                if gu:GetOwner() == me then
                    local gi = GameInfo.Units[gu:GetType()]
                    if gi and (gi.FormationClass == "FORMATION_CLASS_LAND_COMBAT" or gi.FormationClass == "FORMATION_CLASS_NAVAL_COMBAT") then garrison = "1" end
                end
            end
        end
        table.insert(cityXY, {x = c:GetX(), y = c:GetY()})
        print("CITY|" .. c:GetID() .. "|" .. clean(Locale.Lookup(c:GetName())) .. "|" .. c:GetX() .. "|" .. c:GetY()
            .. "|" .. c:GetPopulation() .. "|" .. g:GetAmenities() .. "|" .. g:GetAmenitiesNeeded()
            .. "|" .. string.format("%.1f", g:GetHousing()) .. "|" .. string.format("%.1f|%.1f", loy, loyPT)
            .. "|" .. string.format("%.1f", c:GetYield(1)) .. "|" .. building .. "|" .. turnsLeft
            .. "|" .. specialty .. "|" .. (govCity[c:GetID()] and "1" or "0") .. "|" .. (c:IsCapital() and "1" or "0")
            .. "|" .. garrison .. "|" .. table.concat(dists, ";") .. "|" .. table.concat(blds, ";"))
    end)
    if not ok then print("WARN|city " .. tostring(c:GetID()) .. ": " .. clean(err)) end
end

-- Own units
for _, u in pMe:GetUnits():Members() do
    pcall(function()
        local info = GameInfo.Units[u:GetType()]
        if not info then return end
        local ux, uy = u:GetX(), u:GetY()
        if ux < 0 then return end
        local civ = info.FormationClass == "FORMATION_CLASS_CIVILIAN" and "1" or "0"
        local recon = info.PromotionClass == "PROMOTION_CLASS_RECON" and "1" or "0"
        local best, bestDesc = -1, ""
        for _, hst in ipairs(hostiles) do
            local d = Map.GetPlotDistance(ux, uy, hst.x, hst.y)
            if d <= 3 and (best < 0 or d < best) then best, bestDesc = d, hst.desc end
        end
        local hp = u:GetMaxDamage() - u:GetDamage()
        print("UNIT|" .. u:GetID() .. "|" .. info.UnitType .. "|" .. ux .. "|" .. uy .. "|"
            .. string.format("%.1f", u:GetMovesRemaining()) .. "|" .. hp .. "|" .. civ .. "|" .. recon
            .. "|" .. best .. "|" .. bestDesc)
    end)
end

-- Barbarian camps on plots we can see right now
local campIdx = GameInfo.Improvements["IMPROVEMENT_BARBARIAN_CAMP"]
campIdx = campIdx and campIdx.Index or -1
local function nearestCity(x, y)
    local best = 999
    for _, cxy in ipairs(cityXY) do
        local d = Map.GetPlotDistance(x, y, cxy.x, cxy.y)
        if d < best then best = d end
    end
    return best
end
if campIdx >= 0 then
    for idx = 0, Map.GetPlotCount() - 1 do
        if vis:IsVisible(idx) then
            local plot = Map.GetPlotByIndex(idx)
            if plot:GetImprovementType() == campIdx then
                print("CAMPSEEN|" .. plot:GetX() .. "|" .. plot:GetY() .. "|" .. nearestCity(plot:GetX(), plot:GetY()))
            end
        end
    end
    for _, kc in ipairs("""
        + camp_list
        + """) do
        local plot = Map.GetPlot(kc[1], kc[2])
        if plot and vis:IsVisible(plot:GetIndex()) and plot:GetImprovementType() ~= campIdx then
            print("CAMPGONE|" .. kc[1] .. "|" .. kc[2])
        end
    end
end

-- Met rivals: religion and culture facts the World Rankings screen shows
local relFounder = {}
for i = 0, 62 do
    local p = Players[i]
    if p and p:IsMajor() and p:IsAlive() then
        local r = p:GetReligion():GetReligionTypeCreated()
        if r and r >= 0 then relFounder[r] = i end
    end
end
local relCount = {}
for i = 0, 62 do
    local p = Players[i]
    if p and p:IsMajor() and p:IsAlive() then
        local maj = p:GetReligion():GetReligionInMajorityOfCities()
        if maj and maj >= 0 then relCount[maj] = (relCount[maj] or 0) + 1 end
    end
end
for r, founder in pairs(relFounder) do
    if founder ~= me and pDiplo:HasMet(founder) then
        local row = GameInfo.Religions[r]
        local nm = row and clean(Locale.Lookup(row.Name)) or "Unknown"
        print("REL|" .. founder .. "|" .. nm .. "|" .. (relCount[r] or 0))
    end
end
local pCulMe = pMe:GetCulture()
for i = 0, 62 do
    local p = Players[i]
    if i ~= me and p and p:IsMajor() and p:IsAlive() and pDiplo:HasMet(i) then
        pcall(function()
            local pc = p:GetCulture()
            local dom = 0
            for j = 0, 62 do
                local q = Players[j]
                if j ~= i and q and q:IsMajor() and q:IsAlive() and (j == me or pDiplo:HasMet(j)) then
                    if pc:IsDominantOver(j) then dom = dom + 1 end
                end
            end
            print("CULT|" .. i .. "|" .. dom .. "|" .. pc:GetTouristsFrom(me) .. "|" .. pCulMe:GetStaycationers())
        end)
    end
end
print("{SENTINEL}")
""".replace("{SENTINEL}", SENTINEL)
    )


def parse_mentor_state(lines: list[str]) -> dict:
    out: dict = {
        "government": "",
        "faith_per_turn": 0.0,
        "techs": set(),
        "civics": set(),
        "alive_majors": 0,
        "cities": [],
        "units": [],
        "camps_seen": [],
        "camps_gone": [],
        "religion": {},  # pid -> (name, civs_converted)
        "culture": {},  # pid -> (civs_dominated, their_tourists_from_us, our_staycationers)
        "warnings": [],
        "era_countdown": 0,
        "age": "",
        "luxuries": {},
        "research": {},  # "tech" / "civic" -> {item, progress, cost, boosted, boost_pct, trigger}
        "governors": {},
        "has_pantheon": False,
        "unplaced_districts": [],
    }
    for line in lines:
        p = line.split("|")
        tag = p[0]
        try:
            if tag == "ERA":
                out["era_countdown"] = max(0, int(p[1]))
                out["age"] = p[2]
            elif tag == "RESEARCH" and len(p) >= 8:
                out["research"][p[1]] = {
                    "item": p[2],
                    "progress": float(p[3]),
                    "cost": float(p[4]),
                    "boosted": p[5] == "1",
                    "boost_pct": int(float(p[6])),
                    "trigger": p[7],
                }
            elif tag == "GOVCAN":
                out["governors"] = {"can_appoint": p[1] == "1", "can_promote": p[2] == "1", "unassigned": int(p[3])}
            elif tag == "PANTHEON":
                out["has_pantheon"] = p[1] == "1"
            elif tag == "DISTUNLOCK":
                out["unplaced_districts"].append({"district": p[1], "cost": int(p[2]), "city": p[3]})
            elif tag == "LUXHELD":
                for item in p[1].split(";"):
                    if "=" in item:
                        k, v = item.split("=", 1)
                        out["luxuries"][k] = int(v)
            elif tag == "GOV":
                out["government"] = p[1]
            elif tag == "FAITHPT":
                out["faith_per_turn"] = float(p[1])
            elif tag == "TECHS":
                out["techs"] = {t for t in p[1].split(";") if t}
            elif tag == "CIVICS":
                out["civics"] = {t for t in p[1].split(";") if t}
            elif tag == "MAJORS":
                out["alive_majors"] = int(p[1])
            elif tag == "CITY" and len(p) >= 20:
                out["cities"].append(
                    {
                        "city_id": int(p[1]),
                        "name": p[2],
                        "x": int(p[3]),
                        "y": int(p[4]),
                        "population": int(p[5]),
                        "amenities": int(float(p[6])),
                        "amenities_needed": int(float(p[7])),
                        "housing": float(p[8]),
                        "loyalty": float(p[9]),
                        "loyalty_per_turn": float(p[10]),
                        "production": float(p[11]),
                        "currently_building": p[12],
                        "production_turns_left": int(p[13]),
                        "specialty_districts": int(p[14]),
                        "has_governor": p[15] == "1",
                        "is_capital": p[16] == "1",
                        "has_garrison": p[17] == "1",
                        "districts": [d for d in p[18].split(";") if d],
                        "buildings": [b for b in p[19].split(";") if b],
                    }
                )
            elif tag == "UNIT" and len(p) >= 11:
                dist = int(p[9])
                out["units"].append(
                    {
                        "unit_id": int(p[1]),
                        "unit_type": p[2],
                        "x": int(p[3]),
                        "y": int(p[4]),
                        "moves_remaining": float(p[5]),
                        "health": int(p[6]),
                        "is_civilian": p[7] == "1",
                        "is_recon": p[8] == "1",
                        "threat_distance": dist if dist >= 0 else None,
                        "threat_desc": p[10],
                    }
                )
            elif tag == "CAMPSEEN":
                out["camps_seen"].append((int(p[1]), int(p[2]), int(p[3])))
            elif tag == "CAMPGONE":
                out["camps_gone"].append((int(p[1]), int(p[2])))
            elif tag == "REL":
                out["religion"][int(p[1])] = (p[2], int(p[3]))
            elif tag == "CULT":
                out["culture"][int(p[1])] = (int(p[2]), int(p[3]), int(p[4]))
            elif tag == "WARN":
                out["warnings"].append(p[1])
        except (ValueError, IndexError):
            out["warnings"].append(f"unparsed: {line[:120]}")
    return out


# ---------------------------------------------------------------------------
# Tiles
# ---------------------------------------------------------------------------

TILE_SCOPES = ("area", "city", "empire", "revealed")


def build_tiles_query(
    scope: str,
    x: int = 0,
    y: int = 0,
    radius: int = 2,
    city_id: int = -1,
    resource: str = "",
    improvement: str = "",
) -> str:
    """Revealed plots in a scope, optionally narrowed by resource/improvement.

    scope: area (x, y, radius) | city (its purchased plots) | empire (plots we
    own) | revealed (every revealed plot — use with a resource/improvement
    filter, the output is otherwise very large).
    """
    if scope not in TILE_SCOPES:
        raise ValueError(f"scope must be one of {TILE_SCOPES}")
    return (
        _LUA_PRELUDE
        + f"""
local scope, cx, cy, r, cityId = "{scope}", {x}, {y}, {radius}, {city_id}
local wantRes, wantImp = "{resource}", "{improvement}"
local plots = {{}}
if scope == "area" then
    for dy = -r, r do for dx = -r, r do
        local plot = Map.GetPlot(cx + dx, cy + dy)
        if plot and Map.GetPlotDistance(cx, cy, plot:GetX(), plot:GetY()) <= r then table.insert(plots, plot:GetIndex()) end
    end end
elseif scope == "city" then
    local c = CityManager.GetCity(me, cityId % 65536)
    if c == nil then print("ERR:CITY_NOT_FOUND"); print("{SENTINEL}"); return end
    for _, idx in ipairs(Map.GetCityPlots():GetPurchasedPlots(c)) do table.insert(plots, idx) end
else
    for idx = 0, Map.GetPlotCount() - 1 do
        local plot = Map.GetPlotByIndex(idx)
        if scope == "revealed" or plot:GetOwner() == me then table.insert(plots, idx) end
    end
end
for _, idx in ipairs(plots) do
    if vis:IsRevealed(idx) then
        local plot = Map.GetPlotByIndex(idx)
        local visible = vis:IsVisible(idx)
        local terrain = GameInfo.Terrains[plot:GetTerrainType()].TerrainType
        local res, resClass = "", ""
        local ri = plot:GetResourceType()
        if ri >= 0 then
            local row = GameInfo.Resources[ri]
            if row and resVisible(row) then res, resClass = row.ResourceType, (row.ResourceClassType or "") end
        end
        local feature, imp, pill, dist, ownerId, ownerName, cityOf, worked, road, appeal = "", "", "0", "", -1, "", -1, "0", "0", ""
        if visible then
            local fi = plot:GetFeatureType()
            if fi >= 0 then feature = GameInfo.Features[fi].FeatureType end
            local ii = plot:GetImprovementType()
            if ii >= 0 then
                imp = GameInfo.Improvements[ii].ImprovementType
                if plot:IsImprovementPillaged() then pill = "1" end
            end
            local di = plot:GetDistrictType()
            if di >= 0 then dist = GameInfo.Districts[di].DistrictType end
            ownerId = plot:GetOwner()
            if ownerId == me then ownerName = "me"
            elseif ownerId >= 0 and pDiplo:HasMet(ownerId) then
                ownerName = clean(Locale.Lookup(PlayerConfigurations[ownerId]:GetCivilizationShortDescription()))
            elseif ownerId >= 0 then ownerName = "unmet" end
            if ownerId == me then
                pcall(function()
                    local oc = Cities.GetPlotPurchaseCity(plot)
                    if oc then cityOf = oc:GetID() end
                end)
                pcall(function() if plot:GetWorkerCount() > 0 then worked = "1" end end)
            end
            pcall(function() if plot:GetRouteType() >= 0 then road = "1" end end)
            pcall(function() appeal = tostring(plot:GetAppeal()) end)
        end
        local keep = true
        if wantRes ~= "" and res ~= wantRes then keep = false end
        if wantImp ~= "" and imp ~= wantImp then keep = false end
        if keep then
            print("TILE|" .. plot:GetX() .. "|" .. plot:GetY() .. "|" .. (visible and "1" or "0") .. "|" .. terrain
                .. "|" .. feature .. "|" .. res .. "|" .. resClass .. "|" .. imp .. "|" .. pill .. "|" .. dist
                .. "|" .. ownerId .. "|" .. ownerName .. "|" .. cityOf .. "|" .. worked .. "|" .. road .. "|" .. appeal)
        end
    end
end
print("{SENTINEL}")
"""
    )


def parse_tiles(lines: list[str]) -> list[dict]:
    rows: list[dict] = []
    for line in lines:
        if line.startswith("ERR:"):
            raise ValueError(line)
        p = line.split("|")
        if p[0] != "TILE" or len(p) < 17:
            continue
        rows.append(
            {
                "x": int(p[1]),
                "y": int(p[2]),
                "revealed": True,  # the query only emits revealed plots
                "visible": p[3] == "1",
                "terrain": p[4],
                "feature": p[5],
                "resource": p[6],
                "resource_class": p[7].replace("RESOURCECLASS_", "").lower(),
                "resource_visible": bool(p[6]),
                "improvement": p[8],
                "pillaged": p[9] == "1",
                "district": p[10],
                "owner_id": int(p[11]),
                "owner": p[12],
                "city_id": int(p[13]),
                "worked": p[14] == "1",
                "has_road": p[15] == "1",
                "appeal": int(p[16]) if p[16] not in ("", "nil") else None,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Amenities, loyalty, housing breakdowns (the city panel's own numbers)
# ---------------------------------------------------------------------------

AMENITY_SOURCES = (
    "Luxuries",
    "Entertainment",
    "Districts",
    "Civics",
    "GreatPeople",
    "CityStates",
    "Religion",
    "NationalParks",
    "NaturalWonders",
    "StartingEra",
    "Improvements",
    "Governors",
    "Traits",
)


def build_city_needs_query(city_id: int) -> str:
    """Amenity, housing and loyalty breakdown for one city, plus the facts the
    fix-it options need: our luxury holdings, unimproved luxury plots and the
    nearest builder to each, and the loyalty pressure breakdown."""
    getters = "\n".join(
        f'pcall(function() print("ASRC|{s}|" .. g:GetAmenitiesFrom{s}()) end)'
        for s in AMENITY_SOURCES
    )
    housing = "\n".join(
        f'pcall(function() print("HSRC|{s}|" .. string.format("%.1f", g:GetHousingFrom{s}())) end)'
        for s in (
            "Buildings",
            "Civics",
            "Districts",
            "GreatPeople",
            "GreatWorks",
            "Improvements",
            "StartingEra",
            "Water",
        )
    )
    return (
        _LUA_PRELUDE
        + f"""
local c = CityManager.GetCity(me, {city_id} % 65536)
if c == nil then print("ERR:CITY_NOT_FOUND"); print("{SENTINEL}"); return end
local g = c:GetGrowth()
print("AMEN|" .. g:GetAmenities() .. "|" .. g:GetAmenitiesNeeded() .. "|" .. c:GetPopulation() .. "|" .. string.format("%.1f", g:GetHousing()))
{getters}
pcall(function() print("ALOST|WarWeariness|" .. g:GetAmenitiesLostFromWarWeariness()) end)
pcall(function() print("ALOST|Bankruptcy|" .. g:GetAmenitiesLostFromBankruptcy()) end)
{housing}

-- Luxury types we hold (copies), and unimproved luxury plots in our borders
for row in GameInfo.Resources() do
    if row.ResourceClassType == "RESOURCECLASS_LUXURY" then
        local n = 0
        pcall(function() n = pRes:GetResourceAmount(row.Index) end)
        if n > 0 then print("LUX|" .. row.ResourceType .. "|" .. n) end
    end
end
local builders = {{}}
for _, u in pMe:GetUnits():Members() do
    local info = GameInfo.Units[u:GetType()]
    if info and info.UnitType == "UNIT_BUILDER" and u:GetX() >= 0 then
        local charges = 0
        pcall(function() charges = u:GetBuildCharges() end)
        if charges > 0 then table.insert(builders, {{id = u:GetID(), x = u:GetX(), y = u:GetY(), moves = info.BaseMoves or 2}}) end
    end
end
for idx = 0, Map.GetPlotCount() - 1 do
    local plot = Map.GetPlotByIndex(idx)
    if plot:GetOwner() == me then
        local ri = plot:GetResourceType()
        if ri >= 0 then
            local row = GameInfo.Resources[ri]
            if row and row.ResourceClassType == "RESOURCECLASS_LUXURY" and resVisible(row)
               and (plot:GetImprovementType() < 0 or plot:IsImprovementPillaged()) and plot:GetDistrictType() < 0 then
                local bestD, bestId, bestMoves = -1, -1, 2
                for _, b in ipairs(builders) do
                    local d = Map.GetPlotDistance(b.x, b.y, plot:GetX(), plot:GetY())
                    if bestD < 0 or d < bestD then bestD, bestId, bestMoves = d, b.id, b.moves end
                end
                print("UNIMPLUX|" .. row.ResourceType .. "|" .. plot:GetX() .. "|" .. plot:GetY() .. "|"
                    .. (plot:IsImprovementPillaged() and "1" or "0") .. "|" .. bestId .. "|" .. bestD .. "|" .. bestMoves)
            end
        end
    end
end

-- Loyalty: the culture panel's breakdown
pcall(function()
    local ci = c:GetCulturalIdentity()
    print("LOY|" .. string.format("%.1f|%.1f", ci:GetLoyalty(), ci:GetLoyaltyPerTurn()) .. "|" .. ci:GetTurnsToConversion())
    for _, inner in ipairs(ci:GetIdentitySourcesDetailedBreakdown()) do
        local src, val = next(inner)
        print("LSRC|" .. clean(src) .. "|" .. string.format("%.1f", val))
    end
end)
local govHere, govAny = "0", "0"
pcall(function()
    local pGovs = pMe:GetGovernors()
    for row in GameInfo.Governors() do
        if pGovs:HasGovernor(row.Hash) then
            local gv = pGovs:GetGovernor(row.Hash)
            local ac = gv:GetAssignedCity()
            if ac and ac:GetID() == c:GetID() then govHere = "1" end
            if ac == nil then govAny = "1" end
        end
    end
end)
print("GOVS|" .. govHere .. "|" .. govAny)
print("{SENTINEL}")
"""
    )


def parse_city_needs(lines: list[str]) -> dict:
    out: dict = {
        "amenities": 0,
        "amenities_needed": 0,
        "population": 0,
        "housing": 0.0,
        "amenity_sources": {},
        "amenity_losses": {},
        "housing_sources": {},
        "luxuries_held": {},
        "unimproved_luxuries": [],
        "loyalty": None,
        "loyalty_per_turn": None,
        "turns_to_conversion": None,
        "loyalty_sources": [],
        "governor_here": False,
        "unassigned_governor": False,
    }
    for line in lines:
        if line.startswith("ERR:"):
            raise ValueError(line)
        p = line.split("|")
        try:
            if p[0] == "AMEN":
                out["amenities"] = int(float(p[1]))
                out["amenities_needed"] = int(float(p[2]))
                out["population"] = int(p[3])
                out["housing"] = float(p[4])
            elif p[0] == "ASRC":
                out["amenity_sources"][p[1]] = int(float(p[2]))
            elif p[0] == "ALOST":
                out["amenity_losses"][p[1]] = int(float(p[2]))
            elif p[0] == "HSRC":
                out["housing_sources"][p[1]] = float(p[2])
            elif p[0] == "LUX":
                out["luxuries_held"][p[1]] = int(p[2])
            elif p[0] == "UNIMPLUX":
                out["unimproved_luxuries"].append(
                    {
                        "resource": p[1],
                        "x": int(p[2]),
                        "y": int(p[3]),
                        "pillaged": p[4] == "1",
                        "builder_id": int(p[5]),
                        "builder_distance": int(p[6]),
                        "builder_moves": int(p[7]),
                    }
                )
            elif p[0] == "LOY":
                out["loyalty"] = float(p[1])
                out["loyalty_per_turn"] = float(p[2])
                out["turns_to_conversion"] = int(p[3])
            elif p[0] == "LSRC":
                out["loyalty_sources"].append((p[1], float(p[2])))
            elif p[0] == "GOVS":
                out["governor_here"] = p[1] == "1"
                out["unassigned_governor"] = p[2] == "1"
        except (ValueError, IndexError):
            continue
    return out


# ---------------------------------------------------------------------------
# National parks — the engine's own rule check
# ---------------------------------------------------------------------------


def build_park_sites_query() -> str:
    """Plots where a Naturalist could designate a park right now.

    Uses Game.GetNationalParks():GetPossibleParkTiles(me), the same call the
    game's SelectedUnit_Expansion2.lua uses to highlight park plots, so the
    rule (shape, borders, appeal, no improvements/districts) is the engine's,
    not a reimplementation.
    """
    return (
        _LUA_PRELUDE
        + """
local ok, plots = pcall(function() return Game.GetNationalParks():GetPossibleParkTiles(me) end)
if not ok or plots == nil then print("ERR:NO_PARK_API"); print("{SENTINEL}"); return end
for _, idx in ipairs(plots) do
    if vis:IsRevealed(idx) then
        local plot = Map.GetPlotByIndex(idx)
        local appeal = ""
        pcall(function() appeal = tostring(plot:GetAppeal()) end)
        local cityName, cityId = "", -1
        pcall(function()
            local oc = Cities.GetPlotPurchaseCity(plot)
            if oc then cityName, cityId = clean(Locale.Lookup(oc:GetName())), oc:GetID() end
        end)
        print("PARK|" .. plot:GetX() .. "|" .. plot:GetY() .. "|" .. appeal .. "|" .. cityId .. "|" .. cityName)
    end
end
print("{SENTINEL}")
""".replace("{SENTINEL}", SENTINEL)
    )


def parse_park_sites(lines: list[str]) -> list[dict]:
    rows = []
    for line in lines:
        if line.startswith("ERR:"):
            raise ValueError(line)
        p = line.split("|")
        if p[0] == "PARK" and len(p) >= 6:
            rows.append(
                {
                    "x": int(p[1]),
                    "y": int(p[2]),
                    "appeal": int(p[3]) if p[3] else None,
                    "city_id": int(p[4]),
                    "city": p[5],
                }
            )
    return rows


# ---------------------------------------------------------------------------
# In-game UI: highlights, pins, camera, alert panel
# ---------------------------------------------------------------------------

# The layers WorldInput.lua draws outside any modal lens: ToggleLayerOn, then
# SetLayerHexesArea (WorldInput.lua:2104-2105, 2444-2445). Each layer has its
# own built-in style, so "color" picks a layer rather than an RGB value.
# (Lens layers such as Hex_Coloring_Great_People or the appeal layer only draw
# while their lens is active, and the lens repaints them — a live test showed
# nothing on screen.)
HIGHLIGHT_LAYERS = {
    "green": "Hex_Coloring_Movement",
    "teal": "Hex_Coloring_Movement",
    "grey": "Hex_Coloring_Movement",
    "red": "Hex_Coloring_Attack",
}
_ALL_HIGHLIGHT_LAYERS = sorted(set(HIGHLIGHT_LAYERS.values()))


def _lua_clear_highlight_layers() -> str:
    return "\n".join(
        f'UILens.ToggleLayerOff(UILens.CreateLensLayerHash("{n}")); UILens.ClearLayerHexes(UILens.CreateLensLayerHash("{n}"))'
        for n in _ALL_HIGHLIGHT_LAYERS
    )


def build_highlight_query(
    tiles: list[tuple[int, int]],
    color: str = "green",
    look_at: bool = True,
) -> str:
    layer_name = HIGHLIGHT_LAYERS.get(color, HIGHLIGHT_LAYERS["green"])
    coords = "{" + ",".join(f"{{{x},{y}}}" for x, y in tiles) + "}"
    return f"""
local me = Game.GetLocalPlayer()
local idxs = {{}}
for _, xy in ipairs({coords}) do
    local plot = Map.GetPlot(xy[1], xy[2])
    if plot and PlayersVisibility[me]:IsRevealed(plot:GetIndex()) then table.insert(idxs, plot:GetIndex()) end
end
{_lua_clear_highlight_layers()}
if #idxs > 0 then
    local layer = UILens.CreateLensLayerHash("{layer_name}")
    UILens.ToggleLayerOn(layer)
    UILens.SetLayerHexesArea(layer, me, idxs)
end
ExposedMembers.Chancellor_Highlight = true
{"if #idxs > 0 then local p = Map.GetPlotByIndex(idxs[1]); UI.LookAtPlot(p:GetX(), p:GetY()) end" if look_at else ""}
print("HIGHLIGHTED|" .. #idxs)
print("{SENTINEL}")
"""


def build_clear_highlights_query() -> str:
    return f"""
{_lua_clear_highlight_layers()}
ExposedMembers.Chancellor_Highlight = nil
print("CLEARED")
print("{SENTINEL}")
"""


PIN_PREFIX = "[Vizier] "


def icon_candidates(icon: str) -> list[str]:
    """'commercial hub' → DISTRICT_COMMERCIAL_HUB, IMPROVEMENT_…, BUILDING_…, UNIT_…;
    a full type name is tried as given."""
    t = icon.strip().upper().replace(" ", "_").replace("-", "_")
    if not t:
        return []
    if t.split("_", 1)[0] in ("DISTRICT", "IMPROVEMENT", "BUILDING", "UNIT"):
        return [t]
    return [f"{p}_{t}" for p in ("DISTRICT", "IMPROVEMENT", "BUILDING", "UNIT")]


def build_add_pin_query(x: int, y: int, label: str, icon: str = "") -> str:
    """Create or update a map pin the way MapPinPopup.lua does (private pin).

    icon: a district/improvement/building/unit type or plain name. The icon
    name follows MapTacks.lua: "ICON_" .. DistrictType / BuildingType /
    UnitType, and Improvements.Icon for improvements. Prints the resolved
    type, or ICON_UNKNOWN if none matched (the pin is still placed).
    """
    safe = label.replace("\\", "").replace('"', "'")[:60]
    cands = _lua_str_list(icon_candidates(icon))
    return f"""
local me = Game.GetLocalPlayer()
local cfg = PlayerConfigurations[me]
local iconName, iconType = nil, ""
for _, t in ipairs({cands}) do
    if iconName == nil then
        if GameInfo.Districts[t] then iconName, iconType = "ICON_" .. t, t
        elseif GameInfo.Improvements[t] then iconName, iconType = GameInfo.Improvements[t].Icon, t
        elseif GameInfo.Buildings[t] then iconName, iconType = "ICON_" .. t, t
        elseif GameInfo.Units[t] then iconName, iconType = "ICON_" .. t, t end
    end
end
local pin = cfg:GetMapPin({x}, {y})
if pin == nil then print("ERR:PIN_FAILED"); print("{SENTINEL}"); return end
pin:SetName("{PIN_PREFIX}{safe}")
if iconName then pin:SetIconName(iconName) end
Network.BroadcastPlayerInfo()
print("PIN|" .. pin:GetID() .. "|" .. (iconType ~= "" and iconType or "{"ICON_UNKNOWN" if icon else ""}"))
print("{SENTINEL}")
"""


def build_clear_pins_query() -> str:
    """Delete only the pins Vizier placed (name starts with the prefix)."""
    return f"""
local me = Game.GetLocalPlayer()
local cfg = PlayerConfigurations[me]
local doomed = {{}}
local pins = cfg:GetMapPins()
if pins then
    for _, p in pairs(pins) do
        local n = p:GetName() or ""
        if string.sub(n, 1, {len(PIN_PREFIX)}) == "{PIN_PREFIX}" then table.insert(doomed, p:GetID()) end
    end
end
for _, id in ipairs(doomed) do cfg:DeleteMapPin(id) end
if #doomed > 0 then Network.BroadcastPlayerInfo() end
print("PINS_REMOVED|" .. #doomed)
print("{SENTINEL}")
"""


def build_push_alerts_query(turn: int, alerts: list[tuple[str, str, str]]) -> str:
    """Publish the top alerts to the ChancellorAlerts mod panel.

    ExposedMembers is shared across UI contexts; the mod reads it on
    Chancellor_AlertsUpdated and on LocalPlayerTurnBegin. Harmless if the mod
    isn't installed.
    """

    def esc(s: str) -> str:
        return s.replace("\\", "").replace('"', "'").replace("\n", " ")[:160]

    items = ",".join(
        f'{{severity="{esc(sev)}", title="{esc(title)}", detail="{esc(detail)}"}}'
        for sev, title, detail in alerts
    )
    return f"""
ExposedMembers.Chancellor = ExposedMembers.Chancellor or {{}}
ExposedMembers.Chancellor.turn = {turn}
ExposedMembers.Chancellor.alerts = {{{items}}}
pcall(function() LuaEvents.Chancellor_AlertsUpdated() end)
print("PUSHED|{len(alerts)}")
print("{SENTINEL}")
"""


def build_turn_seq_query() -> str:
    """Read the mod's turn-start counter (nil if the mod isn't running)."""
    return f"""
local seq = ExposedMembers.Chancellor_TurnSeq
print("SEQ|" .. tostring(seq))
print("{SENTINEL}")
"""



# ---------------------------------------------------------------------------
# Identity, empire overview, rivals, trade, policies (adapted from civ6-mcp)
# ---------------------------------------------------------------------------


def build_identity_query() -> str:
    """(civ type, map seed): keys per-game storage so games never mix."""
    return f"""
local cfg = PlayerConfigurations[Game.GetLocalPlayer()]
print("GAMESEED|" .. cfg:GetCivilizationTypeName() .. "|" .. tostring(GameConfiguration.GetValue("GAME_SYNC_RANDOM_SEED")))
print("{SENTINEL}")
"""


def parse_identity(lines: list[str]) -> tuple[str, int]:
    for line in lines:
        if line.startswith("GAMESEED|"):
            _, civ, seed = line.split("|", 2)
            try:
                return civ.replace("CIVILIZATION_", "").lower(), int(float(seed))
            except ValueError:
                return civ.replace("CIVILIZATION_", "").lower(), 0
    return "unknown", 0


def build_empire_query() -> str:
    """Overview, met rivals' visible victory/diplomacy facts, trade and policies."""
    return (
        _LUA_PRELUDE
        + """
local cfg = PlayerConfigurations[me]
local tr = pMe:GetTreasury()
local cu = pMe:GetCulture()

-- Diplomatic favor per turn, as civ6-mcp estimates it: government tier,
-- alliance levels and suzerainties (the game exposes no direct getter).
local favorPT = 0
pcall(function()
    local g = GameInfo.Governments[cu:GetCurrentGovernment()]
    if g and g.Tier then favorPT = favorPT + math.max(1, tonumber(tostring(g.Tier):match("(%d+)$")) or 0) end
end)
for i = 0, 62 do
    local p = Players[i]
    if p and p:IsAlive() then
        if i ~= me and p:IsMajor() and pDiplo:HasMet(i) then
            pcall(function()
                if p:GetDiplomaticAI():GetDiplomaticStateIndex(me) == 0 then
                    favorPT = favorPT + (tonumber(pDiplo:GetAllianceLevel(i)) or 1)
                end
            end)
        end
        pcall(function()
            local inf = p:GetInfluence()
            if inf:CanReceiveInfluence() and inf:GetSuzerain() == me then favorPT = favorPT + 1 end
        end)
    end
end
print("OV|" .. Game.GetCurrentGameTurn() .. "|" .. me .. "|" .. clean(Locale.Lookup(cfg:GetCivilizationShortDescription()))
    .. "|" .. clean(Locale.Lookup(cfg:GetLeaderName())) .. "|" .. string.format("%.1f", tr:GetGoldBalance())
    .. "|" .. string.format("%.1f", tr:GetGoldYield() - tr:GetTotalMaintenance())
    .. "|" .. string.format("%.1f", pMe:GetTechs():GetScienceYield()) .. "|" .. string.format("%.1f", cu:GetCultureYield())
    .. "|" .. string.format("%.1f", pMe:GetReligion():GetFaithBalance()) .. "|" .. (pMe:GetFavor() or 0) .. "|" .. favorPT)

-- Land explored
local revLand, totalLand = 0, 0
for i = 0, Map.GetPlotCount() - 1 do
    local plot = Map.GetPlotByIndex(i)
    if not plot:IsWater() then
        totalLand = totalLand + 1
        if vis:IsRevealed(i) then revLand = revLand + 1 end
    end
end
print("EXPLORE|" .. revLand .. "|" .. totalLand)

-- Religion slots (counts every major — the game shows "X of Y founded")
local nMajors, nRel = 0, 0
for i = 0, 62 do
    local p = Players[i]
    if p and p:IsMajor() and p:IsAlive() then
        nMajors = nMajors + 1
        local r = p:GetReligion():GetReligionTypeCreated()
        if r and r >= 0 then
            nRel = nRel + 1
            if i == me then
                local row = GameInfo.Religions[r]
                print("OURREL|" .. (row and clean(Locale.Lookup(row.Name)) or "?"))
            end
        end
    end
end
print("RELSLOTS|" .. nRel .. "|" .. (math.floor(nMajors / 2) + 1))

-- Era score
pcall(function()
    local eras = Game.GetEras()
    local row = GameInfo.Eras[eras:GetCurrentEra()]
    print("ERASCORE|" .. (row and clean(Locale.Lookup(row.Name)) or "?") .. "|" .. eras:GetPlayerCurrentScore(me)
        .. "|" .. eras:GetPlayerDarkAgeThreshold(me) .. "|" .. eras:GetPlayerGoldenAgeThreshold(me))
end)

-- Difficulty, speed, victories
pcall(function()
    local h = cfg:GetHandicapTypeID()
    for d in GameInfo.Difficulties() do
        if GameConfiguration.MakeHash(d.DifficultyType) == h then print("DIFF|" .. clean(Locale.Lookup(d.Name))); break end
    end
end)
pcall(function()
    local gs = GameInfo.GameSpeeds[Game.GetGameSpeedType()]
    if gs then print("SPEED|" .. (gs.CostMultiplier or 100)) end
end)
local ven = {}
for _, vt in ipairs({"VICTORY_TECHNOLOGY", "VICTORY_CONQUEST", "VICTORY_CULTURE", "VICTORY_RELIGIOUS", "VICTORY_DIPLOMATIC", "VICTORY_SCORE"}) do
    local row = GameInfo.Victories[vt]
    if row then
        local ok, en = pcall(function() return Game.IsVictoryEnabled(row.Index) end)
        if ok and en then table.insert(ven, vt) end
    end
end
print("VENABLED|" .. table.concat(ven, ";"))

-- Our victory stats, then met rivals' (the World Rankings screen shows these)
local function stats(p)
    local st = p:GetStats()
    local mil, svp, sneed, dvp, tour = 0, 0, 0, 0, 0
    pcall(function() mil = st:GetMilitaryStrength() end)
    pcall(function() svp = st:GetScienceVictoryPoints() end)
    pcall(function() sneed = st:GetScienceVictoryPointsTotalNeeded() end)
    pcall(function() dvp = st:GetDiplomaticVictoryPoints() end)
    pcall(function() tour = st:GetTourism() end)
    return mil .. "|" .. svp .. "|" .. sneed .. "|" .. dvp .. "|" .. tour
end
print("ME|" .. stats(pMe))
local states = {"ALLIED", "DECLARED_FRIEND", "FRIENDLY", "NEUTRAL", "UNFRIENDLY", "DENOUNCED", "WAR"}
for i = 0, 62 do
    local p = Players[i]
    if i ~= me and p and p:IsMajor() and p:IsAlive() and pDiplo:HasMet(i) then
        pcall(function()
            local state = "UNKNOWN"
            pcall(function() state = states[p:GetDiplomaticAI():GetDiplomaticStateIndex(me) + 1] or "UNKNOWN" end)
            local acts = {}
            for _, a in ipairs({"DIPLOACTION_DECLARE_FRIENDSHIP", "DIPLOACTION_MAKE_ALLIANCE"}) do
                local ok, v = pcall(function() return pDiplo:IsDiplomaticActionValid(a, i, false) end)
                if ok and v then table.insert(acts, (a:gsub("DIPLOACTION_", ""))) end
            end
            local allied = "0"
            pcall(function() if pDiplo:GetAllianceType(i) >= 0 then allied = "1" end end)
            local nC = 0
            for _ in p:GetCities():Members() do nC = nC + 1 end
            print("RIVAL|" .. i .. "|" .. clean(Locale.Lookup(PlayerConfigurations[i]:GetCivilizationShortDescription()))
                .. "|" .. p:GetScore() .. "|" .. nC .. "|" .. stats(p)
                .. "|" .. (p:GetReligion():GetReligionTypeCreated() >= 0 and "1" or "0")
                .. "|" .. state .. "|" .. (pDiplo:IsAtWarWith(i) and "1" or "0")
                .. "|" .. (pDiplo:HasDelegationAt(i) and "1" or "0") .. "|" .. (pDiplo:HasEmbassyAt(i) and "1" or "0")
                .. "|" .. table.concat(acts, ";") .. "|" .. allied)
        end)
    end
end

-- Trade: capacity, active routes, and "ghost" routes whose trader is gone
pcall(function()
    local traders = {}
    for _, u in pMe:GetUnits():Members() do
        local info = GameInfo.Units[u:GetType()]
        if info and info.UnitType == "UNIT_TRADER" then traders[u:GetID()] = true end
    end
    local seen, active, ghosts = {}, 0, 0
    for _, c in pMe:GetCities():Members() do
        pcall(function()
            for _, r in ipairs(c:GetTrade():GetOutgoingRoutes() or {}) do
                local key = r.TraderUnitID .. "_" .. r.DestinationCityPlayer .. "_" .. r.DestinationCityID
                if not seen[key] then
                    seen[key] = true
                    if traders[r.TraderUnitID] then active = active + 1 else ghosts = ghosts + 1 end
                end
            end
        end)
    end
    print("TRADE|" .. pMe:GetTrade():GetOutgoingRouteCapacity() .. "|" .. active .. "|" .. ghosts)
end)
"""
        + _LUA_POLICIES
        + """
print("{SENTINEL}")
""".replace("{SENTINEL}", SENTINEL)
    )


# Slotted and slot-able policies (shared by the empire and policies queries).
_LUA_POLICIES = """
pcall(function()
    local cu = pMe:GetCulture()
    local n = cu:GetNumPolicySlots()
    local slotNames = {[0] = "SLOT_ECONOMIC", [1] = "SLOT_MILITARY", [2] = "SLOT_DIPLOMATIC", [3] = "SLOT_WILDCARD", [4] = "SLOT_WILDCARD"}
    for sIdx = 0, n - 1 do
        local pi = cu:GetSlotPolicy(sIdx)
        local pt = (pi and pi >= 0 and GameInfo.Policies[pi]) and GameInfo.Policies[pi].PolicyType or ""
        print("PSLOT|" .. sIdx .. "|" .. (slotNames[cu:GetSlotType(sIdx)] or "SLOT_OTHER") .. "|" .. pt)
    end
    for pol in GameInfo.Policies() do
        if cu:IsPolicyUnlocked(pol.Index) then
            for sIdx = 0, n - 1 do
                if cu:CanSlotPolicy(pol.Index, sIdx) then
                    print("PAVAIL|" .. pol.PolicyType .. "|" .. clean(Locale.Lookup(pol.Name)) .. "|" .. (pol.GovernmentSlotType or "SLOT_WILDCARD"))
                    break
                end
            end
        end
    end
end)
"""


def parse_empire(lines: list[str]) -> dict:
    out: dict = {
        "overview": {},
        "explored": (0, 0),
        "our_religion": "",
        "religions": (0, 0),
        "era": ("", 0, 0, 0),
        "difficulty": "",
        "speed_multiplier": 100,
        "enabled_victories": set(),
        "me": {},
        "rivals": [],
        "trade": (0, 0, 0),
        "policies": parse_policies(lines),
    }

    def stats(parts: list[str]) -> dict:
        return {
            "military_strength": int(float(parts[0])),
            "science_vp": int(float(parts[1])),
            "science_vp_needed": int(float(parts[2])),
            "diplomatic_vp": int(float(parts[3])),
            "tourism": int(float(parts[4])),
        }

    for line in lines:
        p = line.split("|")
        try:
            if p[0] == "OV" and len(p) >= 12:
                out["overview"] = {
                    "turn": int(p[1]),
                    "player_id": int(p[2]),
                    "civ": p[3],
                    "leader": p[4],
                    "gold": float(p[5]),
                    "gold_per_turn": float(p[6]),
                    "science_per_turn": float(p[7]),
                    "culture_per_turn": float(p[8]),
                    "faith": float(p[9]),
                    "favor": int(float(p[10])),
                    "favor_per_turn": int(float(p[11])),
                }
            elif p[0] == "EXPLORE":
                out["explored"] = (int(p[1]), int(p[2]))
            elif p[0] == "OURREL":
                out["our_religion"] = p[1]
            elif p[0] == "RELSLOTS":
                out["religions"] = (int(p[1]), int(p[2]))
            elif p[0] == "ERASCORE":
                out["era"] = (p[1], int(p[2]), int(p[3]), int(p[4]))
            elif p[0] == "DIFF":
                out["difficulty"] = p[1]
            elif p[0] == "SPEED":
                out["speed_multiplier"] = int(float(p[1]))
            elif p[0] == "VENABLED":
                out["enabled_victories"] = {v for v in p[1].split(";") if v}
            elif p[0] == "ME" and len(p) >= 6:
                out["me"] = stats(p[1:6])
            elif p[0] == "RIVAL" and len(p) >= 17:
                acts = set(p[15].split(";")) if p[15] else set()
                out["rivals"].append(
                    {
                        "player_id": int(p[1]),
                        "name": p[2],
                        "score": int(float(p[3])),
                        "num_cities": int(p[4]),
                        **stats(p[5:10]),
                        "has_religion": p[10] == "1",
                        "diplomatic_state": p[11],
                        "at_war": p[12] == "1",
                        "we_have_delegation": p[13] == "1",
                        "we_have_embassy": p[14] == "1",
                        "can_declare_friendship": "DECLARE_FRIENDSHIP" in acts,
                        "can_form_alliance": "MAKE_ALLIANCE" in acts,
                        "is_friend": p[11] == "DECLARED_FRIEND",
                        "is_ally": p[16] == "1" or p[11] == "ALLIED",
                    }
                )
            elif p[0] == "TRADE":
                out["trade"] = (int(p[1]), int(p[2]), int(p[3]))
        except (ValueError, IndexError):
            continue
    return out


def build_policies_query() -> str:
    return _LUA_PRELUDE + _LUA_POLICIES + f'\nprint("{SENTINEL}")\n'


def parse_policies(lines: list[str]) -> dict:
    slots, available = [], []
    for line in lines:
        p = line.split("|")
        if p[0] == "PSLOT" and len(p) >= 4:
            slots.append({"slot_index": int(p[1]), "slot_type": p[2], "current_policy": p[3] or None})
        elif p[0] == "PAVAIL" and len(p) >= 4:
            available.append({"policy_type": p[1], "name": p[2], "slot_type": p[3]})
    return {"slots": slots, "available": available}


def build_production_query(city_id: int) -> str:
    """What a city can make now: production cost, turns and gold cost (-1 = can't buy)."""
    return (
        _LUA_PRELUDE
        + f"""
local c = CityManager.GetCity(me, {city_id} % 65536)
if c == nil then print("ERR:CITY_NOT_FOUND"); print("{SENTINEL}"); return end
local bq = c:GetBuildQueue()
local goldIdx = GameInfo.Yields["YIELD_GOLD"].Index
local cg = c:GetGold()
local function goldCost(hash, isUnit)
    local ok, v = pcall(function()
        if isUnit then return cg:GetPurchaseCost(goldIdx, hash, MilitaryFormationTypes.STANDARD_MILITARY_FORMATION) end
        return cg:GetPurchaseCost(goldIdx, hash, -1)
    end)
    if ok and v and v > 0 then return math.floor(v) end
    return -1
end
local function cost(row)
    local v = row.Cost or 0
    pcall(function() local x = bq:GetProductionCost(row.Hash); if x and x > 0 then v = math.floor(x) end end)
    return v
end
local function emit(cat, typ, row, gold)
    print("OPT|" .. cat .. "|" .. typ .. "|" .. cost(row) .. "|" .. bq:GetTurnsLeft(row.Hash) .. "|" .. gold)
end
for row in GameInfo.Units() do
    if bq:CanProduce(row.Hash, true) then emit("UNIT", row.UnitType, row, goldCost(row.Hash, true)) end
end
for row in GameInfo.Buildings() do
    if bq:CanProduce(row.Hash, true) then emit("BUILDING", row.BuildingType, row, row.IsWonder and -1 or goldCost(row.Hash, false)) end
end
for row in GameInfo.Districts() do
    if bq:CanProduce(row.Hash, true) then emit("DISTRICT", row.DistrictType, row, -1) end
end
for row in GameInfo.Projects() do
    if bq:CanProduce(row.Hash, true) then emit("PROJECT", row.ProjectType, row, -1) end
end
print("{SENTINEL}")
"""
    )


def parse_production(lines: list[str]) -> list[dict]:
    out = []
    for line in lines:
        if line.startswith("ERR:"):
            raise ValueError(line)
        p = line.split("|")
        if p[0] == "OPT" and len(p) >= 6:
            try:
                out.append(
                    {
                        "category": p[1],
                        "item_name": p[2],
                        "cost": int(float(p[3])),
                        "turns": int(float(p[4])),
                        "gold_cost": int(float(p[5])),
                        "is_repair": False,
                    }
                )
            except ValueError:
                continue
    return out


# ---------------------------------------------------------------------------
# Settle spots
# ---------------------------------------------------------------------------


def build_settle_query(limit: int = 5, max_distance: int = 9) -> str:
    """Score revealed, legal city sites near the empire.

    Legality: Players[me]:GetCities():IsValidFoundLocation(x, y) when the
    context offers it, else the 4-tile city spacing rule (GlobalParameters
    CITY_MIN_RANGE = 3). Only revealed plots count, resources only if visible.
    The game's own recommendations (GetGrandStrategicAI():
    GetSettlementRecommendations, the settler icons in WorldViewIconsManager.lua)
    are flagged.
    """
    return (
        _LUA_PRELUDE
        + f"""
local LIMIT, MAXD = {limit}, {max_distance}
local anchors = {{}}
for _, c in pMe:GetCities():Members() do table.insert(anchors, {{x = c:GetX(), y = c:GetY()}}) end
if #anchors == 0 then
    for _, u in pMe:GetUnits():Members() do
        local info = GameInfo.Units[u:GetType()]
        if info and info.UnitType == "UNIT_SETTLER" and u:GetX() >= 0 then table.insert(anchors, {{x = u:GetX(), y = u:GetY()}}) end
    end
end
if #anchors == 0 then print("ERR:NO_CITY_OR_SETTLER"); print("{SENTINEL}"); return end

-- Every visible city (any owner) for spacing when IsValidFoundLocation isn't available
local seenCities = {{}}
for i = 0, 63 do
    local p = Players[i]
    if p and p:IsAlive() then
        for _, c in p:GetCities():Members() do
            if vis:IsRevealed(c:GetX(), c:GetY()) then table.insert(seenCities, {{x = c:GetX(), y = c:GetY()}}) end
        end
    end
end
local pCities = pMe:GetCities()
local function legal(plot)
    local ok, v = pcall(function() return pCities:IsValidFoundLocation(plot:GetX(), plot:GetY()) end)
    if ok and v ~= nil then return v end
    for _, c in ipairs(seenCities) do
        if Map.GetPlotDistance(plot:GetX(), plot:GetY(), c.x, c.y) < 4 then return false end
    end
    return true
end

local recommended = {{}}
pcall(function()
    for _, r in pairs(pMe:GetGrandStrategicAI():GetSettlementRecommendations(5)) do
        recommended[r.SettlingLocation] = true
    end
end)

-- Luxury types we already have: held copies, plus any in our borders even if
-- not improved yet (a second site with the same type adds no new amenity)
local luxSeen = {{}}
for row in GameInfo.Resources() do
    if row.ResourceClassType == "RESOURCECLASS_LUXURY" then
        local ok, n = pcall(function() return pRes:GetResourceAmount(row.Index) end)
        if ok and n and n > 0 then luxSeen[row.ResourceType] = true end
    end
end
for idx = 0, Map.GetPlotCount() - 1 do
    local plot = Map.GetPlotByIndex(idx)
    if plot:GetOwner() == me then
        local ri = plot:GetResourceType()
        local row = ri >= 0 and GameInfo.Resources[ri] or nil
        if row and row.ResourceClassType == "RESOURCECLASS_LUXURY" and resVisible(row) then luxSeen[row.ResourceType] = true end
    end
end
-- Campus adjacency per Adjacency_YieldChanges (verified with REA): mountain +1,
-- reef +2, geothermal fissure +2, jungle +1 per 2
local function featureType(q)
    local fi = q:GetFeatureType()
    return fi >= 0 and GameInfo.Features[fi] and GameInfo.Features[fi].FeatureType or ""
end

local candidates = {{}}
for idx = 0, Map.GetPlotCount() - 1 do
    local plot = Map.GetPlotByIndex(idx)
    if vis:IsRevealed(idx) and not plot:IsWater() and not plot:IsMountain() and plot:GetOwner() < 0 then
        local px, py = plot:GetX(), plot:GetY()
        local near = 99
        for _, a in ipairs(anchors) do near = math.min(near, Map.GetPlotDistance(px, py, a.x, a.y)) end
        if near >= 3 and near <= MAXD and legal(plot) then
            local food, prod, lux, luxNew, strat, mountains, foreign, unrevealed = 0, 0, 0, 0, 0, 0, 0, 0
            local reefs, geo, jungle = 0, 0, 0
            local luxNames = {{}}
            for dy = -2, 2 do for dx = -2, 2 do
                local q = Map.GetPlot(px + dx, py + dy)
                if q then
                    local d = Map.GetPlotDistance(px, py, q:GetX(), q:GetY())
                    if d >= 1 and d <= 2 then
                        if not vis:IsRevealed(q:GetIndex()) then
                            unrevealed = unrevealed + 1
                        else
                            local w = (d == 1) and 2 or 1
                            if not q:IsMountain() then
                                food = food + w * q:GetYield(0)
                                prod = prod + w * q:GetYield(1)
                            end
                            if d == 1 then
                                if q:IsMountain() then mountains = mountains + 1 end
                                local ft = featureType(q)
                                if ft == "FEATURE_REEF" then reefs = reefs + 1
                                elseif ft == "FEATURE_GEOTHERMAL_FISSURE" then geo = geo + 1
                                elseif ft == "FEATURE_JUNGLE" then jungle = jungle + 1 end
                            end
                            if q:GetOwner() >= 0 and q:GetOwner() ~= me then foreign = foreign + 1 end
                            local ri = q:GetResourceType()
                            if ri >= 0 then
                                local row = GameInfo.Resources[ri]
                                if row and resVisible(row) then
                                    if row.ResourceClassType == "RESOURCECLASS_LUXURY" then
                                        lux = lux + 1
                                        if not luxSeen[row.ResourceType] then luxNew = luxNew + 1 end
                                        table.insert(luxNames, row.ResourceType)
                                    elseif row.ResourceClassType == "RESOURCECLASS_STRATEGIC" then
                                        strat = strat + 1
                                    end
                                end
                            end
                        end
                    end
                end
            end end
            local fresh = plot:IsFreshWater()
            local coast = plot:IsCoastalLand()
            local hills = plot:IsHills()
            local score = food + prod + (fresh and 12 or 0) + (coast and 4 or 0) + (hills and 4 or 0)
                + 8 * luxNew + 3 * (lux - luxNew) + 3 * strat + 2 * math.min(mountains + 2 * reefs + 2 * geo + math.floor(jungle / 2), 5)
                - 3 * foreign - 3 * math.max(0, near - 6) + (recommended[idx] and 5 or 0)
            table.insert(candidates, {{x = px, y = py, score = score, food = food, prod = prod, fresh = fresh, coast = coast,
                hills = hills, lux = table.concat(luxNames, ";"), luxNew = luxNew, strat = strat, mountains = mountains,
                campus = mountains + 2 * reefs + 2 * geo + math.floor(jungle / 2), reefs = reefs,
                foreign = foreign, near = near, rec = recommended[idx] and true or false, unrevealed = unrevealed}})
        end
    end
end
table.sort(candidates, function(a, b) return a.score > b.score end)
-- Keep picks at least 4 tiles apart so the list offers real alternatives
local picked = {{}}
for _, c in ipairs(candidates) do
    if #picked >= LIMIT then break end
    local clash = false
    for _, p in ipairs(picked) do
        if Map.GetPlotDistance(c.x, c.y, p.x, p.y) < 4 then clash = true; break end
    end
    if not clash then table.insert(picked, c) end
end
for _, c in ipairs(picked) do
    print("SETTLE|" .. c.x .. "|" .. c.y .. "|" .. c.score .. "|" .. c.food .. "|" .. c.prod .. "|" .. (c.fresh and 1 or 0)
        .. "|" .. (c.coast and 1 or 0) .. "|" .. (c.hills and 1 or 0) .. "|" .. c.lux .. "|" .. c.luxNew .. "|" .. c.strat
        .. "|" .. c.mountains .. "|" .. c.foreign .. "|" .. c.near .. "|" .. (c.rec and 1 or 0) .. "|" .. c.unrevealed
        .. "|" .. c.campus .. "|" .. c.reefs)
end
print("SETTLECOUNT|" .. #candidates)
print("{SENTINEL}")
"""
    )


def parse_settle(lines: list[str]) -> tuple[list[dict], int]:
    spots, total = [], 0
    for line in lines:
        if line.startswith("ERR:"):
            raise ValueError("No city or settler to plan from yet." if "NO_CITY" in line else line)
        p = line.split("|")
        try:
            if p[0] == "SETTLE" and len(p) >= 17:
                spots.append(
                    {
                        "x": int(p[1]),
                        "y": int(p[2]),
                        "score": int(float(p[3])),
                        "food": int(float(p[4])),
                        "production": int(float(p[5])),
                        "fresh_water": p[6] == "1",
                        "coastal": p[7] == "1",
                        "hills": p[8] == "1",
                        "luxuries": [r for r in p[9].split(";") if r],
                        "new_luxury_types": int(p[10]),
                        "strategics": int(p[11]),
                        "adjacent_mountains": int(p[12]),
                        "foreign_tiles": int(p[13]),
                        "distance": int(p[14]),
                        "game_recommends": p[15] == "1",
                        "unrevealed_nearby": int(p[16]),
                        "campus_adjacency": int(p[17]) if len(p) > 17 else int(p[12]),
                        "adjacent_reefs": int(p[18]) if len(p) > 18 else 0,
                    }
                )
            elif p[0] == "SETTLECOUNT":
                total = int(p[1])
        except (ValueError, IndexError):
            continue
    return spots, total



# ---------------------------------------------------------------------------
# Rule tables from the running game (replaces hard-coded gamedata when live)
# ---------------------------------------------------------------------------


def build_rules_query() -> str:
    """Entertainment/housing per building and district, and how many cities each
    luxury feeds (Resources.Happiness), straight from GameInfo — so the numbers
    match the ruleset this game loaded. REA showed rulesets differ (e.g. Palace
    amenities 1 vs 2 between two cached databases)."""
    return f"""
for row in GameInfo.Buildings() do
    local e, h, r = row.Entertainment or 0, row.Housing or 0, row.RegionalRange or 0
    if e ~= 0 or h ~= 0 then print("RB|" .. row.BuildingType .. "|" .. e .. "|" .. h .. "|" .. r) end
end
for row in GameInfo.Districts() do
    local e, h = row.Entertainment or 0, row.Housing or 0
    if e ~= 0 or h ~= 0 then print("RD|" .. row.DistrictType .. "|" .. e .. "|" .. h) end
end
for row in GameInfo.Resources() do
    if row.ResourceClassType == "RESOURCECLASS_LUXURY" then print("RL|" .. row.ResourceType .. "|" .. (row.Happiness or 0)) end
end
print("{SENTINEL}")
"""


def parse_rules(lines: list[str]) -> dict:
    out: dict = {
        "entertainment_buildings": {},
        "regional_entertainment": set(),
        "housing_buildings": {},
        "entertainment_districts": {},
        "housing_districts": {},
        "luxury_cities": {},
    }
    for line in lines:
        p = line.split("|")
        try:
            if p[0] == "RB" and len(p) >= 5:
                e, h, r = int(float(p[2])), int(float(p[3])), int(float(p[4]))
                if e:
                    out["entertainment_buildings"][p[1]] = e
                    if r:
                        out["regional_entertainment"].add(p[1])
                if h:
                    out["housing_buildings"][p[1]] = h
            elif p[0] == "RD" and len(p) >= 4:
                e, h = int(float(p[2])), int(float(p[3]))
                if e:
                    out["entertainment_districts"][p[1]] = e
                if h:
                    out["housing_districts"][p[1]] = h
            elif p[0] == "RL" and len(p) >= 3:
                out["luxury_cities"][p[1]] = int(float(p[2]))
        except ValueError:
            continue
    return out
