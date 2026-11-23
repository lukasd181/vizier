-- Vizier Alerts: shows the mentor's top alerts in the game UI.
--
-- The MCP server writes ExposedMembers.Vizier = { turn = N, alerts = {...} }
-- over FireTuner and fires LuaEvents.Vizier_AlertsUpdated. ExposedMembers is
-- shared across UI contexts, so this context can read what the tuner wrote.
--
-- On each LocalPlayerTurnBegin this bumps ExposedMembers.Vizier_TurnSeq,
-- the turn-start signal a watcher can poll for. Display only: no game calls.

include("InstanceManager");

local m_AlertIM = InstanceManager:new("AlertInstance", "Root", Controls.AlertStack);
local m_Dismissed = -1;  -- turn the player closed the panel on

local SEVERITY_PREFIX = {
  critical = "[COLOR_RED]",
  warning  = "[COLOR_LIGHTBLUE]",
  info     = "",
};

function Refresh()
  local data = ExposedMembers.Vizier;
  m_AlertIM:ResetInstances();
  if data == nil or data.alerts == nil or #data.alerts == 0 then
    Controls.Panel:SetHide(true);
    return;
  end

  local turn = Game.GetCurrentGameTurn();
  if m_Dismissed == turn then
    Controls.Panel:SetHide(true);
    return;
  end

  local header = "Vizier";
  if data.turn ~= nil and data.turn < turn then
    header = header .. " [COLOR_Grey](from turn " .. tostring(data.turn) .. ")[ENDCOLOR]";
  end
  Controls.Header:SetText(header);

  for _, a in ipairs(data.alerts) do
    local inst = m_AlertIM:GetInstance();
    local prefix = SEVERITY_PREFIX[a.severity] or "";
    local suffix = (prefix ~= "") and "[ENDCOLOR]" or "";
    inst.Title:SetText(prefix .. (a.title or "") .. suffix);
    inst.Detail:SetText(a.detail or "");
  end
  Controls.AlertStack:CalculateSize();
  Controls.Body:CalculateSize();
  Controls.Frame:SetSizeY(Controls.Body:GetSizeY() + 28);
  Controls.Panel:SetHide(false);
end

function OnLocalPlayerTurnBegin()
  ExposedMembers.Vizier_TurnSeq = (ExposedMembers.Vizier_TurnSeq or 0) + 1;
  Refresh();
end

function OnClose()
  m_Dismissed = Game.GetCurrentGameTurn();
  Controls.Panel:SetHide(true);
end

function Initialize()
  ExposedMembers.Vizier = ExposedMembers.Vizier or {};
  Controls.Close:RegisterCallback(Mouse.eLClick, OnClose);
  Events.LocalPlayerTurnBegin.Add(OnLocalPlayerTurnBegin);
  LuaEvents.Vizier_AlertsUpdated.Add(function() m_Dismissed = -1; Refresh(); end);
  Refresh();
end
Initialize();
