"""Mentor-specific Lua queries, sent over FireTuner like civ6-mcp's own.

Conventions follow civ_mcp.lua: each build_* returns Lua source that prints
pipe-delimited lines and ends with the sentinel; each parse_* turns those
lines into plain dicts. All of these run in the InGame context
(GameConnection.execute_write), which is where the game's own UI code calls
the same APIs.

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

from civ_mcp.lua._helpers import SENTINEL


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
    """One round-trip for everything the turn watcher needs beyond civ6-mcp's
    overview / victory / diplomacy / trade queries.

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
