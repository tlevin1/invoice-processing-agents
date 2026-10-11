import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session", autouse=True)
def inventory_db():
    """The validation tests read inventory.db, which is gitignored. Create it on
    a fresh clone (or in CI) so `pytest` works without a manual setup step."""
    from setup_db import setup_inventory

    db = ROOT / "inventory.db"
    if not db.exists():
        setup_inventory(str(db))
