"""Test harness: no network, isolated STOCKDESK_HOME, tools importable as plain modules."""
from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
from stockdesk import common  # noqa: E402

DATA = ROOT / "src" / "stockdesk" / "data"


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise RuntimeError("network access is disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "config").mkdir(parents=True)
    for name in ("peers.json", "sector_etf.json", "news_names.json"):
        source = DATA / "config" / name
        if source.is_file():
            (home / "config" / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("STOCKDESK_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path / "user"))   # Path.home(): never the real ~/.stockdesk
    monkeypatch.setenv("SEC_USER_AGENT", "StockDeskTest tester@stockdesk.test")
    for name in ("STOCKDESK_CACHE_TTL", "STOCKDESK_NEWS_CACHE_TTL", "STOCKDESK_MAX_FUND_AGE_DAYS",
                 "STOCKDESK_CACHE_TTL_HOURS"):   # a demo-day shell must not change results
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(common, "_sleep", lambda seconds: None)
    common._last_request.clear()
    return home


@pytest.fixture
def run_id():
    rid = common.new_run_id()
    common.set_current_run(rid)
    return rid


@pytest.fixture
def fixtures_dir() -> Path:
    return ROOT / "tests" / "fixtures"
