import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from bganalyzer.config import AppConfig
from bganalyzer.contracts.domain import SourceRecord
from bganalyzer.db.connection import close_connection, initialize_database
from bganalyzer.db.repository import Repository


@pytest.fixture
def config(tmp_path, monkeypatch):
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(name, str(tmp_path / name))
    config = AppConfig()
    config.nightscout.origin = "https://example.test/nightscout"
    yield config
    close_connection()


@pytest.fixture
def repo(config):
    initialize_database(config)
    repo = Repository(config)
    repo.upsert_source(SourceRecord(id="synthetic", origin=config.nightscout.origin))
    return repo
