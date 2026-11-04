import sqlite3
import time


def connect(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER, status TEXT, amount INTEGER)")
    return conn


def find_orders(conn, status):
    return conn.execute("SELECT id, status, amount FROM orders WHERE status = ?", (status,)).fetchall()


def page(items, number, size=20):
    start = (number - 1) * size
    return items[start:start + size]


def revenue(orders):
    return sum(o["amount"] for o in orders if o["status"] != "refunded")


def retry(fn, attempts=3, delay=0):
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(delay)


def export_paid(path):
    conn = connect(path)
    try:
        return conn.execute("SELECT id, amount FROM orders WHERE status = 'paid'").fetchall()
    finally:
        conn.close()
