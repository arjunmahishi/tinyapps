# tinyapps

A tiny, self-hosted home for AI-built web pages. Ask your agent for a tool or a
page; it writes a single HTML file and replies with a link.

- **Artifacts** — static HTML pages (reports, charts, mockups) at `/artifacts/<name>`.
  Like Claude artifacts, but they persist at a URL.
- **Apps** — HTML pages with their own SQLite database at `/apps/<name>`, reached
  from the page through a small `app.sql()` bridge.

There's no build step, no deploy and no framework: write the file and it's live.
One Python file, standard library only. Built for a single owner on a single
machine, running alongside [Hermes Agent](https://github.com/NousResearch/hermes-agent),
though any agent that can write files works.

## How it works

```text
agent ──writes──▶ ~/tinyapps/web/apps/todo.html
      ──writes──▶ ~/tinyapps/data/todo.sqlite     (directly, with sqlite3)

browser ──▶ /apps/todo          host page
              └─ <iframe sandbox>  /apps/todo/frame  (your HTML + injected app SDK)
                    │ postMessage
                    ▼
            host page ──POST /api/apps/todo/sql──▶ server ──▶ todo.sqlite
```

- Pages run in a sandboxed iframe with an opaque origin and `connect-src 'none'`,
  so app code can't make network requests or touch the host. Its only way
  out is `app.sql()`, which is relayed by the host page.
- The server picks the database from the app name in the URL, never from the
  request, and only accepts API calls from its own host.
- Code and content are separate: this repo holds the server; pages and
  databases live in `~/tinyapps/`, so they never end up in git and databases
  are never served over HTTP.

## Writing an app

One self-contained HTML file. CDN scripts are fine.

```html
<!doctype html>
<html>
<head><title>todo</title></head>
<body>
  <ul id="list"></ul>
  <script>
    (async () => {
      await app.sql("CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY, title TEXT)");
      const [{ id }] = await app.sql("INSERT INTO todos (title) VALUES (?) RETURNING id", ["milk"]);
      const rows = await app.sql("SELECT id, title FROM todos ORDER BY id");
      document.getElementById("list").innerHTML = rows.map((r) => `<li>${r.title}</li>`).join("");
    })().catch((err) => document.body.append(`Error: ${err.message}`));
  </script>
</body>
</html>
```

`app.sql(sql, params)` runs one statement and resolves to an array of row
objects. Use `?` parameters for values and `RETURNING` for new ids.

Because of the sandbox, pages can't use `localStorage`, `fetch`/XHR (apps
only), `alert`/`confirm`, popups or form submission.

## Install

Requires Python 3.10+ and, for the service, systemd.

```bash
git clone <this repo> ~/dev/tinyapps
cd ~/dev/tinyapps
python3 -m unittest test_server        # optional
python3 server.py                      # serves ~/tinyapps on :8080
```

Settings (environment variables):

| Variable | Default | Purpose |
|---|---|---|
| `TINYAPPS_HOME` | `~/tinyapps` | Content folder (`web/` and `data/`) |
| `TINYAPPS_PORT` | `8080` | Listen port (binds all interfaces) |

### Run as a service

`tinyapps.service` is a systemd user unit tied to `hermes-gateway.service`, so
it starts and stops with the agent. For a different agent, or to run it on its
own, edit the `After`, `PartOf` and `WantedBy` lines (for example
`WantedBy=default.target`).

```bash
systemctl --user link ~/dev/tinyapps/tinyapps.service
systemctl --user enable --now tinyapps
```

### Teach the agent

`skill/SKILL.md` is a [Hermes skill](https://hermes-agent.nousresearch.com/docs/developer-guide/creating-skills)
that explains how to create, update and delete apps and artifacts, and how to
manage app databases. Set the base URL in it to wherever you serve tinyapps,
then copy it in:

```bash
mkdir -p ~/.hermes/skills/productivity/tinyapps
cp skill/SKILL.md ~/.hermes/skills/productivity/tinyapps/
```

It's plain Markdown, so other agents can use it as instructions too.

## Managing content

```bash
ls ~/tinyapps/web/apps ~/tinyapps/web/artifacts
python3 server.py delete apps <name>        # removes the page and its database
python3 server.py delete artifacts <name>
```

Names are lowercase letters, digits and dashes. Deletion is permanent, so back
up `~/tinyapps/data/`.

## Security notes

tinyapps has no login. It's meant for a trusted network or to sit behind an
authenticating proxy such as Cloudflare Tunnel + Zero Trust Access. Anyone who
can reach it can open every page and read or change every app's data.

App code has full control of its own database. Pages can load scripts from
the internet, so treat them as only partly isolated.
