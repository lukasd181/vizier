"""FireTuner client: talk to a running Civilization VI over its debug port.

Civ 6 opens a TCP port (4318) when EnableTuner is 1 in AppOptions.txt. The
wire format is length-prefixed frames:

    [4-byte LE uint32 length][4-byte LE int32 tag][UTF-8 payload + NUL]

Handshake: "APP:" returns the game identity, "LSQ:" lists Lua states as
alternating index/name entries. Commands are "CMD:<state>:<lua>" on tag 3;
print() output comes back as messages "O\\0<context>: <text>". Queries end by
printing SENTINEL so we know when a response is complete.

Two Lua states matter: GameCore_Tuner (the simulation) and InGame (the UI
layer, where the game's own UI calls the same APIs). Vizier runs everything
in InGame.

The game accepts ONE tuner connection at a time.

Ported from civ6-mcp (src/civ_mcp/tuner_client.py and connection.py),
MIT License, Copyright (c) 2026 Liam Wilkinson — see NOTICE.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass

log = logging.getLogger(__name__)

SENTINEL = "---END---"

_HEADER = "<Ii"  # little-endian: uint32 length, int32 tag
_HEADER_SIZE = struct.calcsize(_HEADER)
TAG_COMMAND = 3
TAG_HANDSHAKE = 4

DEFAULT_PORT = 4318
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


class LuaError(Exception):
    """The game reported an error running Lua."""


@dataclass
class _Message:
    tag: int
    payload: str


async def _send(writer: asyncio.StreamWriter, tag: int, payload: str) -> None:
    data = payload.encode("utf-8") + b"\x00"
    writer.write(struct.pack(_HEADER, len(data), tag) + data)
    await writer.drain()


async def _recv(reader: asyncio.StreamReader, timeout: float) -> _Message | None:
    try:
        header = await asyncio.wait_for(reader.readexactly(_HEADER_SIZE), timeout=timeout)
        length, tag = struct.unpack(_HEADER, header)
        data = await asyncio.wait_for(reader.readexactly(length), timeout=timeout)
    except asyncio.TimeoutError:
        return None
    return _Message(tag, data.rstrip(b"\x00").decode("utf-8", errors="replace"))


async def _drain(reader: asyncio.StreamReader, timeout: float) -> None:
    while await _recv(reader, timeout) is not None:
        pass


def _output_text(payload: str) -> str | None:
    """Text of a print() message ("O\\0<context>: <text>"), else None."""
    if not payload.startswith("O"):
        return None
    sep = payload.find(": ", 2)
    if sep >= 0:
        return payload[sep + 2 :]
    return payload.lstrip("O").lstrip("\x00").strip()


class GameConnection:
    """One persistent, reconnecting FireTuner connection, serialised by a lock."""

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT):
        # The tuner port must stay local (spec guardrail); remote access, if
        # ever added, goes through a daemon's outbound connection.
        if host not in LOCAL_HOSTS:
            raise ValueError("FireTuner must stay on localhost")
        self.host, self.port = host, port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self.app_identity = ""
        self.lua_states: dict[int, str] = {}
        self.gamecore_index: int | None = None
        self.ingame_index: int | None = None

    @property
    def is_connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=5.0
            )
        except (asyncio.TimeoutError, OSError) as e:
            raise ConnectionError(
                f"Cannot connect to Civ 6 at {self.host}:{self.port}. Is the game running with EnableTuner=1?"
            ) from e
        await _drain(self._reader, 0.3)
        await _send(self._writer, TAG_HANDSHAKE, "APP:")
        app = await _recv(self._reader, 5.0)
        self.app_identity = app.payload if app else ""
        await _send(self._writer, TAG_HANDSHAKE, "LSQ:")
        lsq = await _recv(self._reader, 5.0)
        raw = lsq.payload if lsq else ""
        entries = [s.strip() for s in raw.split("\x00") if s.strip()]
        if len(entries) <= 1 and "\n" in raw:
            entries = [s.strip() for s in raw.split("\n") if s.strip()]
        self._index_states(entries)
        log.info("Connected to %s (GameCore=%s, InGame=%s)", self.app_identity, self.gamecore_index, self.ingame_index)

    def _index_states(self, entries: list[str]) -> None:
        """Entries alternate [index, name, index, name, ...]."""
        self.lua_states, self.gamecore_index, self.ingame_index = {}, None, None
        i = 0
        while i + 1 < len(entries):
            try:
                idx = int(entries[i])
            except ValueError:
                i += 1
                continue
            name = entries[i + 1]
            self.lua_states[idx] = name
            if name == "GameCore_Tuner" and self.gamecore_index is None:
                self.gamecore_index = idx
            if name == "InGame" and self.ingame_index is None:
                self.ingame_index = idx
            i += 2

    async def disconnect(self) -> None:
        if self._writer and not self._writer.is_closing():
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError:
                pass
        self._reader = self._writer = None

    async def _ensure_game(self) -> None:
        if not self.is_connected:
            await self.connect()
        if self.ingame_index is None:
            # Connected at the main menu: states appear once a game loads.
            await self.disconnect()
            await self.connect()
        if self.ingame_index is None:
            raise ConnectionError("No game loaded: the InGame Lua state isn't there (still at the main menu?)")

    async def execute_write(self, lua: str, timeout: float = 5.0) -> list[str]:
        """Run Lua in the InGame context and return its printed lines."""
        await self._ensure_game()
        async with self._lock:
            try:
                return await self._run(self.ingame_index, lua, timeout)
            except (ConnectionError, OSError, asyncio.IncompleteReadError):
                log.info("Tuner connection lost; reconnecting once")
                await self.disconnect()
                await self.connect()
                return await self._run(self.ingame_index, lua, timeout)

    async def _run(self, state: int | None, lua: str, timeout: float) -> list[str]:
        assert self._reader is not None and self._writer is not None and state is not None
        await _drain(self._reader, 0.1)
        await _send(self._writer, TAG_COMMAND, f"CMD:{state}:{lua}")
        lines: list[str] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while (remaining := deadline - loop.time()) > 0:
            msg = await _recv(self._reader, min(remaining, 2.0))
            if msg is None:
                break
            if msg.payload.startswith("ERR:"):
                raise LuaError(msg.payload)
            text = _output_text(msg.payload)
            if text is None:
                continue
            if text.strip() == SENTINEL:
                break
            lines.append(text)
        await _drain(self._reader, 0.2)
        return lines
