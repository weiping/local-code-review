"""Host-side checks for the five planted bugs, run in the demo repo after --apply. Prints one line per bug."""
import json, os, sqlite3, sys, tempfile
sys.path.insert(0, os.getcwd())
import app.orders as m

res = {}
conn = m.connect()
conn.executemany("INSERT INTO orders VALUES (?, ?, ?)", [(1, "paid", 1000), (2, "refunded", 500), (3, "paid", 900)])
try:
    res["sql_injection"] = len(m.find_orders(conn, "paid' OR '1'='1")) == 0 and len(m.find_orders(conn, "paid")) == 2
except Exception as e:
    res["sql_injection"] = False
res["pagination"] = m.page(list(range(23)), 1)[:3] == [0, 1, 2]
orders = json.loads('[{"status": "paid", "amount": 1000}, {"status": "refunded", "amount": 500}, {"status": "paid", "amount": 900}]')
try:
    res["is_not"] = m.revenue(orders) == 1900
except Exception:
    res["is_not"] = False
def down():
    raise RuntimeError("down")
try:
    m.retry(down)
    res["retry"] = False
except RuntimeError:
    res["retry"] = True
except Exception:
    res["retry"] = False
closed, real = [], sqlite3.connect
class Wrapped:
    def __init__(self, c):
        self._c = c
    def close(self):
        closed.append(1)
        self._c.close()
    def __getattr__(self, k):
        return getattr(self._c, k)
    def __enter__(self):
        self._c.__enter__()
        return self
    def __exit__(self, *a):
        return self._c.__exit__(*a)
m.sqlite3.connect = lambda *a, **k: Wrapped(real(*a, **k))
path = tempfile.mktemp(suffix=".db")
try:
    m.export_paid(path)
    res["conn_close"] = bool(closed)
except Exception:
    res["conn_close"] = False
finally:
    m.sqlite3.connect = real
print(json.dumps(res))
