"""Product catalog backed by SQLite."""
import sqlite3

SORTABLE = {"name": "name", "price": "price_cents", "newest": "created_at"}


def connect(path=":memory:"):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS products ("
        " sku TEXT PRIMARY KEY, name TEXT NOT NULL, price_cents INTEGER NOT NULL,"
        " created_at TEXT NOT NULL, hidden INTEGER NOT NULL DEFAULT 0)"
    )
    return conn


def add_product(conn, sku, name, price_cents, created_at, hidden=False):
    conn.execute(
        "INSERT INTO products (sku, name, price_cents, created_at, hidden) VALUES (?, ?, ?, ?, ?)",
        (sku, name, price_cents, created_at, int(hidden)),
    )
    conn.commit()


def search(conn, text):
    """Visible products whose name contains `text`, by name."""
    query = f"SELECT sku, name, price_cents FROM products WHERE hidden = 0 AND name LIKE '%{text}%' ORDER BY name"
    return [dict(row) for row in conn.execute(query)]


def get_product(conn, sku):
    row = conn.execute("SELECT sku, name, price_cents, hidden FROM products WHERE sku = ?", (sku,)).fetchone()
    return dict(row) if row else None


def set_hidden(conn, sku, hidden):
    conn.execute("UPDATE products SET hidden = ? WHERE sku = ?", (int(hidden), sku))
    conn.commit()


def count_visible(conn):
    return conn.execute("SELECT COUNT(*) FROM products WHERE hidden = 0").fetchone()[0]


def list_sorted(conn, sort="name", descending=False):
    """Visible products ordered by one of the SORTABLE keys."""
    column = SORTABLE[sort]
    direction = "DESC" if descending else "ASC"
    query = f"SELECT sku, name, price_cents FROM products WHERE hidden = 0 ORDER BY {column} {direction}"
    return [dict(row) for row in conn.execute(query)]
