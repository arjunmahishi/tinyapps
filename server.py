#!/usr/bin/env python3
"""tinyapps: serve AI-written HTML artifacts and apps; each app gets its own SQLite database.

Usage:
  server.py                        serve on TINYAPPS_PORT (default 8080)
  server.py delete apps <name>     delete an app page and its database
  server.py delete artifacts <name>
"""

import json
import os
import re
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HOME = Path(os.environ.get("TINYAPPS_HOME", Path.home() / "tinyapps"))
PORT = int(os.environ.get("TINYAPPS_PORT", "8080"))
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
KINDS = ("apps", "artifacts")
MAX_BODY = 1_000_000

FRAME_CSP = "sandbox allow-scripts allow-downloads; connect-src 'none'; form-action 'none'"
ARTIFACT_CSP = "sandbox allow-scripts allow-downloads; form-action 'none'"

SDK = """<script>
window.app = (() => {
  let next = 0;
  const pending = new Map();
  addEventListener("message", (e) => {
    if (e.source !== parent || !e.data || e.data.type !== "tinyapps:result") return;
    const p = pending.get(e.data.id);
    if (!p) return;
    pending.delete(e.data.id);
    if (e.data.error) p.reject(new Error(e.data.error));
    else p.resolve(e.data.rows);
  });
  return {
    name: %(name)s,
    sql(sql, params = []) {
      return new Promise((resolve, reject) => {
        const id = ++next;
        pending.set(id, { resolve, reject });
        parent.postMessage({ type: "tinyapps:sql", id, sql, params }, "*");
      });
    },
  };
})();
</script>
"""

HOST_PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<style>html, body, iframe { margin: 0; border: 0; width: 100%%; height: 100%%; display: block; }</style>
<iframe sandbox="allow-scripts allow-downloads" src="/apps/%(title)s/frame"></iframe>
<script>
const frame = document.querySelector("iframe");
addEventListener("message", async (e) => {
  if (e.source !== frame.contentWindow || !e.data || e.data.type !== "tinyapps:sql") return;
  const { id, sql, params } = e.data;
  let reply;
  try {
    const res = await fetch(%(api)s, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql, params }),
    });
    const body = await res.json();
    reply = res.ok ? { id, rows: body.rows } : { id, error: body.error || res.statusText };
  } catch (err) {
    reply = { id, error: String(err) };
  }
  frame.contentWindow.postMessage({ type: "tinyapps:result", ...reply }, "*");
});
</script>
"""


def page_path(kind, name):
    return HOME / "web" / kind / f"{name}.html"


def db_path(name):
    return HOME / "data" / f"{name}.sqlite"


def page_exists(kind, name):
    return kind in KINDS and bool(NAME.fullmatch(name)) and page_path(kind, name).is_file()


def _deny_attach(action, *_):
    if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def run_sql(name, sql, params):
    """Run one statement against the app's database and return its rows."""
    db_path(name).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path(name), timeout=5)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.set_authorizer(_deny_attach)
        con.row_factory = sqlite3.Row
        with con:
            return [dict(row) for row in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def inject(page, script):
    """Insert script at the start of <head>, else after the doctype, else at the top."""
    for pattern in (r"<head\b[^>]*>", r"<!doctype[^>]*>"):
        m = re.search(pattern, page, re.I)
        if m:
            return page[: m.end()] + script + page[m.end() :]
    return script + page


def listing(kind):
    names = sorted(p.stem for p in (HOME / "web" / kind).glob("*.html") if NAME.fullmatch(p.stem))
    items = "".join(f'<li><a href="/{kind}/{n}">{n}</a></li>' for n in names) or "<li>none yet</li>"
    return f'<!doctype html><meta charset="utf-8"><title>{kind}</title><h1>{kind}</h1><ul>{items}</ul>'


def delete(kind, name):
    if kind not in KINDS or not NAME.fullmatch(name):
        sys.exit(f"invalid kind or name: {kind} {name}")
    page = page_path(kind, name)
    if not page.is_file():
        sys.exit(f"no such {kind[:-1]}: {name}")
    page.unlink()
    if kind == "apps":
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db_path(name)}{suffix}").unlink(missing_ok=True)
    print(f"deleted {kind[:-1]} {name}")


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, ctype="text/html; charset=utf-8", csp=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if csp:
            self.send_header("Content-Security-Policy", csp)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status, obj):
        self.send(status, json.dumps(obj), "application/json")

    def parts(self):
        return urlsplit(self.path).path.strip("/").split("/")

    def do_GET(self):
        match self.parts():
            case [""]:
                self.send(200, '<!doctype html><meta charset="utf-8"><title>tinyapps</title>'
                          '<ul><li><a href="/apps">apps</a></li><li><a href="/artifacts">artifacts</a></li></ul>')
            case [kind] if kind in KINDS:
                self.send(200, listing(kind))
            case ["artifacts", name] if page_exists("artifacts", name):
                self.send(200, page_path("artifacts", name).read_bytes(), csp=ARTIFACT_CSP)
            case ["apps", name] if page_exists("apps", name):
                self.send(200, HOST_PAGE % {"title": name, "api": json.dumps(f"/api/apps/{name}/sql")})
            case ["apps", name, "frame"] if page_exists("apps", name):
                page = page_path("apps", name).read_text(encoding="utf-8")
                self.send(200, inject(page, SDK % {"name": json.dumps(name)}), csp=FRAME_CSP)
            case _:
                self.send_json(404, {"error": "not found"})

    def do_POST(self):
        match self.parts():
            case ["api", "apps", name, "sql"] if page_exists("apps", name):
                self.handle_sql(name)
            case _:
                self.send_json(404, {"error": "not found"})

    def handle_sql(self, name):
        # Only the host page may call the API; sandboxed pages send Origin "null". Compare
        # hosts, not schemes, so it keeps working behind a TLS-terminating proxy.
        if urlsplit(self.headers.get("Origin", "")).netloc != self.headers.get("Host"):
            return self.send_json(403, {"error": "forbidden origin"})
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self.send_json(415, {"error": "expected application/json"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= MAX_BODY:
                return self.send_json(413, {"error": "request too large"})
            body = json.loads(self.rfile.read(length))
            sql, params = body["sql"], body.get("params", [])
            if not isinstance(sql, str) or not isinstance(params, (list, dict)):
                raise ValueError("sql must be a string and params a list or object")
        except (ValueError, KeyError, TypeError) as exc:
            return self.send_json(400, {"error": f"bad request: {exc}"})
        try:
            self.send_json(200, {"rows": run_sql(name, sql, params)})
        except sqlite3.Error as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            self.log_error("sql failed for %s: %r", name, exc)
            self.send_json(500, {"error": str(exc)})


def main():
    if sys.argv[1:2] == ["delete"] and len(sys.argv) == 4:
        return delete(sys.argv[2], sys.argv[3])
    if len(sys.argv) > 1:
        sys.exit(__doc__)
    for kind in KINDS:
        (HOME / "web" / kind).mkdir(parents=True, exist_ok=True)
    (HOME / "data").mkdir(parents=True, exist_ok=True)
    print(f"tinyapps serving {HOME} on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
