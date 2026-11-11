"""End-to-end check for server.py, against a temporary content folder."""

import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer

import server


class TinyappsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        server.HOME = Path(cls.tmp.name)
        for kind in server.KINDS:
            (server.HOME / "web" / kind).mkdir(parents=True)
        server.page_path("apps", "todo").write_text("<!doctype html><html><head><title>t</title></head><body>todo</body></html>")
        server.page_path("artifacts", "report").write_text("<h1>report</h1>")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.host = f"127.0.0.1:{cls.httpd.server_port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(self.host)
        conn.request(method, path, body=body, headers=headers or {})
        res = conn.getresponse()
        data = res.read().decode()
        conn.close()
        return res, data

    def sql(self, sql, params=(), app="todo", origin=None):
        headers = {"Content-Type": "application/json", "Origin": origin or f"http://{self.host}"}
        res, data = self.request("POST", f"/api/apps/{app}/sql", json.dumps({"sql": sql, "params": list(params)}), headers)
        return res.status, json.loads(data)

    def test_app_pages_and_sql(self):
        res, data = self.request("GET", "/apps/todo")
        self.assertEqual(res.status, 200)
        self.assertIn('<iframe sandbox="allow-scripts allow-downloads" src="/apps/todo/frame">', data)

        res, data = self.request("GET", "/apps/todo/frame")
        self.assertEqual(res.status, 200)
        self.assertIn("connect-src 'none'", res.getheader("Content-Security-Policy"))
        self.assertTrue(res.getheader("Content-Security-Policy").startswith("sandbox allow-scripts"))
        self.assertLess(data.index("<head>"), data.index("window.app"))
        self.assertLess(data.index("window.app"), data.index("<title>"))

        self.assertEqual(self.sql("CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY, title TEXT)"), (200, {"rows": []}))
        status, body = self.sql("INSERT INTO todos (title) VALUES (?) RETURNING id", ["milk"])
        self.assertEqual(status, 200)
        new_id = body["rows"][0]["id"]

        # The agent writes to the database directly; the app sees it.
        with sqlite3.connect(server.db_path("todo"), timeout=5) as con:
            con.execute("INSERT INTO todos (title) VALUES ('eggs')")
        status, body = self.sql("SELECT title FROM todos WHERE id >= ? ORDER BY id", [new_id])
        self.assertEqual((status, body), (200, {"rows": [{"title": "milk"}, {"title": "eggs"}]}))

    def test_sql_errors(self):
        for sql in ("ATTACH DATABASE '/tmp/x.sqlite' AS x", "SELECT 1; SELECT 2", "SELEC nope"):
            with self.subTest(sql=sql):
                status, body = self.sql(sql)
                self.assertEqual(status, 400)
                self.assertIn("error", body)

    def test_api_rejects_other_callers(self):
        cases = [
            ("foreign origin", {"Origin": "http://evil.example", "Content-Type": "application/json"}, 403),
            ("sandboxed page", {"Origin": "null", "Content-Type": "application/json"}, 403),
            ("no origin", {"Content-Type": "application/json"}, 403),
            ("not json", {"Origin": f"http://{self.host}", "Content-Type": "text/plain"}, 415),
        ]
        for label, headers, want in cases:
            with self.subTest(label):
                res, _ = self.request("POST", "/api/apps/todo/sql", '{"sql": "SELECT 1"}', headers)
                self.assertEqual(res.status, want)
        # Artifacts have no database.
        self.assertEqual(self.sql("SELECT 1", app="report")[0], 404)

    def test_artifact(self):
        res, data = self.request("GET", "/artifacts/report")
        self.assertEqual(res.status, 200)
        self.assertEqual(data, "<h1>report</h1>")
        self.assertTrue(res.getheader("Content-Security-Policy").startswith("sandbox allow-scripts"))
        self.assertIn("report", self.request("GET", "/artifacts")[1])

    def test_nothing_else_is_served(self):
        self.sql("SELECT 1")  # make sure the database file exists
        for path in ("/apps/todo.sqlite", "/data/todo.sqlite", "/apps/../data/todo.sqlite", "/web/apps/todo.html",
                     "/apps/todo.html", "/apps/Bad_Name", "/artifacts/todo", "/apps/report", "/artifacts/report/frame"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0].status, 404)

    def test_delete(self):
        server.page_path("apps", "gone").write_text("<p>bye</p>")
        self.sql("CREATE TABLE t (x)", app="gone")
        self.assertTrue(server.db_path("gone").exists())
        server.delete("apps", "gone")
        self.assertFalse(server.page_path("apps", "gone").exists())
        self.assertFalse(list(server.db_path("gone").parent.glob("gone.sqlite*")))

        server.page_path("artifacts", "old").write_text("<p>old</p>")
        server.delete("artifacts", "old")
        self.assertFalse(server.page_path("artifacts", "old").exists())

        for kind, name in (("apps", "../todo"), ("pages", "todo"), ("apps", "missing")):
            with self.subTest(kind=kind, name=name), self.assertRaises(SystemExit):
                server.delete(kind, name)


if __name__ == "__main__":
    unittest.main()
