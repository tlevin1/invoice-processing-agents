"""
Run once before processing invoices:
    python setup_db.py
"""
import sqlite3
import sys


def setup_inventory(db_path: str = "inventory.db") -> None:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS inventory")
    cursor.execute(
        "CREATE TABLE inventory (item TEXT PRIMARY KEY, stock INTEGER, unit_price REAL)"
    )
    cursor.executemany(
        "INSERT INTO inventory VALUES (?, ?, ?)",
        [
            ("WidgetA", 15, 250.00),
            ("WidgetB", 10, 500.00),
            ("GadgetX", 5,  750.00),
            ("FakeItem", 0, 999.00),
        ],
    )
    conn.commit()
    conn.close()
    print(f"Inventory database created at '{db_path}'")
    print("  WidgetA  : 15 in stock @ $250.00")
    print("  WidgetB  : 10 in stock @ $500.00")
    print("  GadgetX  :  5 in stock @ $750.00")
    print("  FakeItem :  0 in stock @ $999.00")


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "inventory.db"
    setup_inventory(db_path)
