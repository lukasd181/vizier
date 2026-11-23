"""`vizier setup` and `vizier doctor`.

setup  — turns the tuner on, installs the in-game panel mod and registers
         Vizier with Claude Desktop. Asks before each change (unless --yes)
         and backs up every file it edits.
doctor — read-only checks with a fix for each problem. Changes nothing.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from vizier.paths import bundled_mod_dir, civ_paths, first_existing

def _symbols() -> tuple[str, str, str]:
    """✓ ! ✗ where the console can print them (older Windows consoles can't)."""
    try:
        "✓✗".encode(sys.stdout.encoding or "ascii")
        return "✓", "!", "✗"
    except (UnicodeEncodeError, LookupError):
        return "OK", "!!", "XX"


OK, WARN, FAIL = _symbols()
_TUNER_RE = re.compile(r"^(\s*EnableTuner\s+)(\d+)", re.M)


def _ask(question: str, yes: bool) -> bool:
    if yes:
        return True
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _backup(path: Path, tag: str) -> Path:
    dst = path.with_name(path.name + f".{tag}-backup")
    shutil.copy2(path, dst)
    return dst


def tuner_setting(app_options: Path) -> int | None:
    m = _TUNER_RE.search(app_options.read_text(errors="replace"))
    return int(m.group(2)) if m else None


def server_command() -> dict:
    return {"command": sys.executable, "args": ["-m", "vizier"]}


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


def setup(yes: bool = False, claude_desktop: bool = False) -> int:
    paths = civ_paths()
    print(f"Vizier setup ({paths.platform})\n")

    # 1. Tuner
    app = first_existing(paths.app_options)
    if app is None:
        print(f"{FAIL} AppOptions.txt not found. Looked in:")
        for p in paths.app_options:
            print(f"    {p}")
        print("  Start Civ 6 once so it creates the file, or set VIZIER_APPOPTIONS to its path.")
    elif tuner_setting(app) == 1:
        print(f"{OK} The tuner is already on ({app}).")
    else:
        print("Vizier reads the game through its debug port (FireTuner).")
        print("Turning it on disables achievements while it's on.")
        if paths.platform == "windows":
            print("On Windows the tuner also needs the free 'Sid Meier's Civilization VI SDK'")
            print("(Steam → Library → Tools), or the 'Tuner' switch in the game's Options.")
        if _ask(f"Set EnableTuner 1 in {app}?", yes):
            text = app.read_text(errors="replace")
            bak = _backup(app, "vizier")
            if _TUNER_RE.search(text):
                text = _TUNER_RE.sub(r"\g<1>1", text, count=1)
            else:
                text += "\n[Debug]\n;Enable FireTuner.\nEnableTuner 1\n"
            app.write_text(text)
            print(f"{OK} Tuner on (backup: {bak.name}). Restart Civ 6 for it to take effect.")
        else:
            print(f"{WARN} Skipped. Vizier can't connect until EnableTuner is 1.")

    # 2. In-game panel mod
    src = bundled_mod_dir()
    mods = paths.mods_dir[0]
    if src is None:
        print(f"{WARN} The VizierAlerts mod isn't bundled with this install; skipping.")
    elif _ask(f"Install the optional in-game alert panel mod into {mods}?", yes):
        dst = mods / "VizierAlerts"
        mods.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, dirs_exist_ok=True)
        print(f"{OK} Mod installed. Enable 'Vizier Alerts' under Additional Content before loading a game.")
    else:
        print(f"{WARN} Skipped the mod (optional).")

    # 3. Clients
    entry = server_command()
    cfg = paths.claude_desktop_config
    if claude_desktop:
        if _ask(f"Register Vizier in Claude Desktop ({cfg})?", yes):
            data = json.loads(cfg.read_text()) if cfg.exists() else {}
            if cfg.exists():
                _backup(cfg, "vizier")
            data.setdefault("mcpServers", {})["vizier"] = entry
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text(json.dumps(data, indent=2))
            print(f"{OK} Registered. Quit and reopen Claude Desktop.")
    else:
        print("\nTo use Vizier in Claude Desktop, re-run with --claude-desktop, or add this to")
        print(f"{cfg}:")
        print(json.dumps({"mcpServers": {"vizier": entry}}, indent=2))
    print("\nFor Claude Code:")
    print(f"  claude mcp add vizier -- {entry['command']} -m vizier")
    print("\nThen run `vizier doctor` with a single-player game loaded.")
    return 0


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def _listen_address(port: int) -> str | None:
    """Best effort: which address the game's tuner port listens on."""
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=5).stdout
            for line in out.splitlines():
                if f":{port} " in line and "LISTENING" in line:
                    return line.split()[1]
        elif shutil.which("lsof"):
            out = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True, timeout=5
            ).stdout
            for line in out.splitlines()[1:]:
                return line.split()[8]
    except (OSError, subprocess.SubprocessError, IndexError):
        return None
    return None


