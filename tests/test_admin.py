"""`vizier setup` and `vizier doctor` against temporary files, never the real ones."""

import json
from pathlib import Path

import pytest

from vizier import admin
from vizier.paths import CivPaths, bundled_mod_dir, civ_paths


@pytest.fixture
def fake_paths(tmp_path, monkeypatch):
    app = tmp_path / "AppOptions.txt"
    app.write_text("[Video]\nFullScreen 0\n\n[Debug]\n;Enable FireTuner.\nEnableTuner 0\n")
    paths = CivPaths("mac", [app], [tmp_path / "Mods"], tmp_path / "Claude" / "claude_desktop_config.json")
    monkeypatch.setattr(admin, "civ_paths", lambda: paths)
    monkeypatch.setenv("VIZIER_DB", str(tmp_path / "db.sqlite3"))
    return paths


def test_setup_turns_tuner_on_installs_mod_and_registers(fake_paths):
    assert admin.setup(yes=True, claude_desktop=True) == 0
    app = fake_paths.app_options[0]
    assert admin.tuner_setting(app) == 1
    assert "FullScreen 0" in app.read_text()  # nothing else touched
    assert app.with_name("AppOptions.txt.vizier-backup").read_text().count("EnableTuner 0") == 1
    assert (fake_paths.mods_dir[0] / "VizierAlerts" / "VizierAlerts.modinfo").exists()
    cfg = json.loads(fake_paths.claude_desktop_config.read_text())
    assert cfg["mcpServers"]["vizier"]["args"] == ["-m", "vizier"]


def test_setup_keeps_other_claude_servers(fake_paths):
    cfg = fake_paths.claude_desktop_config
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"preferences": {"x": 1}, "mcpServers": {"other": {"command": "x"}}}))
    admin.setup(yes=True, claude_desktop=True)
    data = json.loads(cfg.read_text())
    assert data["preferences"] == {"x": 1} and set(data["mcpServers"]) == {"other", "vizier"}
    assert cfg.with_name(cfg.name + ".vizier-backup").exists()


def test_setup_without_consent_changes_nothing(fake_paths, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    before = fake_paths.app_options[0].read_text()
    admin.setup(yes=False, claude_desktop=True)
    assert fake_paths.app_options[0].read_text() == before
    assert not fake_paths.mods_dir[0].exists() and not fake_paths.claude_desktop_config.exists()


def test_doctor_reports_without_changing_anything(fake_paths, capsys):
    before = fake_paths.app_options[0].read_text()
    code = admin.doctor(port=1)  # nothing listens on port 1
    out = capsys.readouterr().out
    assert code == 1
    assert "EnableTuner 0" in out and "Cannot connect" in out
    assert fake_paths.app_options[0].read_text() == before


def test_mod_is_bundled():
    assert bundled_mod_dir() is not None


@pytest.mark.parametrize("plat", ["darwin", "win32", "linux"])
def test_platform_paths(plat, monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", plat)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("VIZIER_APPOPTIONS", raising=False)
    monkeypatch.delenv("VIZIER_MODS_DIR", raising=False)
    p = civ_paths()
    assert p.app_options[0].name == "AppOptions.txt"
    assert p.mods_dir[0].name == "Mods" and "Civilization VI" in str(p.mods_dir[0])
    assert p.claude_desktop_config.name == "claude_desktop_config.json"
