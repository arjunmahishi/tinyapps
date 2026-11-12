---
name: tinyapps
description: Create, update and delete single-file HTML apps (with a SQLite database) and static artifacts served by tinyapps.
---
# tinyapps

Base URL: `<TINYAPPS_BASE_URL>`. If this is a placeholder, ask the user for the URL they open tinyapps at and replace it in this file.

- App (saves data): `~/tinyapps/web/apps/<name>.html` → `<base>/apps/<name>`
- Artifact (static): `~/tinyapps/web/artifacts/<name>.html` → `<base>/artifacts/<name>`
- Database: `~/tinyapps/data/<name>.sqlite`, apps only, never served. Write it directly with Python `sqlite3`.
- Names match `^[a-z0-9][a-z0-9-]{0,62}$`. Writing a file publishes it.

## Sandbox
Pages are one self-contained HTML file (inline or CDN CSS/JS). No storage, cookies, dialogs or popups.
Apps can't make network requests; artifacts can't reach `/api`.

## Data
`await app.sql(sql, params)` runs one statement and returns rows. Use `?` params.
The app and you may write at the same time; keep transactions short.

## Delete (only when asked; permanent)
`rm ~/tinyapps/web/apps/<name>.html ~/tinyapps/data/<name>.sqlite*` or `rm ~/tinyapps/web/artifacts/<name>.html`

## Check
`curl -so /dev/null -w '%{http_code}' http://127.0.0.1:8080/<apps|artifacts>/<name>` → 200. Service: `systemctl --user status tinyapps`.
