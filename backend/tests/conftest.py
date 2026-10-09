"""Pytest configuration and shared fixtures."""
import os

# Must be set before anything imports app.config / app.database.session,
# which read the database URL once at import time.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as async")
