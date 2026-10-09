import concurrent.futures
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reflect import Budget, Db, Tasks


class DurableReflectionTests(unittest.TestCase):
    def test_cap_zero_stops_calls(self):
        with tempfile.TemporaryDirectory() as td:
            db = Db(Path(td) / 'data.db')
            self.addCleanup(lambda: db.conn.close())
            self.assertFalse(Budget(db, 0).take())
            self.assertEqual(Budget(db, 0).used_today(), (0, 0))

    def test_atomic_cap_across_connections(self):
        with tempfile.TemporaryDirectory() as td:
            dbs = [Db(Path(td) / 'data.db') for _ in range(16)]
            barrier = threading.Barrier(len(dbs))
            def take(db):
                barrier.wait()
                return Budget(db, 1).take()
            try:
                with concurrent.futures.ThreadPoolExecutor(len(dbs)) as pool:
                    results = list(pool.map(take, dbs))
                self.assertEqual(sum(results), 1)
                self.assertEqual(Budget(dbs[0], 1).used_today(), (1, 1))
            finally:
                for db in dbs: db.conn.close()

    def test_expired_owner_cannot_update_or_write(self):
        with tempfile.TemporaryDirectory() as td:
            db = Db(Path(td) / 'data.db')
            self.addCleanup(lambda: db.conn.close())
            self.assertTrue(hasattr(Tasks, 'acquire'), 'lease ownership is missing')
            now = [100.0]
            a = Tasks(db, clock=lambda: now[0], lease_seconds=2)
            b = Tasks(db, clock=lambda: now[0], lease_seconds=2)
            old = a.acquire('task')
            self.assertIsNotNone(old)
            self.assertIsNone(b.acquire('task'))
            now[0] = 103
            new = b.acquire('task')
            self.assertGreater(new.generation, old.generation)
            for method in (a.renew, a.complete, a.fail): self.assertFalse(method(old))
            with self.assertRaises(RuntimeError):
                with a.fence(old): pass
            self.assertTrue(b.complete(new))
            self.assertIsNone(a.acquire('task'))

    def test_invalid_release_does_not_spend_attempts(self):
        with tempfile.TemporaryDirectory() as td:
            db = Db(Path(td) / 'data.db')
            self.addCleanup(lambda: db.conn.close())
            tasks = Tasks(db)
            self.assertTrue(tasks.claim('retry'))
            tasks.unclaim('retry')
            tasks.unclaim('retry')
            attempts = db.conn.execute('SELECT attempts FROM tasks').fetchone()[0]
            self.assertEqual(attempts, 1)

    def test_legacy_claim_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'data.db'
            with sqlite3.connect(path) as conn:
                conn.execute('CREATE TABLE tasks(task TEXT PRIMARY KEY, claimed_at TEXT, attempts INTEGER DEFAULT 0)')
                conn.execute("INSERT INTO tasks VALUES('old', '2020-01-01', 0)")
            db = Db(path)
            self.addCleanup(lambda: db.conn.close())
            self.assertFalse(Tasks(db).claim('old'))
            columns = {r[1] for r in db.conn.execute('PRAGMA table_info(tasks)')}
            self.assertIn('state', columns)


if __name__ == '__main__': unittest.main()
