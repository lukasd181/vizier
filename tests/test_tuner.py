"""The FireTuner client against a fake game speaking the real wire protocol."""

import asyncio
import struct

import pytest
from conftest import run

from chancellor.tuner import SENTINEL, GameConnection, LuaError


def frame(tag: int, payload: str) -> bytes:
    data = payload.encode() + b"\x00"
    return struct.pack("<Ii", len(data), tag) + data


class FakeGame:
    """Answers APP:/LSQ: and echoes CMD: lines back as print() output."""

    def __init__(self, in_game: bool = True):
        self.in_game = in_game
        self.commands: list[str] = []

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                length, tag = struct.unpack("<Ii", await reader.readexactly(8))
                payload = (await reader.readexactly(length)).rstrip(b"\x00").decode()
                if payload == "APP:":
                    writer.write(frame(4, "Civ6 fake build"))
                elif payload == "LSQ:":
                    states = ["0", "Main", "7", "GameCore_Tuner"] + (["145", "InGame"] if self.in_game else [])
                    writer.write(frame(4, "\x00".join(states)))
                elif payload.startswith("CMD:"):
                    _, state, lua = payload.split(":", 2)
                    self.commands.append(f"{state}:{lua}")
                    if lua == "boom":
                        writer.write(frame(3, "ERR:attempt to call a nil value"))
                    else:
                        for line in lua.split("\n"):
                            writer.write(frame(3, f"O\x00InGame: {line}"))
                        writer.write(frame(3, f"O\x00InGame: {SENTINEL}"))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()


async def with_game(game: FakeGame, fn):
    server = await asyncio.start_server(game.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        conn = GameConnection("127.0.0.1", port)
        try:
            return await fn(conn)
        finally:
            await conn.disconnect()
    finally:
        server.close()
        await server.wait_closed()


def test_handshake_finds_lua_states():
    async def go(conn):
        await conn.connect()
        return conn.app_identity, conn.gamecore_index, conn.ingame_index

    assert run(with_game(FakeGame(), go)) == ("Civ6 fake build", 7, 145)


def test_execute_runs_in_ingame_and_collects_until_sentinel():
    game = FakeGame()

    async def go(conn):
        return await conn.execute_write("TURN|12\nCITY|Kyoto", timeout=3)

    assert run(with_game(game, go)) == ["TURN|12", "CITY|Kyoto"]
    assert game.commands[0].startswith("145:")


def test_lua_error_raises():
    async def go(conn):
        with pytest.raises(LuaError):
            await conn.execute_write("boom", timeout=3)

    run(with_game(FakeGame(), go))


def test_main_menu_has_no_game():
    async def go(conn):
        with pytest.raises(ConnectionError, match="No game loaded"):
            await conn.execute_write("x", timeout=3)

    run(with_game(FakeGame(in_game=False), go))


def test_no_game_running():
    async def go():
        conn = GameConnection("127.0.0.1", 1)  # nothing listens on port 1
        with pytest.raises(ConnectionError, match="EnableTuner"):
            await conn.connect()

    run(go())


def test_refuses_remote_host():
    with pytest.raises(ValueError, match="localhost"):
        GameConnection("192.168.1.20")
