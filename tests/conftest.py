import asyncio
from pathlib import Path

import pytest

from vizier.fog import FogFilter
from vizier.mentor import Mentor
from vizier.sources.fixture import FixtureSource
from vizier.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
MIDGAME = FIXTURES / "midgame.json"

# Planted in raw fixture rows the player can't see; must never reach output.
HIDDEN_MARKERS = (
    "HIDDEN_CIV_SPAIN",
    "HIDDEN_RELIGION_CATHOLIC",
    "RESOURCE_HIDDEN_URANIUM",
    "RESOURCE_HIDDEN_NITER",
    "IMPROVEMENT_HIDDEN_CAMP",
    "IMPROVEMENT_HIDDEN_FORT",
    "FEATURE_HIDDEN_FOREST",
    "DISTRICT_HIDDEN_ENCAMPMENT",
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def mentor(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    m = Mentor(FixtureSource(MIDGAME), store, FogFilter(full_vision=False))
    yield m
    store.close()
