# SETUP — Boundary Editor & Plaque Editor (standalone second machine)

## What this is

This repo runs the **Boundary Editor** and **Plaque Editor** as a single local
Flask web app on port **5051**. Each machine runs its own copy with its own
`db/workspace.db`. Course folders (`ItWentIn/GolfCourses/`) come with the
clone. There is no network mount, no cloud sync, no shared state. Writes on
your machine stay on your machine.

## Prerequisites

- **Python 3.13** — the pins in `requirements.txt` were resolved against 3.13
  wheels. See the "Install" step below for how to get by with 3.12 if you must.
  The cleanest path on macOS/Linux is `pyenv`:
  ```bash
  brew install pyenv       # macOS; use your package manager on Linux
  pyenv install 3.13.1
  pyenv local 3.13.1       # inside the repo root
  ```
- **Homebrew** (macOS) — needed for `pyenv` and handy for `git`. Install with
  the official one-liner:
  ```bash
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  ```
  When it finishes it prints a **"Next steps"** section with two or three
  lines (typically `echo >> ~/.zprofile`, `echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile`,
  and `eval "$(/opt/homebrew/bin/brew shellenv)"`). Run those lines exactly as
  printed, then confirm with `brew --version`.
- **git**
- **~3 GB free disk** for the clone (course folders are in the repo).
- **macOS or Linux**. The app assumes a POSIX shell (`run.sh`) and calls the
  macOS `open` command to hand `.3mf` files to Bambu Studio. On Linux `open`
  won't exist — the editor itself still works, but the "open in slicer"
  convenience button will report an error. Windows is unsupported out of
  the box (no `run.sh`, no `open`).

## Install

```bash
git clone https://github.com/quadrabyte1/Claude_2027.git Claude_2027
cd Claude_2027/SHARED_WORK_FOLDER
python3.13 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

`requirements-optional.txt` is **not needed for the editors**. It holds extras
for one of Thomas's one-off helper scripts (`clean_photo_lama.py`) and has its
own install instructions in the file header. Skip it.

**If you are stuck on Python 3.12**, two pins need loosening (both have 3.12
wheels, but not at the exact pinned version):

- `numpy==2.4.2` → `numpy>=2.1,<2.5`
- `pillow==12.1.1` → `pillow>=11,<13`

Edit `requirements.txt` locally (don't commit the change — it'll drift from
Thomas's machine) and re-run `pip install -r requirements.txt`. Everything
else in the file has 3.12 wheels at the pinned versions.

**Python 3.11 and older are not supported.** `numpy 2.x` dropped 3.10 support
and the pinned `shapely`/`trimesh` versions assume `numpy 2.x`.

## Workspace DB

The Flask app reads team/task/course rows from `db/workspace.db`. Standalone
users should **copy Thomas's current `workspace.db` once** as a starting
point:

```bash
scp thomas@<thomas-host>:/path/to/SHARED_WORK_FOLDER/db/workspace.db ./db/workspace.db
```

Heads-up: because each machine has its own copy, **writes you make on your
machine (new tasks, edits, closed rows) will not propagate back to Thomas**.
That's intentional and fine for standalone editor use. If you want to pull a
fresh copy later, overwrite the file (make a backup first).

## Run

```bash
cd app
./run.sh
```

Then open:

- Dashboard:       <http://localhost:5051/>
- Boundary Editor: <http://localhost:5051/editor>
- Plaque Editor:   <http://localhost:5051/plaque>

Port **5051** must be free. Logs stream to `app/logs/server.log`.

## Auto-start at login (macOS)

Optional. Two user LaunchAgents keep the server running and open the browser
tabs after login. From the SHARED_WORK_FOLDER root, run one command:

```bash
scripts/install_autostart.sh
```

It finds the clone from its own location, checks the `.venv` (Python 3.13),
writes and validates both plists, loads them, and waits for the server to
answer on port 5051. Re-running is safe. After a `git pull`, restart the
server with:

```bash
launchctl kickstart -k gui/$(id -u)/com.iwi.editor
```

To remove the agents: `scripts/install_autostart.sh --uninstall`.

## Known limitations

- **Thomas-only helper scripts have hardcoded paths.** The following scripts
  in `app/` contain hardcoded `/Volumes/GIT/Claude_2027/...`
  paths and will not run on your machine without further edits. **None of
  them are used by the Boundary Editor or Plaque Editor routes** — they are
  Thomas's one-shot utilities for unrelated projects (deck/patio mockups,
  Evernote migration, legacy flat-piece generators):
  - `clean_photo_lama.py`
  - `deck_mockup.py`
  - `evernote_migrate.py`
  - `generate_flat_pieces.py`
  - `generate_flat_pieces_checkpoint_a.py`
  - `generate_flat_pieces_hole9.py`
  - `hole9_boundaries.py`
  - `patio_mockup.py`
  - `patio_mockup_vera.py`
  - `patio_mockup_vera_porch.py`
  - `ridge_filter_test.py`

  You can ignore all of these. If you ever need one, swap its hardcoded
  constant for an `os.path.dirname(os.path.abspath(__file__))`-relative path.

- **`/Volumes/GIT/...` paths will not work on your machine.** Thomas's repo
  lives on an external volume. All editor code uses repo-relative paths
  (`os.path.dirname(__file__)` + `..`), so a plain `git clone` into any
  directory works fine. Just don't paste `/Volumes/GIT/Claude_2027/...` paths
  from Thomas's logs/screenshots into your shell.

- **"Open in slicer" button is macOS-only** (uses `/usr/bin/open`). On Linux
  the button will show an error but the 3MF is still written to disk — open
  it yourself.

## Troubleshooting

**Port 5051 already in use.**
```bash
lsof -i :5051           # find the PID
kill <pid>
```

**`ModuleNotFoundError: No module named 'flask'` (or `dotenv`, `cv2`,
`shapely`, or any other package)** — the server was almost certainly started
with plain `python3` (the system/Homebrew interpreter) instead of the venv's
Python. Either activate the venv first (`source .venv/bin/activate` from the
repo root, then `python app.py`), or call the venv interpreter directly from
`app/`: `../.venv/bin/python app.py`. If the module is still missing under
the venv's Python, re-run `pip install -r requirements.txt`.

**`pip install` fails on numpy or pillow** — you're on Python 3.12 and need
the pin loosening described above. If `pip` claims no wheel is available on
3.13 either, your `pip` is stale: `pip install --upgrade pip` and retry.

**`pip install` fails with `ResolutionImpossible` mentioning
`simple-lama-inpainting` and `numpy<2.0.0`** — you have an old checkout of
`requirements.txt`. `simple-lama-inpainting` declares `numpy<2`, which can never
resolve against the `numpy==2.4.2` pin. It is only used by a one-off helper, so
`git pull` (it now lives in `requirements-optional.txt`) or delete the
`simple-lama-inpainting` and `replicate` lines from `requirements.txt`, then
re-run `pip install -r requirements.txt`.

**`ERROR: No matching distribution found for numpy` / "no matching
distributions available"** — the venv was built with the wrong Python (e.g.
macOS's system `python3`, which is 3.9). Check:
```bash
.venv/bin/python --version     # must say 3.13.x
```
If not, delete and recreate it with 3.13:
```bash
deactivate 2>/dev/null; rm -rf .venv
python3.13 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**Editor loads but course dropdowns are empty** — `ItWentIn/GolfCourses/`
is missing; check you ran the app from the cloned `SHARED_WORK_FOLDER`.

**Editor loads but no team/task data on sidebar** — `db/workspace.db` is
missing. See the "Workspace DB" section above.
