---
name: tinyapps
description: Build, update and delete small web apps (HTML + their own SQLite database) and static HTML artifacts on this machine, served at /apps/<name> and /artifacts/<name>. Use when the user asks for an app, tool, dashboard, tracker, page, report, chart or "artifact" they can open in a browser.
version: 1.0.0
metadata:
  hermes:
    tags: [apps, artifacts, html, sqlite, web]
---

# tinyapps

A local server (`tinyapps.service`, code in `~/dev/tinyapps/`) serves pages you write as single HTML files.
Base URL: `http://192.168.0.15:8080`. Content lives in `~/tinyapps/`. Never edit `~/dev/tinyapps/`.

## Pick the kind

- Needs to save data or act on something → **app**: `~/tinyapps/web/apps/<name>.html`, link `<base>/apps/<name>`.
- Otherwise (report, chart, mockup, one-off page) → **artifact**: `~/tinyapps/web/artifacts/<name>.html`, link `<base>/artifacts/<name>`.

Names: lowercase letters, digits, dashes; start with a letter or digit; max 63 chars (`^[a-z0-9][a-z0-9-]{0,62}$`).
Check the name isn't taken before creating (unless updating). Writing the file publishes it immediately; always reply with the link.

## Page rules (both kinds)

- One self-contained HTML file with `<!doctype html>` and a `<head>`. Inline CSS/JS; CDN `<script>`/`<link>` over https is fine.
- It runs in a sandbox: no `localStorage`/`sessionStorage`/cookies, no `alert`/`confirm`/`prompt`, no popups or `target="_blank"`, no `<form>` submission (handle input with JS).
- Apps additionally cannot use `fetch`/XHR/WebSocket at all. Artifacts can fetch public data, but not the tinyapps API.
- Show loading and error states on the page.

## App data: `app.sql`

The server injects `window.app` into apps. One SQL statement per call; returns a Promise of row objects.

```js
try {
  const rows = await app.sql("SELECT id, title FROM todos WHERE done = ? ORDER BY id", [0]);
  const [{ id }] = await app.sql("INSERT INTO todos (title) VALUES (?) RETURNING id", [title]);
} catch (err) {
  showError(err.message);
}
```

Use `?` parameters for every value, never string-built SQL. Use `RETURNING` to get new ids.

## App database: write it directly

Each app has its own database at `~/tinyapps/data/<name>.sqlite` (created on first use, never served over HTTP).
Create the schema and seed data yourself with Python's sqlite3 (the `sqlite3` CLI is not installed):

```bash
python3 - <<'PY'
import sqlite3, pathlib
db = pathlib.Path.home() / "tinyapps/data/todo.sqlite"
db.parent.mkdir(parents=True, exist_ok=True)
con = sqlite3.connect(db, timeout=5)
con.execute("PRAGMA journal_mode=WAL")
with con:
    con.execute("CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY, title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0)")
print(con.execute("SELECT sql FROM sqlite_master").fetchall())
PY
```

- Read the current schema (`SELECT sql FROM sqlite_master`) before changing it.
- Change the schema and the HTML together so the app never breaks; prefer additive changes (`ALTER TABLE ... ADD COLUMN`).
- Keep transactions short; the app may be writing at the same time.
- Ask before dropping tables or deleting rows the user created.

## Delete

Only when the user asks. Deletion is permanent (an app's database goes with it):

```bash
python3 ~/dev/tinyapps/server.py delete apps <name>
python3 ~/dev/tinyapps/server.py delete artifacts <name>
```

## Promote an artifact to an app

`mv ~/tinyapps/web/artifacts/<name>.html ~/tinyapps/web/apps/<name>.html`, then add `app.sql` calls and the schema.

## Check your work

`curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/apps/<name>` should print 200.
If the server is down: `systemctl --user status tinyapps`.
