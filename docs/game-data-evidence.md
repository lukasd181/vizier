# Game data evidence

The mentor reasons with game rules (amenity thresholds, which buildings give
amenities, which policy cards cost loyalty…). None of those numbers are taken
from wikis or memory. They were read from the shipped game with
[REA](https://github.com/morluto/rea), and each one is cited in
`src/chancellor/gamedata.py` by its evidence ID.

## Source artifact

| | |
|---|---|
| File | `~/Library/Application Support/Sid Meier's Civilization VI/Firaxis Games/Sid Meier's Civilization VI/Cache/DebugGameplay.sqlite` |
| What it is | The compiled gameplay database the game writes when it loads a ruleset |
| SHA-256 | `7d1acb3aaa494c00c220de1fc6045bfcb568682f1a09e6f2afb5103cd981941f` |
| Ruleset | Gathering Storm (`DISTRICT_DAM`, `DISTRICT_CANAL`, `DISTRICT_PRESERVE`, `DISTRICT_DIPLOMATIC_QUARTER` present) |
| Tool | REA `inspect_sqlite_database` (read-only private copy; source never opened by SQLite) |
| Inventory | 456 tables (`ev_56ca61d781f8bde59be8a5fab76a6996c1e5b902cc27c24408bee414d0d6c778`) |

The cache is rewritten when the game loads a different ruleset, so a vanilla
or Rise & Fall game can produce a different file. `gamedata.RULESET_SHA256`
records which one these numbers came from.

## Records

| Table | Evidence ID | Used for |
|---|---|---|
| `Happinesses` | `ev_8f9f51aa…6da5f00` | amenity → growth/yield levels (Revolt ≤ −7 … Ecstatic ≥ 5) |
| `Happinesses_XP1` | `ev_b95e1cde…aa3a711` | amenity level → loyalty per turn (−6 … +6) |
| `LoyaltyLevels` | `ev_ea34e648…f6b867` | loyalty → yield penalty bands |
| `Victories` | `ev_2706ec8b…2cffe7` | `CriticalPercentage` per victory, used as alert thresholds |
| `GlobalParameters` (492 rows) | `ev_90be58dc…cfa27bdc` | 20 DVP to win, 2 pop per amenity, national park amenities, housing growth steps, governor 5-turn establish, religion/starvation loyalty |
| `Buildings` (138 rows) | `ev_b440c386…e1d06b8d` | `Entertainment`, `Housing`, `RegionalRange` |
| `Districts` (36 rows) | `ev_1c8fbd61…e3546dd` | `Entertainment`, `Housing` |
| `PolicyModifiers` | `ev_bf72ecd2…6a181e1` | policy → modifier joins |
| `Modifiers` (3,197 rows) | `ev_a3846477…57a7cb79e` | modifier types (`…ADJUST_POLICY_AMENITY`, `…ADJUST_IDENTITY_PER_TURN`) |
| `ModifierArguments` (5,908 rows) | `ev_1b44225b…6aae831` | `Amount` per modifier |
| `BuildingModifiers` | `ev_8e009036…c49caa` | Monument +1, Colosseum +2 loyalty |

The complete bundle (12 records, 3.8 MB) was exported with
`export_evidence_bundle`; re-create it by running the same
`inspect_sqlite_database` calls against the file above.

## What REA established vs. what's still an estimate

**Observed in the shipped data:**
- Policy amenity amounts: Liberalism +1, New Deal +2, Retainers +1, Sports Media +1,
  Civil Prestige +1, Classical Republic +1; Robber Barons −2, Music Censorship −1,
  Automated Workforce −1.
- Policy loyalty: Limitanei +2, Praetorium +2, Colonial Offices +3, Martial Law +4,
  Automated Workforce −5.
- National Park: +2 amenities to its city, reaches 4 other cities.

**Not in the data (labelled `estimate` in the options output):**
- The governor's own +8 loyalty. No modifier or parameter carries it, so it's
  probably an engine constant. Check it against a live loyalty breakdown.
- Policy *conditions* (e.g. "cities with 2+ specialty districts"). The amounts
  were read, but their requirement sets weren't decoded. The conditions come
  from the card text.

## Second ruleset: the live game (re-checked with REA)

When a game is loaded, Civ 6 rewrites the cache for that game's ruleset. With
the America/Prince game loaded the file became
`8ba5359449d5a3d251fe02d12d5ef5ead52d93f575062e9833c6fa5cf6834718`:

| Check | Evidence ID | Result |
|---|---|---|
| `GlobalParameters` (492 rows) | `ev_d2d991ca…75e91e8127` | **identical** to the first ruleset (spacing, housing, park, DVP, governor, identity values) |
| `Buildings` | `ev_d75dd28c…cb409ebd` | 121 rows (138 before); **Palace Entertainment 2** (was 1) |
| `Districts` | `ev_c5d91912…6aa1638` | 30 rows (36 before): no Preserve, Diplomatic Quarter, Hippodrome, Observatory, Oppidum, Thanh |
| `Resources.Happiness` | `ev_e2f029d8…32fd7865` | every normal luxury feeds **4** cities; Perfume, Cinnamon, Cloves feed 6 |
| `District_Adjacencies` | `ev_60784930…6e0602f` | Campus: mountains, jungle, districts, Government Plaza, geothermal, reef; Commercial Hub: river, harbor, districts, Government Plaza |
| `Adjacency_YieldChanges` | `ev_39562247…7586f0d` | Campus: mountain **+1**, jungle **+1 per 2**, reef **+2**, geothermal **+2**, districts +1 per 2, Gov Plaza +1. Commercial Hub: river **+2**, harbor **+2**, districts +1 per 2, Gov Plaza +1 |

What changed in the code because of this:
- **Live rule tables.** `build_rules_query` reads entertainment, housing and
  luxury reach from `GameInfo` once per game, and the fix-it options and
  spare-luxury rule use them. `gamedata.py` is now only the fallback (fixtures,
  replays). Verified live: Washington's amenities show the Palace's +2.
- **Settle scoring** counts Campus adjacency with the verified values
  (mountain +1, reef +2, geothermal +2, jungle +1 per 2).
- **Luxury reach** in the spare-luxury rule is per resource
  (`Resources.Happiness`), not a flat 4.

## Engine APIs, confirmed in the shipped UI Lua

The mentor's Lua calls only APIs the game's own UI uses, found by searching
`Civ6.app/Contents/Assets/**/*.lua`:

| API | Shipped caller |
|---|---|
| `Players[me]:GetCities():IsValidFoundLocation(x, y)` | `DLC/PiratesScenario/Scripts/PiratesScenario_StartScript.lua:532` (settle legality; falls back to the 4-tile spacing rule) |
| `pPlayer:GetGrandStrategicAI():GetSettlementRecommendations(n)` | `Base/Assets/UI/WorldViewIconsManager.lua:710` (the game's settler recommendations) |
| `Game.GetNationalParks():GetPossibleParkTiles(player)` | `DLC/Expansion2/UI/Replacements/SelectedUnit_Expansion2.lua:59` — the engine's own park rule, used instead of re-implementing it |
| `pCityGrowth:GetAmenities() - GetAmenitiesNeeded()` | `Base/Assets/UI/CitySupport.lua:526` (net amenities) |
| `pCityGrowth:GetAmenitiesFrom*` / `GetHousingFrom*` | city panel breakdowns |
| `pCulturalIdentity:GetIdentitySourcesDetailedBreakdown()` | `DLC/Expansion2/UI/Additions/CityPanelCulture.lua:132` |
| `playerResources:IsResourceVisible(hash)` | plot tooltips (11 call sites) |
| `UILens.SetLayerHexesColoredArea`, `ClearLayerHexes`, `ToggleLayerOn/Off` | `CityBannerManager.lua`, `MinimapPanel_Expansion1.lua` |
| `PlayerConfigurations[me]:GetMapPin(x, y)`, `SetName`, `Network.BroadcastPlayerInfo` | `Base/Assets/UI/Popups/MapPinPopup.lua:237,334,340` |
| `Events.LocalPlayerTurnBegin`, `ExposedMembers` | 63 call sites; `MapTacks.lua` |

## A civ6-mcp bug this surfaced

`civ6-mcp/src/civ_mcp/lua/cities.py:45` reports a city's amenities as
`GetAmenitiesNeeded() + GetAmenities()`. The game's own formula
(`CitySupport.lua:526`) is `GetAmenities() - GetAmenitiesNeeded()`. The mentor
reads amenities with its own query, so this doesn't affect it, but civ6-mcp's
`get_cities` output overstates amenities.
