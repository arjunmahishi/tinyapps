#!/usr/bin/env python3
"""tinyapps: serve AI-written HTML artifacts and apps; each app gets its own SQLite database.

Usage:
  tinyapps                         serve on TINYAPPS_PORT (default 8080)
  tinyapps delete apps <name>      delete an app page and its database
  tinyapps delete artifacts <name>
  tinyapps skill                   print the agent skill (SKILL.md)
"""

import json
import html
import os
import re
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
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


def listing():
    sections = []
    nav = []
    for kind in KINDS:
        names = sorted(p.stem for p in (HOME / "web" / kind).glob("*.html") if NAME.fullmatch(p.stem))
        title = kind.title()
        cards = "".join(
            f'<a class="item card" href="/{kind}/{n}"><span class="item-mark" aria-hidden="true">'
            f'{"◈" if kind == "apps" else "▧"}</span><span class="item-copy"><strong>{html.escape(n.replace("-", " ").title())}</strong>'
            f'<small>/{kind}/{n}</small></span><span class="open" aria-hidden="true">↗</span></a>'
            for n in names
        )
        if not cards:
            cards = f'<div class="empty card"><span class="empty-icon">✳</span><h3>No {kind} yet</h3><p>New {kind} will show up here when they’re ready.</p></div>'
        sections.append(
            f'<section id="{kind}" class="collection"><div class="section-head"><h2>{title}</h2>'
            f'<span class="count">{len(names):02d} {kind}</span></div><div class="grid">{cards}</div></section>'
        )
        nav.append(f'<a href="#{kind}">{title} <span>{len(names):02d}</span></a>')
    return f'''<!doctype html>
<html lang="en" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0b0d12"><title>Tinyapps · Library</title>
<link href="https://cdn.jsdelivr.net/npm/daisyui@4.12.24/dist/full.min.css" rel="stylesheet" type="text/css">
<script src="https://cdn.tailwindcss.com"></script>
<style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{min-height:100vh;margin:0;background:radial-gradient(ellipse at 50% -20%,#1f2b3d 0,transparent 55%),#0b0d12;color:#eff2f8;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}.shell{{width:min(100% - 40px,900px);margin:0 auto;padding:42px 0 72px}}.nav{{display:flex;align-items:center;justify-content:space-between;margin-bottom:70px}}.brand{{display:flex;align-items:center;gap:10px;font-size:14px;font-weight:750;letter-spacing:.02em;color:#f4f6fa;text-decoration:none}}.mark{{display:grid;place-items:center;width:30px;height:30px;border-radius:10px;background:linear-gradient(135deg,#83e2c4,#8db5ff);color:#101821;font-weight:900}}.nav-note{{color:#8792a3;font-size:12px}}.eyebrow{{font:700 11px/1.4 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.16em;color:#8be0c4}}h1{{font-size:clamp(38px,7vw,58px);line-height:1.02;letter-spacing:-.055em;margin:13px 0 12px}}.intro{{max-width:570px;color:#a2adbd;font-size:15px;line-height:1.65;margin:0}}.tabs{{display:flex;gap:6px;border-bottom:1px solid #252d3a;margin:34px 0 18px;padding-bottom:10px}}.tabs a{{color:#9ca8b9;text-decoration:none;font-size:13px;font-weight:650;padding:8px 12px;border-radius:9px}}.tabs a:hover{{background:#202b3b;color:#e8f4f0}}.count{{color:#8290a3;font:12px ui-monospace,monospace}}.tabs a span{{font:11px ui-monospace,monospace;color:#8290a3;margin-left:5px}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr));gap:12px}}.item{{display:flex;align-items:center;gap:13px;padding:16px;text-decoration:none;color:inherit;background:linear-gradient(145deg,#171d28,#121720);border:1px solid #273142;border-radius:14px;transition:transform .16s,border-color .16s,background .16s}}.item:hover{{transform:translateY(-2px);border-color:#527564;background:#19241f}}.item-mark{{display:grid;place-items:center;flex:none;width:40px;height:40px;border-radius:12px;background:#202d33;color:#9ce8ca;font-size:20px}}.item-copy{{min-width:0;display:flex;flex-direction:column;gap:4px}}.item-copy strong{{font-size:14px;line-height:1.25;text-transform:capitalize;overflow-wrap:anywhere}}.item-copy small{{color:#7f8da1;font:11px ui-monospace,monospace;overflow:hidden;text-overflow:ellipsis}}.open{{margin-left:auto;color:#91a3b9;font-size:17px}}.empty{{grid-column:1/-1;text-align:center;padding:48px 20px;background:#121720;border:1px dashed #303a49;border-radius:16px}}.empty-icon{{color:#8be0c4;font-size:23px}}.empty h3{{margin:10px 0 5px;font-size:17px}}.empty p{{color:#8d99aa;font-size:13px;margin:0}}footer{{margin-top:50px;padding-top:16px;border-top:1px solid #202733;color:#667386;font-size:11px}}.collection{{margin-top:32px}}.section-head{{display:flex;align-items:baseline;justify-content:space-between;margin:0 2px 12px}}.section-head h2{{font-size:18px;letter-spacing:-.02em;margin:0}}@media(max-width:600px){{.shell{{width:min(100% - 30px,900px);padding-top:25px}}.nav{{margin-bottom:52px}}.nav-note{{font-size:11px}}}}
</style></head><body><main class="shell"><header class="nav"><a class="brand" href="/"><span class="mark">t</span>tinyapps</a><span class="nav-note">Small tools, ready to open</span></header>
<div class="eyebrow">Your collection</div><h1>Library</h1><p class="intro">Apps and standalone artifacts, together in one place.</p>
<nav class="tabs" aria-label="Collections">{''.join(nav)}</nav>{''.join(sections)}
<footer>tinyapps <span aria-hidden="true">·</span> a home for small useful things</footer></main></body></html>'''


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
                self.send(200, listing())
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
    if sys.argv[1:] == ["skill"]:
        return print(resources.files("tinyapps").joinpath("SKILL.md").read_text(), end="")
    if len(sys.argv) > 1:
        sys.exit(__doc__)
    for kind in KINDS:
        (HOME / "web" / kind).mkdir(parents=True, exist_ok=True)
    (HOME / "data").mkdir(parents=True, exist_ok=True)
    print(f"tinyapps serving {HOME} on :{PORT}", flush=True)
    host = os.environ.get("TINYAPPS_HOST", "0.0.0.0")
    ThreadingHTTPServer((host, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
