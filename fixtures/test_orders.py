import unittest

from app.orders import connect, find_orders, page, retry, revenue


class OrdersTest(unittest.TestCase):
    def test_find(self):
        conn = connect()
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?)", [(1, "paid", 1000), (2, "refunded", 500)])
        self.assertEqual(len(find_orders(conn, "paid")), 1)

    def test_page_size(self):
        self.assertEqual(len(page(list(range(100)), 2)), 20)

    def test_revenue_all_paid(self):
        self.assertEqual(revenue([{"status": "paid", "amount": 5}]), 5)

    def test_retry_success(self):
        self.assertEqual(retry(lambda: 3), 3)


if __name__ == "__main__":
    unittest.main()
