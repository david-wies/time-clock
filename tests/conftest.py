"""Shared pytest fixtures for the Time Clock test suite."""
# pylint: disable=redefined-outer-name  # pytest fixtures shadow module-level fixture names by design

from datetime import datetime

import pytest

from core.events import EventBus
from db.database import Database
from settings import SettingsManager


@pytest.fixture
def event_bus() -> EventBus:
    """Fixture providing a fresh EventBus for each test."""
    return EventBus()


@pytest.fixture
def db() -> Database:
    """Fixture providing a fresh in-memory SQLite database with the schema applied."""
    return Database(db_path=":memory:")


@pytest.fixture
def settings_manager(db: Database) -> SettingsManager:
    """Fixture providing a SettingsManager using the in-memory database."""
    return SettingsManager(db)


@pytest.fixture
def fixed_clock():
    """Deterministic 'now' clock for controller tests (§20.3)."""
    return lambda: datetime(2026, 6, 26, 9, 0)
