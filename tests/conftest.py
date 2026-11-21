import os
import tempfile
from pathlib import Path

import pytest

# Every test run gets its own database; the app module creates its schema at import.
_TMP = tempfile.TemporaryDirectory(prefix="lafaz-test-")
os.environ["LAFAZ_DB"] = str(Path(_TMP.name) / "lafaz.db")

from fastapi.testclient import TestClient  # noqa: E402

from lafaz.app import create_app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(create_app()) as c:
        yield c


def pytest_sessionfinish(session, exitstatus):
    _TMP.cleanup()
