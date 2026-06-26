import pytest
from db.database import Database
from core.events import EventBus
from settings import SettingsManager


@pytest.fixture
def event_bus() -> EventBus:
    """Fixture providing a fresh EventBus for each test."""
    return EventBus()


@pytest.fixture
def db() -> Database:
    """Fixture providing a fresh in-memory SQLite database instance with the schema applied."""
    return Database(db_path=":memory:")


@pytest.fixture
def settings_manager(db: Database) -> SettingsManager:
    """Fixture providing a SettingsManager using the in-memory database."""
    return SettingsManager(db)