async def _probe_game(port: int) -> tuple[str, str]:
    from vizier.sources.base import MultiplayerGame
    from vizier.sources.tuner import TunerSource

    src = TunerSource(port=port)
    try:
        civ, seed = await asyncio.wait_for(src.game_identity(), timeout=15)
        return OK, f"connected; single-player game loaded ({civ}, seed {seed})"
    except MultiplayerGame:
        return FAIL, "connected, but a multiplayer game is loaded; Vizier is single-player only"
    except (ConnectionError, OSError) as e:
        return FAIL, str(e)
    except asyncio.TimeoutError:
        return FAIL, "the tuner port answered but didn't respond; restart Civ 6 (the tuner can hang after a bad connection)"
    finally:
        await src.conn.disconnect()


def doctor(port: int = 4318) -> int:
    paths = civ_paths()
    rows: list[tuple[str, str, str]] = []

    def check(status: str, what: str, detail: str) -> None:
        rows.append((status, what, detail))

    py = sys.version_info
    check(OK if py >= (3, 12) else FAIL, "Python", f"{py.major}.{py.minor}" + ("" if py >= (3, 12) else " (need 3.12+)"))
    try:
        mcp_v = version("mcp")
        check(OK if mcp_v.split(".")[0] == "1" else FAIL, "mcp package", mcp_v + ("" if mcp_v.startswith("1.") else " (need 1.x)"))
    except PackageNotFoundError:
        check(FAIL, "mcp package", "not installed")

    app = first_existing(paths.app_options)
    if app is None:
        check(FAIL, "AppOptions.txt", "not found: " + ", ".join(str(p) for p in paths.app_options))
    else:
        val = tuner_setting(app)
        check(OK if val == 1 else FAIL, "Tuner", f"EnableTuner {val} in {app}" + ("" if val == 1 else " → run `vizier setup`"))

    mods = first_existing(paths.mods_dir)
    installed = bool(mods and (mods / "VizierAlerts" / "VizierAlerts.modinfo").exists())
    check(OK if installed else WARN, "In-game panel mod", "installed" if installed else "not installed (optional; `vizier setup`)")

    status, detail = asyncio.run(_probe_game(port))
    check(status, "Game connection", detail)
    addr = _listen_address(port)
    if addr:
        local = addr.startswith(("127.0.0.1", "[::1]", "localhost"))
        check(OK if local else WARN, "Tuner exposure", f"listening on {addr}" + ("" if local else " — reachable from your network; consider a firewall rule"))

    cfg = paths.claude_desktop_config
    try:
        entry = json.loads(cfg.read_text()).get("mcpServers", {}).get("vizier") if cfg.exists() else None
    except json.JSONDecodeError:
        entry = None
        check(FAIL, "Claude Desktop", f"{cfg} isn't valid JSON")
    if entry:
        exe_ok = Path(entry.get("command", "")).exists()
        check(OK if exe_ok else FAIL, "Claude Desktop", "registered" + ("" if exe_ok else f"; command not found: {entry.get('command')}"))
    else:
        check(WARN, "Claude Desktop", "not registered (optional; `vizier setup --claude-desktop`)")

    from vizier.store import default_db_path

    db = default_db_path()
    try:
        db.parent.mkdir(parents=True, exist_ok=True)
        check(OK, "Memory database", str(db))
    except OSError as e:
        check(FAIL, "Memory database", f"{db}: {e}")

    width = max(len(w) for _, w, _ in rows)
    print(f"Vizier doctor ({paths.platform})\n")
    for status, what, detail in rows:
        print(f"{status} {what.ljust(width)}  {detail}")
    failed = sum(1 for s, _, _ in rows if s == FAIL)
    print(f"\n{'All good.' if not failed else f'{failed} problem(s) above.'}")
    return 1 if failed else 0
