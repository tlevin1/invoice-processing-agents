"""Inventory database access layer."""
import sqlite3
from typing import Optional, Dict

DB_PATH = "inventory.db"


def get_item_stock(item_name: str, db_path: str = "") -> Optional[int]:
    """Return stock count for an item, or None if the item doesn't exist."""
    path = db_path or DB_PATH
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("SELECT stock FROM inventory WHERE item = ?", (item_name,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except sqlite3.OperationalError as e:
        raise RuntimeError(
            f"Cannot read inventory database at '{path}'. "
            "Run 'python setup_db.py' first."
        ) from e


def get_all_inventory(db_path: str = "") -> Dict[str, int]:
    """Return all inventory items as {item_name: stock}."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute("SELECT item, stock FROM inventory")
    rows = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}
