# Contributing

Issues and pull requests are welcome. This file covers what is not obvious
from the tree.

## Running from a checkout

```bash
./scripts/install-arch.sh --check      # or install-debian.sh --check
./run.sh                               # or: python3 -m xeneon_edge
./scripts/layout-editor.py             # the editor, on the main monitor
```

GTK4, libadwaita, WebKitGTK 6.0 and PyGObject come from the distribution
package manager, not from pip — Arch and Debian mark their Python as
externally managed. `pyproject.toml` exists for metadata and tooling.

## Checks before a pull request

```bash
python3 -m compileall -q xeneon_edge scripts
ruff check .                           # config in pyproject.toml; `uvx ruff check .` works too
bash -n scripts/*.sh
node --check xeneon_edge/editor/assets/editor.js
```

The same runs in CI (`.github/workflows/ci.yml`). There is no test suite
yet; the sensor and store modules are plain functions and are
the right place to start one.

## Conventions

- **Commits:** `type(scope): summary` — types `feat`, `fix`, `perf`, `docs`,
  `chore`, `refactor`, `test`; scopes `linux`, `editor`, `readme`. The
  summary says what changed for the user, the body says why.
- **Modules** (`xeneon_edge/modules/`): a module is a `Gtk.Widget` with
  `update(snapshot)` and a `ModuleSpec` (type id, label, factory, `needs`,
  `schema`). The editor renders its settings form from `schema`; the
  aggregator polls only what visible modules declare in `needs`. Keep new
  sensor sources behind the same "return `None` on failure" contract the
  existing ones use so the aggregator can fall back.
- **Never block the GTK main loop.** Sensors run in the aggregator thread and
  hand snapshots over with `GLib.idle_add`; subprocess calls carry timeouts.
- **Comments explain why**, including the measurement that led to a decision.
  Existing comments are partly German; user-facing strings (editor, module
  labels and help, tooltips, status texts) are English, keep new ones English
  too. Journal log lines (`[xeneon-edge] …`) are still German.
- **Config files:** `layout.json` is versioned (`VERSION` in
  `layout_store.py`); a schema change needs a migration in `_from_vN()` so
  existing files keep loading.

## Reporting a problem

Include the distribution, GTK version (`pkg-config --modversion gtk4`), the
output of `./scripts/verify-install.py`, and the dashboard journal:

```bash
journalctl --user -u 'app-xeneon\x2dedge@autostart.service' -n 200
```
