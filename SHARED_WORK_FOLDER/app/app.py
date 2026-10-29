"""
AI Team Workspace — Flask application
Serves a Notion-like UI over the workspace SQLite database.
"""

import os
import re
import sqlite3
import hashlib
import time
from datetime import datetime, date
from pathlib import Path

import heatmap_degrid
import dependency_preflight
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from flask import (
    Flask, render_template, request, redirect, url_for, g, abort, jsonify,
    send_from_directory,
)

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "workspace.db")

APP_VERSION = "v6.07"  # unified version for all main-app pages, shown in every sticky footer

# Tier -> concrete model (single source of truth for Team page + Dashboard).
# Keep in sync with the mapping in team/README.md.
MODEL_VERSIONS = {
    "fable":  {"label": "Fable 5.1",  "id": "claude-fable-5-1"},
    "opus":   {"label": "Opus 5.5",   "id": "claude-opus-5-5"},
    "sonnet": {"label": "Sonnet 5.5", "id": "claude-sonnet-5-5"},
    "haiku":  {"label": "Haiku 5.5",  "id": "claude-haiku-5-5"},
}


def model_info(tier):
    """Return {"label", "id"} for a tier; unknown/empty tiers fall back to the raw name."""
    t = (tier or "sonnet").strip().lower()
    return MODEL_VERSIONS.get(t, {"label": (tier or t).capitalize(), "id": tier or t})


# ── Heat-map degrid (task #590) ────────────────────────────────────────────
# Create New Project shows a copy of the heat-map PNG with its baked-in background
# grid erased (heatmap_degrid.py).  The cleaned copy is saved NEXT TO the original
# as "<stem>__degridded.png"; the original is never modified.
# Boundary detection: compared on 5 holes (Delaveaga 5/11/15, Stanford 3/8) -- identical
# green results, trap IoU within +/-0.3%, no systematic gain.  During the classifier-
# tuning phase detection therefore keeps using the ORIGINAL; flip this to feed it the
# cleaned image.
DEGRID_DETECT_ON_CLEANED = False
EGM_IMAGE_URL_FMT = "/egm/images/{course}/{filename}"
TEAM_INBOX_URL_FMT = "/team_inbox/{filename}"
IMAGE_EXTS = (".png", ".jpg", ".jpeg")

# ═══ APP CONSTANTS (editor / boundary / generation) ═══════════════════════════
# Coding Standard "Named Constants, No Literals" (CLAUDE.md): every meaningful value the
# editor-facing server code uses is defined ONCE here.  Values that must stay equal to a
# constant in templates/editor.html are tagged "editor: NAME"; the guard test
# tests/test_editor_server_constants_sync.py reads the editor block (editor_constants.value)
# and asserts equality, so the two sides cannot drift apart.
# PRINT_SIZE_MM / FRINGE_XY_EXPANSION_MM / grid clamps / grid resolutions are NOT redefined
# here: the generator modules own them (generate_stl_3mf.py, gradient_surface_diagnostic.py)
# and the routes import them lazily from there (a top-level import would pull in trimesh).

# ── Server ──
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5051
SERVER_USE_RELOADER = True

# ── HTTP status codes ──
HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404
HTTP_CONFLICT = 409
HTTP_SERVER_ERROR = 500
HEADER_CACHE_CONTROL = "Cache-Control"
CACHE_NO_STORE = "no-store"
HEADER_CONTENT_TYPE = "Content-Type"
CONTENT_TYPE_PNG = "image/png"
GPS_PREVIEW_CACHE_HEADER = "X-GPS-Preview-Cache"
GPS_PREVIEW_CACHE_HIT = "hit"
GPS_PREVIEW_CACHE_MISS = "miss"

# ── JSON envelope ──
KEY_STATUS = "status"
KEY_MSG = "msg"
STATUS_OK = "ok"
STATUS_ERROR = "error"

# ── Route strings (editor: API_* in the EDITOR CONSTANTS block) ──
ROUTE_EDITOR = "/editor"
ROUTE_API_TASKS_RUNNING_COUNT = "/api/tasks/running_count"   # editor: API_RUNNING_TASKS_COUNT
ROUTE_API_DEGRID_IMAGE = "/api/degrid_image"
ROUTE_API_IMAGES = "/api/images"                             # editor: API_IMAGES
ROUTE_API_COURSES = "/api/courses"                           # editor: API_COURSES
ROUTE_TEAM_INBOX = "/team_inbox/<path:filename>"             # editor: IMAGE_URL_TEAM_INBOX (prefix)
ROUTE_EGM_IMAGE = "/egm/images/<path:course>/<path:filename>"  # editor: IMAGE_URL_EGM_IMAGES (prefix)
ROUTE_API_BOUNDARIES = "/api/boundaries"                     # editor: API_BOUNDARIES
ROUTE_API_BOUNDARIES_LIST = "/api/boundaries/list"           # editor: API_BOUNDARIES_LIST
ROUTE_API_BOUNDARIES_LOAD_PATH = "/api/boundaries/load_path"   # editor: API_BOUNDARIES_LOAD_PATH (full-path load, ?path=)
ROUTE_API_BOUNDARIES_LOAD = "/api/boundaries/load"           # editor: API_BOUNDARIES_LOAD
ROUTE_API_PRINT_CONSTANTS = "/api/print_constants"           # editor: API_PRINT_CONSTANTS
ROUTE_API_DETECT_BOUNDARIES = "/api/detect_boundaries"       # editor: API_DETECT_BOUNDARIES
ROUTE_API_FIND_CONTOURS = "/api/find_contours"               # editor: API_FIND_CONTOURS
ROUTE_API_GENERATE_MODELS = "/api/generate_models"           # editor: API_GENERATE_MODELS
ROUTE_API_DEPENDENCIES = "/api/dependencies"                 # GET: generation dependency status
ROUTE_API_GPS_HEIGHTMAP_PREVIEW = "/api/gps_heightmap_preview"  # editor: API_GPS_HEIGHTMAP_PREVIEW
ROUTE_API_GPS_FILES = "/api/gps_files"                       # editor: API_GPS_FILES
ROUTE_DIAGNOSTIC_ARROWS = "/diagnostic/arrows"
ROUTE_PLAQUE = "/plaque"
ROUTE_API_FONTS = "/api/fonts"
ROUTE_API_GENERATE_PLATE = "/api/generate_plate"
METHOD_GET = "GET"
METHOD_POST = "POST"

# ── Query-string / payload keys (editor sends these; names are the wire contract) ──
QUERY_IMAGE = "image"                  # /editor?image=
QUERY_EGM = "egm"                      # /editor?egm=<absolute .egm path>   (editor: initial egm path)
QUERY_PATH = "path"                    # /api/boundaries/load_path?path=     (editor: QUERY_PATH)
QUERY_FILENAME = "filename"            # /api/boundaries/load?filename=   (editor: QUERY_FILENAME)
QUERY_COURSE = "course"                # /api/gps_files?course=           (editor: QUERY_COURSE)
QUERY_GPS_FILE = "gps_file"
QUERY_BBOX = "bbox"
QUERY_APPROACH_M = "approach_m"
QUERY_GRID_SIZE = "grid_size"
KEY_IMAGE = "image"                    # detect_boundaries / find_contours / degrid_image payload
KEY_COURSE = "course"
KEY_IMAGE_COURSE = "imageCourse"
KEY_GREEN_POINTS = "green_points"      # find_contours payload
KEY_HOLE = "hole"                      # generate_models payload (also the saved-EGM key)
KEY_INCLUDE_BOUNDARY_REGION = "includeBoundaryRegion"          # generate_models payload
KEY_APPLY_FRINGE_FRAME_CAP = "applyFringeFrameCap"
KEY_INCLUDE_FRINGE_WITHOUT_GRASS = "includeFringeWithoutGrass"
KEY_OPEN_IN_SLICER = "open_in_slicer"
KEY_NAME = "name"                      # create_course payload / image + gps file rows
KEY_FILENAME = "filename"
KEY_URL = "url"
KEY_PATH = "path"
KEY_EGM_PATH = "egm_path"              # save payload / load response: absolute path of the EGM file (editor: KEY_EGM_PATH)
KEY_IMAGE_COURSE = "imageCourse"
KEY_IMAGE_WARNING = "imageWarning"
KEY_FILES = "files"
KEY_FILE = "file"
KEY_TYPE = "type"
KEY_COURSES = "courses"
KEY_PROJECTS = "projects"
KEY_POLYGONS = "polygons"
KEY_POLYGON_COUNT = "polygon_count"
KEY_POINTS = "points"
KEY_X = "x"
KEY_Y = "y"
KEY_IMAGE_SIZE = "imageSize"
KEY_WIDTH = "width"
KEY_HEIGHT = "height"
KEY_CONTOUR_STEP = "contourStep"
KEY_CONTOURS = "contours"
KEY_PRINT_SIZE_MM = "print_size_mm"
KEY_FRINGE_XY_EXPANSION_MM = "fringe_xy_expansion_mm"
KEY_SLICER_OPENED = "slicer_opened"
KEY_SLICER_ERROR = "slicer_error"
KEY_WARNINGS = "warnings"
KEY_FOUND = "found"
KEY_ORIGINAL_URL = "originalUrl"
KEY_DEGRIDDED_URL = "degriddedUrl"
KEY_GPS_BACKEND = "gpsBackend"
KEY_GPS_ENABLED = "enabled"
KEY_GPS_FILE = "gpsFile"
KEY_COURSE_GEOREF = "courseGeoRef"
BBOX_KEYS = ("lat_min", "lng_min", "lat_max", "lng_max")

# ── Folders / files / extensions ──
DIR_GOLF_COURSES_PARENT = "ItWentIn"
DIR_GOLF_COURSES = "GolfCourses"
DIR_TEAM_INBOX = "team_inbox"
DIR_OWNER_INBOX = "owner_inbox"
COURSE_SUBDIR_3MFS = "3MFs"
COURSE_SUBDIR_EGMS = "EGMs"
COURSE_SUBDIR_IMAGES = "Images"
COURSE_SUBDIRS = (COURSE_SUBDIR_3MFS, COURSE_SUBDIR_EGMS, COURSE_SUBDIR_IMAGES)   # no STLs/
EXT_EGM = ".egm"
FILE_TYPE_3MF = "3mf"
EXT_3MF = "." + FILE_TYPE_3MF
EXT_GPS = ".gps"
EXT_TXT = ".txt"
GPS_NAME_HINTS = ("gps", "stracka")     # legacy ItWentIn/ files: only these look like GPS data
DEFAULT_COURSE_NAME = "Unknown Course"
DEFAULT_HOLE = "0"
HOLE_LABEL_WIDTH = 2                    # hole "5" -> "05" in filenames
EGM_FILENAME_FMT = "{course} (Hole {hole_label})" + EXT_EGM
THREE_MF_FILENAME_FMT = "{course} (Hole {hole_label})" + EXT_3MF
EGM_JSON_INDENT = 2
HIDDEN_PREFIX = "."
URL_PATH_SEP = "/"
PATH_SEPARATORS = (URL_PATH_SEP, "\\")
PARENT_DIR_TOKEN = ".."

# ── Error / info messages (tests assert on some of these) ──
MSG_NO_IMAGE = "No image specified"
MSG_IMAGE_NOT_FOUND_FMT = "Image not found: {name}"
MSG_CANNOT_READ_IMAGE_FMT = "Cannot read image: {path}"
MSG_COURSE_EMPTY = "Course name must not be empty."
MSG_COURSE_SEPARATORS = "Course name must not contain path separators."
MSG_COURSE_DOT = "Course name must not start with a dot."
MSG_COURSE_INVALID = "Invalid course name."
MSG_COURSE_EXISTS_FMT = "Folder '{name}' already exists."
MSG_INVALID_FILENAME = "Invalid filename"
MSG_FILE_NOT_FOUND = "File not found"
MSG_EGM_PATH_REQUIRED = "path param required"
MSG_EGM_PATH_NOT_ABSOLUTE = "EGM path must be absolute"
MSG_EGM_PATH_BAD_EXT_FMT = "Not an {ext} file"
MSG_EGM_PATH_NOT_FOUND_FMT = "EGM file not found: {path}"
MSG_EGM_PATH_NOT_REGULAR_FMT = "Not a regular file: {path}"
MSG_EGM_IMAGE_MISSING_FMT = "Heat-map image '{image}' for this EGM was not found in GolfCourses/<course>/Images/ (looked in: {courses}). Put the image there to see it."
MSG_NEED_IMAGE_AND_GREEN = "Need image and green_points"
MSG_NO_JSON = "No JSON payload"
MSG_MISSING_COURSE_OR_HOLE = "Missing course or hole"
MSG_EGM_NOT_FOUND_FMT = "EGM file not found: {name}"
MSG_CANNOT_READ_EGM_FMT = "Cannot read EGM: {err}"
MSG_GPS_FILE_REQUIRED = "gps_file param required"
MSG_BBOX_REQUIRED = "bbox param required"
MSG_GPS_FILE_NOT_FOUND_FMT = "GPS file not found: {path}"
MSG_INVALID_BBOX_FMT = "Invalid bbox JSON: {err}"
MSG_MISSING_DEPENDENCY_FMT = "Missing dependency: {err}"
MSG_GPS_HEIGHTMAP_ERROR_FMT = "GPS heightmap error: {err}"
MSG_RENDER_ERROR_FMT = "Render error: {err}"
MSG_GPS_NO_FILE = (
    "gpsBackend.enabled=true but gpsFile is not set. "
    "Select a .gps file in the GPS backend panel."
)
MSG_GPS_FILE_MISSING_FMT = (
    "GPS file not found: {path}. "
    "Upload or select a .gps file in the GPS backend panel."
)
MSG_GPS_NO_GEOREF = (
    "courseGeoRef is not set for this course. "
    "The GPS backend needs the SW and NE corner lat/lng of the course image "
    "in the EGM's courseGeoRef block (the editor no longer has a dialog for this)."
)
MSG_SLICER_TIMEOUT = (
    "Timed out waiting for `open` to hand the file to the slicer. "
    "Try opening it manually in Finder."
)
MSG_SLICER_EXIT_FMT = (
    "`open` exited with code {code}. "
    "Try opening the file manually in Finder."
)

# ── detect_boundaries: defaults, caps, classifier thresholds (HSV, OpenCV scale H 0-179) ──
DETECT_DEFAULT_CONTOUR_STEP_MM = 0.5        # editor: DEFAULT_CONTOUR_STEP_MM
DETECT_MAX_TRAPS = 5
DETECT_MAX_WATERS = 5                       # same cap as traps
DETECT_MIN_BLOB_AREA_PX = 500               # trap / water connected-component floor
DETECT_GREEN_POINTS = 8                     # green polygon resample count
DETECT_HAZARD_POINTS = 16                   # trap / water polygon resample count
DETECT_GREEN_HUE_SPLIT_LO = 30              # non-green hues are < LO or > HI ...
DETECT_GREEN_HUE_SPLIT_HI = 90
DETECT_GREEN_NONGREEN_MIN_SAT = 80          # ... with sat > this ...
DETECT_GREEN_GREENHUE_MIN_SAT = 120         # ... green hues need sat > this
DETECT_GREEN_MIN_VAL = 80
DETECT_GREEN_CLOSE_KERNEL = 15
DETECT_GREEN_CLOSE_ITERATIONS = 5
DETECT_GREEN_BLUR_KERNEL = 21
DETECT_MASK_THRESHOLD = 127                 # binarise a blurred 0/255 mask at mid-grey
DETECT_MASK_ON = 255
DETECT_TRAP_HUE = (10, 40)                  # widened from [15,34] to catch light beige (Stanford H8)
DETECT_TRAP_SAT = (15, 60)
DETECT_TRAP_MIN_VAL = 200
DETECT_HAZARD_CLOSE_KERNEL = 11
DETECT_HAZARD_CLOSE_ITERATIONS = 3
DETECT_HAZARD_OPEN_KERNEL = 7
DETECT_HAZARD_OPEN_ITERATIONS = 2
DETECT_WATER_BLUE_HUE = (100, 130)          # high-saturation path: royal blue / bright cyan
DETECT_WATER_BLUE_MIN_SAT = 130
DETECT_WATER_BLUE_VAL = (130, 220)
DETECT_WATER_PALE_HUE = (80, 105)           # pale-cyan path (2026-09-28)
DETECT_WATER_PALE_SAT = (15, 50)
DETECT_WATER_PALE_MIN_VAL = 200
DETECT_POLY_SMOOTH_KERNEL = 15              # Gaussian blur before resampling trap/water outlines
DETECT_ARC_EPSILON = 1e-9
# Contour-band classification (currently disabled in the response, kept for the debug path)
DETECT_BAND_RANGES = [
    (85, 100),   # 0: blue/cyan
    (65, 84),    # 1: teal
    (45, 64),    # 2: green
    (25, 44),    # 3: yellow-green / yellow
    (15, 24),    # 4: orange
    (5, 14),     # 5: red-orange
    (0, 4),      # 6: dark red (low end)
]
DETECT_BAND_MIN_SAT = 40
DETECT_BAND_MIN_VAL = 60
DETECT_BAND_RED_WRAP_HUE = (175, 180)
DETECT_BAND_RED_WRAP_INDEX = 6
DETECT_BAND_CLEAN_KERNEL = 7
DETECT_BAND_CLOSE_ITERATIONS = 2
DETECT_BAND_PRESENT_MIN_PX = 200
DETECT_BAND_DILATE_KERNEL = 5
DETECT_BAND_DILATE_ITERATIONS = 2
DETECT_ISOLINE_MIN_BOUNDARY_PX = 50
DETECT_ISOLINE_MIN_PIXELS = 20
DETECT_ISOLINE_MERGE_KERNEL = 11
DETECT_ISOLINE_MERGE_ITERATIONS = 3
DETECT_ISOLINE_MIN_POINTS = 4
DETECT_ISOLINE_POINTS = 10
CONTOUR_DIRECTION_LEFT = "left"
CONTOUR_DIRECTION_RIGHT = "right"
POLY_TYPE_GREEN = "green"
POLY_TYPE_TRAP = "trap"
POLY_TYPE_WATER = "water"
POLY_TYPE_CONTOUR = "contour"
POLY_NAME_GREEN = "Green"
POLY_NAME_TRAP_FMT = "Trap {n}"
POLY_NAME_WATER_FMT = "Water {n}"
POLY_NAME_CONTOUR_FMT = "Contour {n}"
KEY_CLOSED = "closed"
KEY_DIRECTION = "direction"

# ── generate_models ──
SLICER_OPEN_COMMAND = "open"                # macOS: hand the file to the .3mf association
SLICER_OPEN_TIMEOUT_S = 10

# ── GPS heightmap preview (defaults mirror the editor's gpsBackend panel) ──
GPS_PREVIEW_DEFAULT_APPROACH_M = 8.0        # editor: DEFAULT_GPS_APPROACH_M
GPS_PREVIEW_DEFAULT_GRID_SIZE = 100         # preview-only (editor default 200 is for the final model)
GPS_PREVIEW_GRID_MIN = 50
GPS_PREVIEW_GRID_MAX = 300
GPS_PREVIEW_VERT_EXAG = 1.0                 # no exaggeration in preview
GPS_PREVIEW_FIGSIZE = (3, 3)
GPS_PREVIEW_DPI = 100
GPS_PREVIEW_CMAP = "terrain"
GPS_PREVIEW_COLORBAR = {"fraction": 0.046, "pad": 0.04, "label": "mm"}
GPS_PREVIEW_TITLE_FONTSIZE = 8
GPS_PREVIEW_TIGHT_PAD = 0.5
GPS_PREVIEW_BACKEND = "Agg"

# ── Plaque / e-mail ──
SMTP_DEFAULT_PORT = "587"
SMTP_DEFAULT_TO = "quadrabyte@pm.me"
SMTP_TIMEOUT_S = 15
PLATE_FONT_FAMILY = "Helvetica"
PLATE_DEFAULT_SLUG = "custom_plate"
PLATE_SLUG_STRIP_RE = r'[^\w\- ]+'
PLATE_BOLD = False
PLATE_ITALIC = False
PLATE_DOWNLOADS_FMT = "~/Downloads/{name}"
# ═══ END APP CONSTANTS ════════════════════════════════════════════════════════

# ── detect_boundaries: classifier knobs ────────────────────────────────────
# When True the green polygon interior is excluded from trap/water detection.
# This prevents the slope-gradient color bands on the putting surface from
# being misclassified as water or sand.  Set to False only for edge cases
# where a real hazard exists inside the green perimeter (e.g., island holes).
MASK_GREEN_INTERIOR_FROM_HAZARDS = True

# ── Display baseline for task counts ──────────────────────────────────────
# Dashboard task counts only reflect tasks with id strictly greater than the
# baseline stored in system_config (key='task_count_baseline_id'). The value
# is pinned on first boot to the current MAX(id) FROM tasks so historical /
# imported rows stay hidden and only current-session-and-beyond work counts.
# Populated at init_db() time; falls back to a live lookup if unset.
_TASK_COUNT_BASELINE_MAX_ID = 0

# ── Database initialisation ────────────────────────────────────────────────

_SCHEMA_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "db", "schema.sql"
))


def init_db():
    """Ensure all required tables exist and run lightweight migrations.

    On a fresh clone (no workspace.db), sourcing db/schema.sql creates every
    table, index, and seed row in one shot. The migrations below remain for
    the benefit of pre-schema.sql databases where columns were added via
    ALTER TABLE at different points in history.
    """
    # Make sure the containing db/ directory exists before SQLite opens it —
    # matters on a fresh clone where the folder may not exist yet.
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    # Apply the canonical schema (idempotent — every statement uses IF NOT
    # EXISTS / INSERT OR IGNORE). This bootstraps a brand-new DB in one call
    # and is a no-op against an existing one.
    if os.path.exists(_SCHEMA_PATH):
        with open(_SCHEMA_PATH) as _f:
            db.executescript(_f.read())
    db.execute("""
        CREATE TABLE IF NOT EXISTS token_usage (
            id INTEGER PRIMARY KEY,
            month TEXT NOT NULL UNIQUE,
            tokens_purchased INTEGER NOT NULL DEFAULT 0,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
    """)
    # Migration: add model column to team_members if missing
    cols = [row[1] for row in db.execute("PRAGMA table_info(team_members)").fetchall()]
    if "model" not in cols:
        db.execute("ALTER TABLE team_members ADD COLUMN model TEXT NOT NULL DEFAULT 'sonnet'")
    # Migration: add start_date column to token_usage if missing
    tu_cols = [row[1] for row in db.execute("PRAGMA table_info(token_usage)").fetchall()]
    if "start_date" not in tu_cols:
        db.execute("ALTER TABLE token_usage ADD COLUMN start_date TEXT")
    # Migration: add started_at column to tasks if missing
    task_cols = [row[1] for row in db.execute("PRAGMA table_info(tasks)").fetchall()]
    if "started_at" not in task_cols:
        db.execute("ALTER TABLE tasks ADD COLUMN started_at TEXT")
        db.execute("UPDATE tasks SET started_at = created_at WHERE started_at IS NULL")
    # Migration: create life_areas table if missing
    db.execute("""
        CREATE TABLE IF NOT EXISTS life_areas (
            id          INTEGER PRIMARY KEY,
            name        TEXT    NOT NULL UNIQUE,
            icon        TEXT,
            color       TEXT,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
    """)
    # Migration: create life_items table if missing
    db.execute("""
        CREATE TABLE IF NOT EXISTS life_items (
            id              INTEGER PRIMARY KEY,
            title           TEXT    NOT NULL,
            notes           TEXT,
            area_id         INTEGER REFERENCES life_areas(id) ON DELETE SET NULL,
            priority        TEXT    NOT NULL DEFAULT 'normal'
                                   CHECK (priority IN ('urgent', 'high', 'normal', 'low')),
            status          TEXT    NOT NULL DEFAULT 'open'
                                   CHECK (status IN ('open', 'done', 'snoozed', 'cancelled')),
            due_date        TEXT,
            recur_rule      TEXT,
            recur_interval  INTEGER,
            recur_anchor    TEXT,
            snoozed_until   TEXT,
            escalation_days INTEGER DEFAULT 3,
            completed_at    TEXT,
            created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_life_items_area_id  ON life_items(area_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_life_items_status   ON life_items(status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_life_items_due_date ON life_items(due_date)")
    # Seed life_areas with 7 defaults (idempotent)
    for name, icon, color, sort_order in [
        ("Home",            "🏠", "#8B5CF6", 1),
        ("Health",          "💪", "#10B981", 2),
        ("Finance",         "💰", "#F59E0B", 3),
        ("Relationships",   "👥", "#EC4899", 4),
        ("Career",          "💼", "#3B82F6", 5),
        ("Personal Growth", "📚", "#6366F1", 6),
        ("Admin & Errands", "📋", "#6B7280", 7),
    ]:
        db.execute(
            "INSERT OR IGNORE INTO life_areas (name, icon, color, sort_order) VALUES (?, ?, ?, ?)",
            (name, icon, color, sort_order),
        )
    # Migration: fix Hollis's missing persona_file column
    db.execute(
        """UPDATE team_members SET persona_file='team/hollis.md',
           updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
           WHERE name='Hollis' AND (persona_file IS NULL OR persona_file = '')"""
    )
    # ── Persona self-healing guardrail (added 2026-09-07 by Reed) ──────────
    # Walk team/*.md on every boot and INSERT OR IGNORE any missing personas
    # back into team_members. Prevents accidental data loss (e.g. a stray
    # DELETE during a migration) from leaving the roster short. INSERT OR
    # IGNORE means existing rows — including any intentional model-tier
    # edits — are never overwritten.
    _backfill_personas(db)
    # ── system_config table + task-count baseline pinning ──────────────────
    # Generic key/value store for cross-boot app settings. Pin the dashboard
    # task-count baseline once, on first boot after this migration, to the
    # current MAX(id) FROM tasks. All future new tasks (id > baseline) show
    # up in the summary counter; imported/historical rows stay hidden.
    db.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    _row = db.execute(
        "SELECT value FROM system_config WHERE key='task_count_baseline_id'"
    ).fetchone()
    if _row is None or _row[0] is None or str(_row[0]).strip() == "":
        _max = db.execute("SELECT COALESCE(MAX(id), 0) FROM tasks").fetchone()[0]
        db.execute(
            "INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)",
            ("task_count_baseline_id", str(int(_max))),
        )
    # Cache into the module-level constant so request handlers avoid a DB
    # round-trip. init_db() is called at import time, so this is populated
    # before the first request.
    global _TASK_COUNT_BASELINE_MAX_ID
    _baseline_row = db.execute(
        "SELECT value FROM system_config WHERE key='task_count_baseline_id'"
    ).fetchone()
    try:
        _TASK_COUNT_BASELINE_MAX_ID = int(_baseline_row[0]) if _baseline_row else 0
    except (TypeError, ValueError):
        _TASK_COUNT_BASELINE_MAX_ID = 0
    db.commit()
    db.close()


def _backfill_personas(db: sqlite3.Connection) -> None:
    """INSERT OR IGNORE any team/*.md persona missing from team_members.

    Extraction rules (kept deliberately narrow so a malformed persona file
    fails soft — it is skipped rather than crashing boot):
      * Name / role come from the H1 heading ``# NAME — ROLE`` (em-dash,
        en-dash, or plain hyphen accepted).
      * Model tier comes from a ``**Model:** <tier>`` line; defaults to
        ``'sonnet'`` if absent.
      * Files starting with ``_hiring_research_`` and ``README.md`` are
        skipped.
    Logs a single ``activity_log`` row when at least one persona is added.
    """
    team_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "team"))
    if not os.path.isdir(team_dir):
        return

    backfilled = []
    # `— ` (em-dash), `– ` (en-dash), or `- ` (hyphen) between name and role.
    h1_re = re.compile(r"^#\s+([^\s#][^\-–—]*?)\s*[—–\-]\s*(.+?)\s*$")
    # Accept either `**Model:** haiku` or `- **Model:** haiku` — both forms
    # appear in the current personas.
    model_re = re.compile(r"^(?:-\s*)?\*\*Model:\*\*\s*([A-Za-z0-9_\-]+)")

    for fname in sorted(os.listdir(team_dir)):
        if not fname.endswith(".md"):
            continue
        if fname.startswith("_hiring_research_") or fname.lower() == "readme.md":
            continue

        path = os.path.join(team_dir, fname)
        name = role = None
        model = "sonnet"
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    if name is None:
                        m = h1_re.match(line)
                        if m:
                            name = m.group(1).strip()
                            role = m.group(2).strip()
                            continue
                    mm = model_re.match(line.strip())
                    if mm:
                        model = mm.group(1).strip().lower()
                        break
        except OSError:
            continue

        if not name or not role:
            continue

        relative_path = f"team/{fname}"
        cur = db.execute(
            """INSERT OR IGNORE INTO team_members (name, role, persona_file, model)
               VALUES (?, ?, ?, ?)""",
            (name, role, relative_path, model),
        )
        if cur.rowcount:
            backfilled.append(name)

    if backfilled:
        db.execute(
            """INSERT INTO activity_log (actor, action, entity_type, details)
               VALUES ('System', 'backfilled_team_members', 'team_member', ?)""",
            (", ".join(backfilled),),
        )


init_db()


# ── Database helpers ────────────────────────────────────────────────────────

# SQLite 3.51.0 (fixed in 3.51.2) can deadlock its unix-VFS mutex when several connections to one file
# open/close concurrently in one process (2026-10-14 hang); serialize in-process DB use with this lock.
import threading, faulthandler
_DB_LOCK = threading.Lock()
_DB_HELD_SINCE = [0.0]
_WEDGE_LOG = os.path.join(os.path.dirname(__file__), "logs", "db_wedge.log")


def _db_lock_acquire():
    if _DB_LOCK.acquire(timeout=10):
        _DB_HELD_SINCE[0] = time.time()
        return True
    return False  # wedged: proceed unserialized rather than hang forever


def _db_lock_release(held):
    if held:
        _DB_HELD_SINCE[0] = 0.0
        _DB_LOCK.release()


def _db_watchdog():
    while True:
        time.sleep(5)
        t = _DB_HELD_SINCE[0]
        if t and time.time() - t > 20:
            try:
                os.makedirs(os.path.dirname(_WEDGE_LOG), exist_ok=True)
                with open(_WEDGE_LOG, "a") as f:
                    f.write(f"\n===== {datetime.now()} DB lock held >20s; all threads =====\n")
                    f.flush()
                    faulthandler.dump_traceback(file=f, all_threads=True)
            except Exception:
                pass
            time.sleep(60)


threading.Thread(target=_db_watchdog, daemon=True).start()


def get_db():
    """Return a per-request database connection with standard PRAGMAs."""
    if "db" not in g:
        g.db_locked = _db_lock_acquire()
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA busy_timeout = 5000")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    held = g.pop("db_locked", False)
    try:
        if db is not None:
            db.close()
    finally:
        _db_lock_release(held)


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    db = get_db()
    db.execute(sql, args)
    db.commit()


# ── Model sync helper ───────────────────────────────────────────────────────

_MODEL_RE = re.compile(r"^\-\s+\*\*Model:\*\*\s*(fable|opus|sonnet|haiku)\s*$", re.MULTILINE)
_VALID_TIERS = {"fable", "opus", "sonnet", "haiku"}


def _sync_team_member_models():
    """For every team_member with a persona_file, read the file, parse the
    **Model:** line, and update the DB row if the stored value differs.

    Edge cases handled:
    - persona_file is NULL or empty: skip (no write).
    - File does not exist or cannot be read: skip (no write).
    - Model line missing or unrecognised value: skip (no write).
    Only writes when a valid opus/sonnet/haiku value is positively parsed.
    """
    members = query("SELECT id, name, model, persona_file FROM team_members")
    db = get_db()
    changed = False
    for m in members:
        pf = m["persona_file"]
        if not pf:
            continue
        # Resolve relative path from repo root (parent of app/)
        full_path = os.path.normpath(os.path.join(_REPO_ROOT, pf))
        try:
            with open(full_path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        match = _MODEL_RE.search(text)
        if not match:
            continue
        declared = match.group(1)
        if declared != m["model"]:
            db.execute(
                "UPDATE team_members SET model=?, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
                (declared, m["id"]),
            )
            changed = True
    if changed:
        db.commit()


# ── Markdown-ish rendering (no deps) ───────────────────────────────────────

def md(text):
    """Minimal markdown to HTML — handles headers, bold, italic, lists,
    code blocks, inline code, links, and paragraphs."""
    if not text:
        return ""
    import html as _html
    text = _html.escape(text)

    # Fenced code blocks
    text = re.sub(
        r"```(\w*)\n(.*?)```",
        lambda m: f'<pre class="bg-[#F7F6F3] rounded-lg p-4 text-sm overflow-x-auto my-4"><code>{m.group(2)}</code></pre>',
        text, flags=re.DOTALL,
    )
    # Inline code
    text = re.sub(r"`([^`]+)`", r'<code class="bg-[#F7F6F3] px-1.5 py-0.5 rounded text-sm">\1</code>', text)
    # Headers
    text = re.sub(r"^#### (.+)$", r'<h4 class="text-base font-semibold mt-6 mb-2 text-[#37352F]">\1</h4>', text, flags=re.MULTILINE)
    text = re.sub(r"^### (.+)$", r'<h3 class="text-lg font-semibold mt-6 mb-2 text-[#37352F]">\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r"^## (.+)$", r'<h2 class="text-xl font-semibold mt-8 mb-3 text-[#37352F]">\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r"^# (.+)$", r'<h1 class="text-2xl font-bold mt-8 mb-4 text-[#37352F]">\1</h1>', text, flags=re.MULTILINE)
    # Bold + italic
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Links
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" class="text-[#2383E2] hover:underline">\1</a>', text)
    # Unordered lists
    text = re.sub(r"^- (.+)$", r'<li class="ml-4 list-disc">\1</li>', text, flags=re.MULTILINE)
    # Wrap consecutive <li> in <ul>
    text = re.sub(
        r"((?:<li[^>]*>.*?</li>\n?)+)",
        r'<ul class="my-3 space-y-1">\1</ul>',
        text,
    )
    # Paragraphs — wrap remaining bare lines
    lines = text.split("\n")
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append("")
        elif stripped.startswith("<"):
            out.append(line)
        else:
            out.append(f'<p class="my-2 leading-relaxed">{stripped}</p>')
    return "\n".join(out)


app.jinja_env.filters["md"] = md


def format_elapsed(seconds):
    if seconds >= 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}m"
    elif seconds >= 60:
        m = seconds // 60
        s = seconds % 60
        return f"{m}m {s}s"
    else:
        return f"{seconds}s"

app.jinja_env.filters["elapsed"] = format_elapsed


# ── Helpers for templates ──────────────────────────────────────────────────

@app.context_processor
def inject_now():
    return {"now": datetime.utcnow(), "today": date.today().isoformat()}


@app.context_processor
def _inject_app_version():
    return {"app_version": APP_VERSION, "model_info": model_info,
            "model_versions": MODEL_VERSIONS}


def _is_htmx():
    return request.headers.get("HX-Request") == "true"


def render(template, **kwargs):
    """Render a template. For HTMX requests, is_htmx=True is passed so
    base.html skips the layout shell and returns only the content block."""
    kwargs["is_htmx"] = _is_htmx()
    return render_template(template, **kwargs)


# ── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    _sync_team_member_models()
    team = query("SELECT * FROM team_members ORDER BY name")
    _status_rows = query(
        "SELECT status, COUNT(*) AS c FROM tasks WHERE id > ? GROUP BY status",
        (_TASK_COUNT_BASELINE_MAX_ID,),
    )
    task_counts = {"total": sum(r["c"] for r in _status_rows)}
    for r in _status_rows:
        task_counts[r["status"]] = r["c"]
    # Ensure keys are always present even if no rows exist
    for _s in ("pending", "in_progress", "done", "cancelled"):
        task_counts.setdefault(_s, 0)

    # Per-member in-progress count (full table — reflects reality, not baselined)
    member_active_counts = {
        row["assigned_to"]: row["c"]
        for row in query(
            "SELECT assigned_to, COUNT(*) AS c FROM tasks"
            " WHERE status='in_progress' AND assigned_to IS NOT NULL"
            " GROUP BY assigned_to"
        )
    }
    journal_count = query("SELECT COUNT(*) as c FROM journal_entries", one=True)["c"]

    from datetime import datetime
    updated_at = datetime.now().strftime("%-m/%-d/%Y %H:%M:%S")

    now = datetime.utcnow()
    busy_tasks = {}
    for row in query(
        "SELECT assigned_to, MIN(started_at) as started_at FROM tasks WHERE status='in_progress' AND assigned_to IS NOT NULL AND started_at IS NOT NULL GROUP BY assigned_to"
    ):
        try:
            started = datetime.strptime(row["started_at"], "%Y-%m-%dT%H:%M:%SZ")
            busy_tasks[row["assigned_to"]] = int((now - started).total_seconds())
        except (ValueError, TypeError):
            busy_tasks[row["assigned_to"]] = 0

    recently_done = {row["assigned_to"] for row in query(
        """SELECT DISTINCT assigned_to FROM tasks
           WHERE status='done' AND assigned_to IS NOT NULL
           AND completed_at > strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-60 seconds')
           /* AND (julianday(completed_at) - julianday(started_at)) * 86400 >= 120 */"""
    )}

    # Per-member current in-progress task (most recently started)
    member_current_tasks = {
        row["assigned_to"]: {"title": row["title"], "description": row["description"] or ""}
        for row in query(
            "SELECT assigned_to, title, description FROM tasks"
            " WHERE status='in_progress' AND assigned_to IS NOT NULL AND started_at IS NOT NULL"
            " GROUP BY assigned_to HAVING started_at = MAX(started_at)"
        )
    }

    # Per-member last activity entry (most recent by created_at)
    _activity_rows = query(
        "SELECT actor, action, details, created_at FROM activity_log"
        " ORDER BY created_at DESC LIMIT 200"
    )
    member_last_activity = {}
    for _row in _activity_rows:
        _actor = _row["actor"]
        if _actor and _actor not in member_last_activity:
            member_last_activity[_actor] = {
                "action": _row["action"],
                "details": _row["details"] or "",
                "created_at": _row["created_at"],
            }

    return render("dashboard.html", team=team,
                   task_counts=task_counts,
                   journal_count=journal_count, updated_at=updated_at,
                   busy_tasks=busy_tasks, recently_done=recently_done,
                   member_active_counts=member_active_counts,
                   member_current_tasks=member_current_tasks,
                   member_last_activity=member_last_activity)


# ── Research documents helpers ─────────────────────────────────────────────

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_RESEARCH_DIRS = {
    "Hiring":  os.path.join(_REPO_ROOT, "Team"),
    "Topical": os.path.join(_REPO_ROOT, "owner_inbox"),
}


def _research_title(filepath):
    """Return the first # heading from the file, falling back to the filename stem."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("# "):
                    return line[2:].strip()
    except OSError:
        pass
    stem = os.path.splitext(os.path.basename(filepath))[0]
    return stem.replace("_", " ").replace("-", " ").title()


def _collect_research_docs():
    """Return list of dicts for all research Markdown files, newest-first by mtime."""
    docs = []
    for badge, dirpath in _RESEARCH_DIRS.items():
        if not os.path.isdir(dirpath):
            continue
        for fname in os.listdir(dirpath):
            if badge == "Hiring":
                if not (fname.startswith("_hiring_research_") and fname.endswith(".md")):
                    continue
            else:  # Topical
                if not ("research" in fname.lower() and fname.endswith(".md")):
                    continue
            full = os.path.join(dirpath, fname)
            if not os.path.isfile(full):
                continue
            mtime = os.path.getmtime(full)
            docs.append({
                "title":  _research_title(full),
                "badge":  badge,
                "mtime":  mtime,
                "date":   datetime.fromtimestamp(mtime).strftime("%Y-%m-%d"),
                # relative path used as URL token — badge prefix avoids collisions
                "url_path": f"{badge.lower()}/{fname}",
            })
    docs.sort(key=lambda d: d["mtime"], reverse=True)
    return docs


@app.route("/research/<path:filename>")
def research_doc(filename):
    """Serve a research Markdown file rendered to HTML.

    filename is expected in the form  <badge_lower>/<basename>  e.g.
    hiring/_hiring_research_foo.md  or  topical/pax_homunculus_research.md
    """
    parts = filename.split("/", 1)
    if len(parts) != 2:
        abort(404)
    badge_key, basename = parts[0].capitalize(), parts[1]

    if badge_key not in _RESEARCH_DIRS:
        abort(404)

    # Reject traversal attempts
    if ".." in basename or "/" in basename or "\\" in basename:
        abort(400)

    dirpath = _RESEARCH_DIRS[badge_key]
    full = os.path.realpath(os.path.join(dirpath, basename))
    allowed = os.path.realpath(dirpath)
    if not full.startswith(allowed + os.sep):
        abort(400)
    if not os.path.isfile(full):
        abort(404)

    with open(full, encoding="utf-8", errors="replace") as f:
        raw = f.read()

    title = _research_title(full)
    content_html = md(raw)
    return render("research_doc.html", title=title, badge=badge_key,
                  content_html=content_html, filename=basename)


@app.route("/team")
def team():
    _sync_team_member_models()
    members = query("SELECT * FROM team_members ORDER BY name")
    return render("team.html", members=members)


@app.route("/api/team/<int:member_id>/model", methods=["PATCH"])
def update_team_member_model(member_id):
    data = request.get_json(force=True, silent=True) or {}
    tier = data.get("model", "").strip().lower()
    if tier not in _VALID_TIERS:
        return jsonify({"error": f"Invalid model tier: {tier!r}"}), 400

    row = query("SELECT * FROM team_members WHERE id=?", (member_id,), one=True)
    if not row:
        abort(404)

    db = get_db()
    db.execute(
        "UPDATE team_members SET model=?, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
        (tier, member_id),
    )
    db.commit()

    if row["persona_file"]:
        full_path = os.path.normpath(os.path.join(_REPO_ROOT, row["persona_file"]))
        try:
            with open(full_path, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            content = re.sub(r"(- \*\*Model:\*\* )\w+", r"\g<1>" + tier, content)
            with open(full_path, "w", encoding="utf-8") as fh:
                fh.write(content)
        except OSError:
            pass

    readme_path = os.path.normpath(os.path.join(_REPO_ROOT, "team", "README.md"))
    try:
        with open(readme_path, encoding="utf-8") as fh:
            content = fh.read()
        pattern = r"(\| \*\*" + re.escape(row["name"]) + r"\*\* \| [^|]+ \| )\w+( \|)"
        content = re.sub(pattern, r"\g<1>" + tier + r"\2", content)
        with open(readme_path, "w", encoding="utf-8") as fh:
            fh.write(content)
    except OSError:
        pass

    return jsonify({"id": member_id, "model": tier})


@app.route(ROUTE_API_TASKS_RUNNING_COUNT)
def api_tasks_running_count():
    import sqlite3
    held = _db_lock_acquire()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT COUNT(*) AS n FROM tasks "
            "WHERE status = 'in_progress' AND assigned_to != 1"
        ).fetchone()
        return jsonify({"count": int(row["n"])})
    finally:
        try:
            con.close()
        finally:
            _db_lock_release(held)


@app.route("/tasks")
def tasks():
    status_filter = request.args.get("status", "")
    if status_filter:
        rows = query(
            """SELECT t.*, tm.name as assignee_name
               FROM tasks t LEFT JOIN team_members tm ON t.assigned_to = tm.id
               WHERE t.status = ? ORDER BY t.created_at DESC""",
            (status_filter,),
        )
    else:
        rows = query(
            """SELECT t.*, tm.name as assignee_name
               FROM tasks t LEFT JOIN team_members tm ON t.assigned_to = tm.id
               ORDER BY t.created_at DESC"""
        )
    statuses = ["pending", "in_progress", "blocked", "done", "cancelled"]
    return render("tasks.html", tasks=rows, statuses=statuses,
                   current_status=status_filter)


@app.route("/journal")
def journal_list():
    entries = query("SELECT * FROM journal_entries ORDER BY date DESC")
    return render("journal_list.html", entries=entries)


@app.route("/journal/new", methods=["GET", "POST"])
def journal_new():
    if request.method == "POST":
        entry_date = request.form.get("date", date.today().isoformat())
        title = request.form.get("title", "")
        content = request.form.get("content", "")
        try:
            execute(
                """INSERT INTO journal_entries (date, title, content)
                   VALUES (?, ?, ?)""",
                (entry_date, title, content),
            )
            # Log activity
            execute(
                """INSERT INTO activity_log (actor, action, entity_type, details)
                   VALUES (?, ?, ?, ?)""",
                ("Sienna", "created_journal_entry", "journal_entry",
                 f'Created journal entry: "{title}" for {entry_date}.'),
            )
        except sqlite3.IntegrityError:
            # Date already exists — redirect to edit
            return redirect(url_for("journal_entry", entry_date=entry_date))
        return redirect(url_for("journal_entry", entry_date=entry_date))
    return render("journal_edit.html", entry=None)


@app.route("/journal/<entry_date>", methods=["GET"])
def journal_entry(entry_date):
    entry = query(
        "SELECT * FROM journal_entries WHERE date = ?", (entry_date,), one=True
    )
    if not entry:
        abort(404)
    return render("journal_entry.html", entry=entry)


@app.route("/journal/<entry_date>/edit", methods=["GET", "POST"])
def journal_edit(entry_date):
    entry = query(
        "SELECT * FROM journal_entries WHERE date = ?", (entry_date,), one=True
    )
    if not entry:
        abort(404)
    if request.method == "POST":
        title = request.form.get("title", "")
        content = request.form.get("content", "")
        execute(
            """UPDATE journal_entries SET title=?, content=?,
               updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
               WHERE date=?""",
            (title, content, entry_date),
        )
        return redirect(url_for("journal_entry", entry_date=entry_date))
    return render("journal_edit.html", entry=entry)


@app.route("/documents")
def documents():
    docs = query(
        """SELECT d.*, t.title as task_title
           FROM documents d LEFT JOIN tasks t ON d.task_id = t.id
           ORDER BY d.created_at DESC"""
    )
    return render("documents.html", documents=docs)


@app.route("/activity")
def activity():
    rows = query("SELECT * FROM activity_log ORDER BY created_at DESC")
    return render("activity.html", activities=rows)


# ── Editor routes ──────────────────────────────────────────────────────────

_EGM_BASE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", DIR_GOLF_COURSES_PARENT, DIR_GOLF_COURSES)
)   # generate_stl_3mf.EGM_BASE is the same path (sync test asserts equality)
_TEAM_INBOX = os.path.join(os.path.dirname(__file__), "..", DIR_TEAM_INBOX)
_OWNER_INBOX = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", DIR_OWNER_INBOX))
_GOLF_COURSES_PARENT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", DIR_GOLF_COURSES_PARENT))

# ── GPS-backend helpers ────────────────────────────────────────────────────
# Simple in-process cache for the GPS preview endpoint.
# Key: SHA-256 of "gps_path|bbox_json|approach_m|grid_size"
# Value: (png_bytes, expiry_timestamp)
_GPS_PREVIEW_CACHE: dict[str, tuple[bytes, float]] = {}
_GPS_PREVIEW_CACHE_TTL_S = 30  # seconds (also quoted in the gps_heightmap_preview docstring)


def _gps_preview_cache_key(gps_file: str, bbox_json: str, approach_m: float, grid_size: int) -> str:
    raw = f"{gps_file}|{bbox_json}|{approach_m}|{grid_size}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _gps_preview_cache_get(key: str) -> bytes | None:
    """Return cached PNG bytes if the entry is still fresh, else None."""
    entry = _GPS_PREVIEW_CACHE.get(key)
    if entry is None:
        return None
    png_bytes, expiry = entry
    if time.time() > expiry:
        _GPS_PREVIEW_CACHE.pop(key, None)
        return None
    return png_bytes


def _gps_preview_cache_set(key: str, png_bytes: bytes) -> None:
    _GPS_PREVIEW_CACHE[key] = (png_bytes, time.time() + _GPS_PREVIEW_CACHE_TTL_S)


def _validate_gps_prereqs(egm_data: dict) -> tuple[bool, str]:
    """Check GPS prereqs when gpsBackend.enabled is True.

    Returns (ok: bool, error_msg: str).  ok=True means pre-check passed.
    """
    gps = egm_data.get(KEY_GPS_BACKEND) or {}
    if not gps.get(KEY_GPS_ENABLED):
        return True, ""  # GPS not active — nothing to check

    gps_file = gps.get(KEY_GPS_FILE, "").strip()
    if not gps_file:
        return False, MSG_GPS_NO_FILE
    if not os.path.isfile(gps_file):
        return False, MSG_GPS_FILE_MISSING_FMT.format(path=gps_file)

    georef = egm_data.get(KEY_COURSE_GEOREF)
    if not georef:
        return False, MSG_GPS_NO_GEOREF

    return True, ""


def _find_image_path(image_name: str, preferred_course: str = "") -> str | None:
    """Resolve an image filename to an absolute path.

    Search order:
      1. ``preferred_course``/Images/ (the image's declared source course)
      2. All other course Images/ folders under _EGM_BASE (cross-course fallback)
      3. team_inbox/ (legacy location)
      4. owner_inbox/ (legacy location)

    Returns the absolute path string, or None if not found.
    """
    search_dirs = []
    # 1. Preferred (source) course first
    if preferred_course and os.path.isdir(_EGM_BASE):
        search_dirs.append(os.path.abspath(os.path.join(_EGM_BASE, preferred_course, COURSE_SUBDIR_IMAGES)))
    # 2. All course Images/ folders (catches cross-course references)
    if os.path.isdir(_EGM_BASE):
        for entry in sorted(os.listdir(_EGM_BASE)):
            if entry == preferred_course:
                continue  # already added above
            candidate_dir = os.path.abspath(os.path.join(_EGM_BASE, entry, COURSE_SUBDIR_IMAGES))
            if os.path.isdir(candidate_dir):
                search_dirs.append(candidate_dir)
    # 3. Legacy locations
    search_dirs.append(os.path.abspath(_TEAM_INBOX))
    search_dirs.append(os.path.abspath(_OWNER_INBOX))

    for folder in search_dirs:
        candidate = os.path.join(folder, image_name)
        if os.path.isfile(candidate):
            return candidate
    return None


def _is_degridded_name(filename: str) -> bool:
    """True for the generated cleaned copies (hidden from the image picker)."""
    return os.path.splitext(filename)[0].endswith(heatmap_degrid.DEGRID_SUFFIX)


def _image_url_for_path(img_path: str) -> str | None:
    """Servable URL for an image that lives in a course Images/ folder or team_inbox."""
    folder = os.path.abspath(os.path.dirname(img_path))
    name = os.path.basename(img_path)
    if os.path.abspath(_TEAM_INBOX) == folder:
        return TEAM_INBOX_URL_FMT.format(filename=name)
    parent, leaf = os.path.split(folder)
    if leaf == COURSE_SUBDIR_IMAGES and os.path.dirname(parent) == os.path.abspath(_EGM_BASE):
        return EGM_IMAGE_URL_FMT.format(course=os.path.basename(parent), filename=name)
    return None


@app.route(ROUTE_API_DEGRID_IMAGE, methods=[METHOD_POST])
def degrid_image():
    """Build on demand (or reuse) the degridded copy of a heat-map PNG.

    Body: {"image": filename, "imageCourse": course}.  Returns
    {"status":"ok","found":bool,"originalUrl":..,"degriddedUrl":..|None}.
    The original file is never touched; the copy is written next to it.
    """
    data = request.get_json(silent=True) or {}
    image_name = data.get(KEY_IMAGE, "")
    img_path = _find_image_path(image_name, preferred_course=data.get(KEY_IMAGE_COURSE, ""))
    if not image_name or img_path is None:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_IMAGE_NOT_FOUND_FMT.format(name=image_name)}), HTTP_BAD_REQUEST
    original_url = _image_url_for_path(img_path)
    if original_url is None:
        return jsonify({KEY_STATUS: STATUS_OK, KEY_FOUND: False, KEY_ORIGINAL_URL: None, KEY_DEGRIDDED_URL: None})
    out_path = heatmap_degrid.degridded_path(img_path)
    # cache is reused only if newer than the source AND stamped with the current algorithm version
    fresh = heatmap_degrid.cache_is_fresh(img_path, out_path)
    if not fresh:
        info = heatmap_degrid.degrid_file(img_path, out_path)
        if not info.get(heatmap_degrid.INFO_WRITTEN):
            return jsonify({KEY_STATUS: STATUS_OK, KEY_FOUND: False, KEY_ORIGINAL_URL: original_url, KEY_DEGRIDDED_URL: None})
    return jsonify({KEY_STATUS: STATUS_OK, KEY_FOUND: True, KEY_ORIGINAL_URL: original_url,
                    KEY_DEGRIDDED_URL: _image_url_for_path(out_path)})


def _collect_course_images():
    """
    Return a list of image dicts from all GolfCourses/*/Images/ folders.

    Each dict has keys: 'filename', 'course', 'url'
    Falls back to team_inbox images (course=None) for backwards compat.
    Results are sorted case-insensitively: courses A→Z, then filenames A→Z within each course.
    """
    results = []
    exts = IMAGE_EXTS
    if os.path.isdir(_EGM_BASE):
        for course in sorted(os.listdir(_EGM_BASE), key=str.casefold):
            img_dir = os.path.join(_EGM_BASE, course, COURSE_SUBDIR_IMAGES)
            if not os.path.isdir(img_dir):
                continue
            for fname in sorted(os.listdir(img_dir), key=str.casefold):
                if fname.lower().endswith(exts) and not _is_degridded_name(fname):
                    results.append({
                        KEY_FILENAME: fname,
                        KEY_COURSE: course,
                        KEY_URL: EGM_IMAGE_URL_FMT.format(course=course, filename=fname),
                    })
    # Backwards compat: also include team_inbox images
    if os.path.isdir(_TEAM_INBOX):
        for fname in sorted(os.listdir(_TEAM_INBOX), key=str.casefold):
            if fname.lower().endswith(exts) and not _is_degridded_name(fname):
                results.append({
                    KEY_FILENAME: fname,
                    KEY_COURSE: None,
                    KEY_URL: TEAM_INBOX_URL_FMT.format(filename=fname),
                })
    return results


@app.route(ROUTE_EDITOR)
def editor():
    """Polygon boundary editor for golf hole images."""
    image = request.args.get(QUERY_IMAGE, "")
    images = [entry[KEY_FILENAME] for entry in _collect_course_images()]
    egm = request.args.get(QUERY_EGM, "")
    return render("editor.html", image=image, images=images, egm=egm)


@app.route(ROUTE_API_IMAGES)
def list_images():
    """Return current list of images from all GolfCourses/*/Images/ folders."""
    return jsonify(_collect_course_images())


@app.route(ROUTE_API_COURSES, methods=[METHOD_GET])
def list_courses():
    """Return case-insensitively sorted list of existing course folder names under GolfCourses/.

    Used by the New Project dialog to surface matching folders before the user
    creates a new (potentially duplicate) folder.
    """
    courses = []
    if os.path.isdir(_EGM_BASE):
        for entry in sorted(os.listdir(_EGM_BASE), key=str.casefold):
            if entry.startswith(HIDDEN_PREFIX):
                continue
            if os.path.isdir(os.path.join(_EGM_BASE, entry)):
                courses.append(entry)
    resp = jsonify({KEY_COURSES: courses})
    resp.headers[HEADER_CACHE_CONTROL] = CACHE_NO_STORE
    return resp


@app.route(ROUTE_API_COURSES, methods=[METHOD_POST])
def create_course():
    """Create a new course folder under GolfCourses/ with standard subfolders.

    Expects JSON: {"name": "<course folder name>"}
    Returns: {KEY_STATUS: STATUS_OK, "course": "<name>"} on success.
    Rejects: empty name, path separators, leading dot, or already-exists (409).
    Subfolders created: 3MFs/, EGMs/, Images/ (no STLs/).
    """
    data = request.get_json(force=True) or {}
    name = (data.get(KEY_NAME) or "").strip()

    # Validate
    if not name:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_COURSE_EMPTY}), HTTP_BAD_REQUEST
    if any(sep in name for sep in PATH_SEPARATORS):
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_COURSE_SEPARATORS}), HTTP_BAD_REQUEST
    if name.startswith(HIDDEN_PREFIX):
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_COURSE_DOT}), HTTP_BAD_REQUEST

    course_root = os.path.normpath(os.path.join(_EGM_BASE, name))
    # Guard against path traversal
    if not course_root.startswith(os.path.normpath(_EGM_BASE) + os.sep):
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_COURSE_INVALID}), HTTP_BAD_REQUEST

    if os.path.exists(course_root):
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_COURSE_EXISTS_FMT.format(name=name)}), HTTP_CONFLICT

    try:
        for sub in COURSE_SUBDIRS:
            os.makedirs(os.path.join(course_root, sub), exist_ok=True)
    except OSError as exc:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: str(exc)}), HTTP_SERVER_ERROR

    return jsonify({KEY_STATUS: STATUS_OK, KEY_COURSE: name})


@app.route(ROUTE_TEAM_INBOX)
def serve_team_inbox(filename):
    """Serve images from team_inbox for the editor (backwards compat)."""
    inbox = os.path.abspath(_TEAM_INBOX)
    return send_from_directory(inbox, filename)


@app.route(ROUTE_EGM_IMAGE)
def serve_egm_image(course, filename):
    """Serve images from a course's Images/ folder."""
    img_dir = os.path.abspath(os.path.join(_EGM_BASE, course, COURSE_SUBDIR_IMAGES))
    return send_from_directory(img_dir, filename)


def _ensure_course_subfolders(course_root: str) -> None:
    """Create 3MFs/, EGMs/, and Images/ under course_root if they don't exist."""
    for sub in COURSE_SUBDIRS:
        os.makedirs(os.path.join(course_root, sub), exist_ok=True)


@app.route(ROUTE_API_BOUNDARIES, methods=[METHOD_POST])
def save_boundaries():
    """Save polygon boundary coordinates as an .egm file."""
    import json as _json
    data = request.get_json()
    course = data.get(KEY_COURSE, DEFAULT_COURSE_NAME)
    hole = data.get(KEY_HOLE, DEFAULT_HOLE)
    hole_label = str(hole).zfill(HOLE_LABEL_WIDTH) if str(hole).isdigit() else str(hole)
    filename = EGM_FILENAME_FMT.format(course=course, hole_label=hole_label)
    # An EGM opened by full path is written back to THAT file, never to a course-folder copy.
    explicit_path = data.pop(KEY_EGM_PATH, "")
    if explicit_path:
        target, err = _validate_egm_path(explicit_path)
        if err:
            return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: err}), HTTP_BAD_REQUEST
        with open(target, "w") as f:
            _json.dump(data, f, indent=EGM_JSON_INDENT)
        return jsonify({KEY_STATUS: STATUS_OK, KEY_PATH: target, KEY_FILENAME: os.path.basename(target)})
    # Save to course EGMs/ folder; fall back to owner_inbox for unknown courses
    if course and course != DEFAULT_COURSE_NAME and os.path.isdir(_EGM_BASE):
        course_root = os.path.join(_EGM_BASE, course)
        _ensure_course_subfolders(course_root)
        egm_dir = os.path.join(course_root, COURSE_SUBDIR_EGMS)
    else:
        egm_dir = os.path.join(os.path.dirname(__file__), "..", DIR_OWNER_INBOX)
        os.makedirs(egm_dir, exist_ok=True)
    output = os.path.join(egm_dir, filename)
    with open(output, "w") as f:
        _json.dump(data, f, indent=EGM_JSON_INDENT)
    return jsonify({KEY_STATUS: STATUS_OK, KEY_PATH: output, KEY_FILENAME: filename})


@app.route(ROUTE_API_BOUNDARIES_LIST)
def list_boundaries():
    """Return a list of all saved .egm project files from all course EGMs/ folders.

    Courses are enumerated case-insensitively A→Z; files within each course are
    enumerated case-insensitively A→Z.
    """
    import json as _json
    projects = []

    def _scan_dir(scan_dir):
        if not os.path.isdir(scan_dir):
            return
        for fname in sorted(os.listdir(scan_dir), key=str.casefold):
            if not fname.endswith(EXT_EGM):
                continue
            fpath = os.path.join(scan_dir, fname)
            try:
                with open(fpath) as f:
                    data = _json.load(f)
                projects.append({
                    KEY_FILENAME: fname,
                    KEY_COURSE: data.get(KEY_COURSE, ""),
                    KEY_HOLE: data.get(KEY_HOLE, ""),
                    KEY_IMAGE: data.get(KEY_IMAGE, ""),
                    KEY_POLYGON_COUNT: len(data.get(KEY_POLYGONS, [])),
                })
            except Exception:
                pass

    # Scan all GolfCourses/*/EGMs/ directories
    if os.path.isdir(_EGM_BASE):
        for course_name in sorted(os.listdir(_EGM_BASE), key=str.casefold):
            _scan_dir(os.path.join(_EGM_BASE, course_name, COURSE_SUBDIR_EGMS))
    # Backwards compat: also scan owner_inbox
    _scan_dir(os.path.join(os.path.dirname(__file__), "..", DIR_OWNER_INBOX))

    resp = jsonify({KEY_STATUS: STATUS_OK, KEY_PROJECTS: projects})
    resp.headers[HEADER_CACHE_CONTROL] = CACHE_NO_STORE
    return resp


def _validate_egm_path(raw_path):
    """Validate a client-supplied full path to an .egm file.

    Returns (realpath, None) or (None, error_message).  Requires an absolute path whose
    symlink-resolved target has the .egm extension, exists, and is a regular file.
    """
    if not raw_path:
        return None, MSG_EGM_PATH_REQUIRED
    if not os.path.isabs(raw_path):
        return None, MSG_EGM_PATH_NOT_ABSOLUTE
    real = os.path.realpath(raw_path)
    if not real.lower().endswith(EXT_EGM):
        return None, MSG_EGM_PATH_BAD_EXT_FMT.format(ext=EXT_EGM)
    if not os.path.exists(real):
        return None, MSG_EGM_PATH_NOT_FOUND_FMT.format(path=raw_path)
    if not os.path.isfile(real):
        return None, MSG_EGM_PATH_NOT_REGULAR_FMT.format(path=raw_path)
    return real, None


def _course_implied_by_egm_path(real_path):
    """If the file sits in <GolfCourses>/<Course>/EGMs/, return <Course>; else ''."""
    egm_dir = os.path.dirname(real_path)
    course_root = os.path.dirname(egm_dir)
    if (os.path.basename(egm_dir) == COURSE_SUBDIR_EGMS
            and os.path.realpath(os.path.dirname(course_root)) == os.path.realpath(_EGM_BASE)):
        return os.path.basename(course_root)
    return ""


def _resolve_egm_image_course(data, real_path):
    """Pick the course whose Images/ folder holds the EGM's image.

    Order: the EGM's imageCourse, its course, then the course implied by its location.
    Returns (course, warning); course '' with no warning means the image is in team_inbox.
    """
    image = data.get(KEY_IMAGE, "")
    candidates = []
    for name in (data.get(KEY_IMAGE_COURSE), data.get(KEY_COURSE), _course_implied_by_egm_path(real_path)):
        if name and name not in candidates:
            candidates.append(name)
    for name in candidates:
        if os.path.isfile(os.path.join(_EGM_BASE, name, COURSE_SUBDIR_IMAGES, image)):
            return name, ""
    if image and os.path.isfile(os.path.join(_TEAM_INBOX, image)):
        return "", ""
    return (candidates[0] if candidates else ""), MSG_EGM_IMAGE_MISSING_FMT.format(
        image=image, courses=", ".join(candidates) or "-")


def _egm_load_response(fpath, by_full_path=False):
    import json as _json
    with open(fpath) as f:
        data = _json.load(f)
    data[KEY_STATUS] = STATUS_OK
    # Expose print constants so the editor can size the fringe-expansion zone.
    # generate_stl_3mf imports trimesh/shapely/numpy at module load; on a fresh
    # machine missing any of those, this route used to 500 with an ImportError
    # even though the file itself loaded fine. Fall back to omitting the
    # constants — the editor tolerates them being null via `if (data.print_size_mm != null)`.
    try:
        from generate_stl_3mf import PRINT_SIZE_MM, FRINGE_XY_EXPANSION_MM
        data[KEY_PRINT_SIZE_MM] = PRINT_SIZE_MM
        data[KEY_FRINGE_XY_EXPANSION_MM] = FRINGE_XY_EXPANSION_MM
    except ImportError as _imp_err:
        print(f"[load_boundaries] WARN: could not import print constants from generate_stl_3mf: {_imp_err!r}")

    # Off-frame polygon points are intentional (users can drag control points
    # outside the image frame deliberately). Return coords as-is from the EGM —
    # no load-time clamping. The generation-time clamp in detect_boundaries
    # still constrains auto-analyzed output to the frame; only hand-placed
    # off-frame points are preserved here.

    if by_full_path:
        data[KEY_EGM_PATH] = fpath
        img_course, warning = _resolve_egm_image_course(data, fpath)
        data[KEY_IMAGE_COURSE] = img_course
        if warning:
            data[KEY_IMAGE_WARNING] = warning
    return jsonify(data)


@app.route(ROUTE_API_BOUNDARIES_LOAD_PATH)
def load_boundaries_by_path():
    """Load an .egm by FULL absolute path (Finder double-click / launcher).  Writes go back to that same file."""
    fpath, err = _validate_egm_path(request.args.get(QUERY_PATH, ""))
    if err:
        code = HTTP_NOT_FOUND if err.startswith(MSG_EGM_PATH_NOT_FOUND_FMT.split("{")[0]) else HTTP_BAD_REQUEST
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: err}), code
    try:
        return _egm_load_response(fpath, by_full_path=True)
    except (OSError, ValueError) as exc:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_CANNOT_READ_EGM_FMT.format(err=exc)}), HTTP_SERVER_ERROR


@app.route(ROUTE_API_BOUNDARIES_LOAD)
def load_boundaries():
    """Load a saved .egm file by filename and return its contents.

    Searches all GolfCourses/*/EGMs/ directories first, then owner_inbox/.
    """
    import json as _json
    filename = request.args.get(QUERY_FILENAME, "")
    if not filename or PARENT_DIR_TOKEN in filename or URL_PATH_SEP in filename:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_INVALID_FILENAME}), HTTP_BAD_REQUEST

    # Search course EGMs/ folders first
    fpath = None
    if os.path.isdir(_EGM_BASE):
        for course_name in sorted(os.listdir(_EGM_BASE)):
            candidate = os.path.join(_EGM_BASE, course_name, COURSE_SUBDIR_EGMS, filename)
            if os.path.isfile(candidate):
                fpath = candidate
                break
    # Fallback: owner_inbox
    if fpath is None:
        candidate = os.path.join(os.path.dirname(__file__), "..", DIR_OWNER_INBOX, filename)
        if os.path.isfile(candidate):
            fpath = candidate
    if fpath is None:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_FILE_NOT_FOUND}), HTTP_NOT_FOUND
    return _egm_load_response(fpath)


@app.route(ROUTE_API_PRINT_CONSTANTS)
def print_constants():
    """Return the print-size and fringe-expansion constants needed by the boundary editor."""
    from generate_stl_3mf import PRINT_SIZE_MM, FRINGE_XY_EXPANSION_MM
    return jsonify({
        KEY_STATUS: STATUS_OK,
        KEY_PRINT_SIZE_MM: PRINT_SIZE_MM,
        KEY_FRINGE_XY_EXPANSION_MM: FRINGE_XY_EXPANSION_MM,
    })


# ── Point-clamping helpers ────────────────────────────────────────────────────

def _clamp_point_to_image(x: float, y: float, w: int, h: int) -> tuple:
    """Clamp a single (x, y) coordinate to the image frame [0, w] x [0, h].

    Returns (float, float).  Points already inside are returned unchanged.
    Prefer snap-to-edge over reject so polygon topology is preserved.
    """
    return (max(0.0, min(float(w), float(x))),
            max(0.0, min(float(h), float(y))))


def _clamp_polygon_points(points: list, w: int, h: int) -> tuple:
    """Clamp every point in *points* to [0, w] x [0, h] and deduplicate
    consecutive identical points that arise when two adjacent vertices both
    snap to the same corner.

    Parameters
    ----------
    points : list of {"x": ..., "y": ...}
    w, h   : image width and height

    Returns
    -------
    (clamped_points, clamp_count) — clamped_points is the cleaned list,
    clamp_count is the number of original points that needed clamping
    (not counting deduplication removals).
    """
    clamp_count = 0
    clamped = []
    for pt in points:
        cx, cy = _clamp_point_to_image(pt[KEY_X], pt[KEY_Y], w, h)
        if cx != float(pt[KEY_X]) or cy != float(pt[KEY_Y]):
            clamp_count += 1
            print(
                f"[boundary_clamp] Point ({pt['x']}, {pt['y']}) clamped to "
                f"({cx}, {cy}) for image {w}x{h}"
            )
        clamped.append({KEY_X: cx, KEY_Y: cy})

    # Deduplicate consecutive identical points (can arise when two adjacent
    # vertices both snap to the same corner of the image frame).
    deduped = []
    for pt in clamped:
        if deduped and deduped[-1][KEY_X] == pt[KEY_X] and deduped[-1][KEY_Y] == pt[KEY_Y]:
            continue  # skip consecutive duplicate
        deduped.append(pt)

    return deduped, clamp_count


@app.route(ROUTE_API_DETECT_BOUNDARIES, methods=[METHOD_POST])
def detect_boundaries():
    """Run quick CV detection on a golf hole image, return initial polygon guesses."""
    import cv2
    import numpy as np
    from scipy.ndimage import binary_fill_holes

    data = request.get_json()
    image_name = data.get(KEY_IMAGE, "")
    course = data.get(KEY_COURSE, "")
    image_course = data.get(KEY_IMAGE_COURSE, "") or course
    if not image_name:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_NO_IMAGE}), HTTP_BAD_REQUEST

    # Resolve image to absolute path, searching all course folders as fallback
    img_path = _find_image_path(image_name, preferred_course=image_course)
    print(f"[detect_boundaries] image lookup: name={image_name!r} preferred_course={image_course!r} -> {img_path!r}")
    if img_path is None:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_IMAGE_NOT_FOUND_FMT.format(name=image_name)}), HTTP_BAD_REQUEST
    if DEGRID_DETECT_ON_CLEANED:
        _cleaned_path = heatmap_degrid.degridded_path(img_path)
        if os.path.isfile(_cleaned_path):
            img_path = _cleaned_path
    img = cv2.imread(img_path)
    if img is None:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_CANNOT_READ_IMAGE_FMT.format(path=img_path)}), HTTP_BAD_REQUEST

    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0].astype(float)
    sat = hsv[:, :, 1].astype(float)
    val = hsv[:, :, 2].astype(float)

    # --- Detect putting green: high-saturation colorful contour bands ---
    # Non-green hues (orange, red, yellow, blue, cyan) with high saturation
    contour_bands = (
        ((hue < DETECT_GREEN_HUE_SPLIT_LO) | (hue > DETECT_GREEN_HUE_SPLIT_HI))
        & (sat > DETECT_GREEN_NONGREEN_MIN_SAT) & (val > DETECT_GREEN_MIN_VAL)
    ) | (
        (hue >= DETECT_GREEN_HUE_SPLIT_LO) & (hue <= DETECT_GREEN_HUE_SPLIT_HI)
        & (sat > DETECT_GREEN_GREENHUE_MIN_SAT) & (val > DETECT_GREEN_MIN_VAL)
    )
    contour_u8 = (contour_bands.astype(np.uint8)) * DETECT_MASK_ON
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DETECT_GREEN_CLOSE_KERNEL, DETECT_GREEN_CLOSE_KERNEL))
    contour_u8 = cv2.morphologyEx(contour_u8, cv2.MORPH_CLOSE, kernel, iterations=DETECT_GREEN_CLOSE_ITERATIONS)
    contour_filled = binary_fill_holes(contour_u8 > 0)
    contour_u8 = (contour_filled.astype(np.uint8)) * DETECT_MASK_ON

    # Largest component = putting green
    n_cc, cc_labels, cc_stats, _ = cv2.connectedComponentsWithStats(contour_u8)
    green_mask = np.zeros((h, w), dtype=np.uint8)
    if n_cc > 1:
        areas = cc_stats[1:, cv2.CC_STAT_AREA]
        largest = 1 + np.argmax(areas)
        green_mask = ((cc_labels == largest) * DETECT_MASK_ON).astype(np.uint8)

    # Smooth green boundary
    green_mask = cv2.GaussianBlur(green_mask, (DETECT_GREEN_BLUR_KERNEL, DETECT_GREEN_BLUR_KERNEL), 0)
    _, green_mask = cv2.threshold(green_mask, DETECT_MASK_THRESHOLD, DETECT_MASK_ON, cv2.THRESH_BINARY)

    # --- Green-interior exclusion mask ---
    # When MASK_GREEN_INTERIOR_FROM_HAZARDS is True the green polygon interior
    # is excluded from both trap and water classification.  This prevents the
    # slope-gradient color bands rendered inside the putting surface from being
    # misclassified as hazards.  On Golf Intelligence heat maps the low-elevation
    # zones appear as blue/teal — indistinguishable from water without this mask.
    # Disable (False) only for rare island holes where a hazard truly sits inside
    # the green perimeter.
    if MASK_GREEN_INTERIOR_FROM_HAZARDS:
        _hazard_search_area = cv2.bitwise_not(green_mask)  # 255 = outside green
    else:
        _hazard_search_area = np.full((h, w), DETECT_MASK_ON, dtype=np.uint8)  # unrestricted

    # --- Detect sand traps: pale cream/beige/tan ---
    # H range widened from [15,34] to [10,40] to catch light beige (H≈13) such
    # as the Stanford H8 lower-left trap.  Saturation and value bounds unchanged.
    # Pixels inside the green are excluded by _hazard_search_area.
    trap_mask = (
        (hue >= DETECT_TRAP_HUE[0]) & (hue <= DETECT_TRAP_HUE[1]) &
        (sat >= DETECT_TRAP_SAT[0]) & (sat <= DETECT_TRAP_SAT[1]) &
        (val >= DETECT_TRAP_MIN_VAL)
    ).astype(np.uint8) * DETECT_MASK_ON
    trap_mask = cv2.bitwise_and(trap_mask, _hazard_search_area)
    kernel_t = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DETECT_HAZARD_CLOSE_KERNEL, DETECT_HAZARD_CLOSE_KERNEL))
    trap_mask = cv2.morphologyEx(trap_mask, cv2.MORPH_CLOSE, kernel_t, iterations=DETECT_HAZARD_CLOSE_ITERATIONS)
    trap_mask = cv2.morphologyEx(trap_mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DETECT_HAZARD_OPEN_KERNEL, DETECT_HAZARD_OPEN_KERNEL)), iterations=DETECT_HAZARD_OPEN_ITERATIONS)
    trap_filled = binary_fill_holes(trap_mask > 0)
    trap_mask = (trap_filled.astype(np.uint8)) * DETECT_MASK_ON

    # Find individual traps
    n_t, t_labels, t_stats, t_centroids = cv2.connectedComponentsWithStats(trap_mask)
    traps = []
    for i in range(1, n_t):
        area = t_stats[i, cv2.CC_STAT_AREA]
        if area >= DETECT_MIN_BLOB_AREA_PX:
            traps.append((i, area))
    traps.sort(key=lambda x: x[1], reverse=True)
    traps = traps[:DETECT_MAX_TRAPS]

    # --- Detect water hazards: deep blue/cyan regions ---
    # Two complementary filters are OR-combined so both saturated blue water
    # (e.g. PGA West, H≈104-105, S≈172, V=164-184) and pale-cyan water
    # (e.g. Stanford H8 LR, H≈90, S≈29, V≈238) are detected.
    #
    # High-saturation path (original): royal blue / bright cyan water bodies.
    #   H 100-130, S≥130, V 130-220.  Excludes darker gradient arrows (V<130)
    #   and near-white reflections (V>220).
    #
    # Pale-cyan path (new, 2026-09-28): very desaturated cyan areas that appear
    #   as light background tints on Golf Intelligence heat maps.  H 80-105
    #   (pure cyan at H=90), S 15-50 (above gray background S=0 but below the
    #   slope-gradient S≥100), V≥200 (bright enough to be a surface, not a dark
    #   gradient band).  S cap of 50 ensures the slope-band interior colors
    #   (S≈100-255) are never pulled in even if green masking were disabled.
    #
    # Pixels inside the green are excluded by _hazard_search_area.
    _water_high_sat = (
        (hue >= DETECT_WATER_BLUE_HUE[0]) & (hue <= DETECT_WATER_BLUE_HUE[1]) &
        (sat >= DETECT_WATER_BLUE_MIN_SAT) &
        (val >= DETECT_WATER_BLUE_VAL[0]) & (val <= DETECT_WATER_BLUE_VAL[1])
    ).astype(np.uint8) * DETECT_MASK_ON
    _water_pale_cyan = (
        (hue >= DETECT_WATER_PALE_HUE[0]) & (hue <= DETECT_WATER_PALE_HUE[1]) &
        (sat >= DETECT_WATER_PALE_SAT[0]) & (sat <= DETECT_WATER_PALE_SAT[1]) &
        (val >= DETECT_WATER_PALE_MIN_VAL)
    ).astype(np.uint8) * DETECT_MASK_ON
    water_mask = cv2.bitwise_or(_water_high_sat, _water_pale_cyan)
    water_mask = cv2.bitwise_and(water_mask, _hazard_search_area)
    kernel_w = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DETECT_HAZARD_CLOSE_KERNEL, DETECT_HAZARD_CLOSE_KERNEL))
    water_mask = cv2.morphologyEx(water_mask, cv2.MORPH_CLOSE, kernel_w, iterations=DETECT_HAZARD_CLOSE_ITERATIONS)
    water_mask = cv2.morphologyEx(water_mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DETECT_HAZARD_OPEN_KERNEL, DETECT_HAZARD_OPEN_KERNEL)), iterations=DETECT_HAZARD_OPEN_ITERATIONS)
    water_filled = binary_fill_holes(water_mask > 0)
    water_mask = (water_filled.astype(np.uint8)) * DETECT_MASK_ON

    # Find individual water bodies
    n_w, w_labels, w_stats, w_centroids = cv2.connectedComponentsWithStats(water_mask)
    waters = []
    for i in range(1, n_w):
        area = w_stats[i, cv2.CC_STAT_AREA]
        if area >= DETECT_MIN_BLOB_AREA_PX:
            waters.append((i, area))
    waters.sort(key=lambda x: x[1], reverse=True)
    waters = waters[:DETECT_MAX_WATERS]

    def mask_to_polygon(mask, num_points):
        """Extract the largest contour from a mask and resample to num_points."""
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return []
        cnt = max(contours, key=cv2.contourArea)
        # Resample to num_points evenly spaced along the contour
        cnt = cnt.squeeze()
        if len(cnt.shape) < 2:
            return []
        # Compute cumulative arc length
        n = len(cnt)
        cum = [0.0]
        for j in range(1, n):
            cum.append(cum[-1] + np.linalg.norm(cnt[j] - cnt[j-1]))
        cum.append(cum[-1] + np.linalg.norm(cnt[0] - cnt[-1]))  # close the loop
        total = cum[-1]
        if total == 0:
            return []
        pts = []
        for j in range(num_points):
            target = (j / num_points) * total
            seg = 0
            while seg < n and cum[seg+1] < target:
                seg += 1
            t = (target - cum[seg]) / max(cum[seg+1] - cum[seg], DETECT_ARC_EPSILON)
            a = cnt[seg % n]
            b = cnt[(seg+1) % n]
            px = int(a[0] + t * (b[0] - a[0]))
            py = int(a[1] + t * (b[1] - a[1]))
            pts.append({KEY_X: px, KEY_Y: py})
        return pts

    # --- Detect contour lines inside the putting green ---
    # The colored overlay is a SLOPE map (not elevation).  The contour lines
    # (isolines of constant elevation) run along the boundaries between
    # adjacent color bands.  We classify pixels into 7 hue bands so that
    # adjacent-band boundaries give us the 6 isolines visible in the image.
    #
    # Band labels (ordered by hue, NOT by elevation):
    #   0 = Blue/Cyan   (hue 85-100)
    #   1 = Teal         (hue 65-84)
    #   2 = Green        (hue 45-64)
    #   3 = Yellow-green (hue 25-44)
    #   4 = Orange       (hue 15-24)
    #   5 = Red-orange   (hue 5-14)
    #   6 = Dark red     (hue 0-4 + 175-180)
    BAND_RANGES = DETECT_BAND_RANGES
    NUM_BANDS = len(BAND_RANGES)
    MIN_BAND_SAT = DETECT_BAND_MIN_SAT
    MIN_BAND_VAL = DETECT_BAND_MIN_VAL

    green_interior = (green_mask > 0)
    label_map = np.full((h, w), -1, dtype=np.int8)

    for band_idx, (h_lo, h_hi) in enumerate(BAND_RANGES):
        band_mask = (
            (hue >= h_lo) & (hue <= h_hi) &
            (sat >= MIN_BAND_SAT) & (val >= MIN_BAND_VAL) &
            green_interior
        )
        label_map[band_mask] = band_idx

    # Red wrap-around (hue 175-180) → band 6
    red_wrap = (
        (hue >= DETECT_BAND_RED_WRAP_HUE[0]) & (hue <= DETECT_BAND_RED_WRAP_HUE[1]) &
        (sat >= MIN_BAND_SAT) & (val >= MIN_BAND_VAL) &
        green_interior
    )
    label_map[red_wrap] = DETECT_BAND_RED_WRAP_INDEX

    # Morphological cleanup per band
    clean_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DETECT_BAND_CLEAN_KERNEL, DETECT_BAND_CLEAN_KERNEL))
    for band_idx in range(NUM_BANDS):
        band_u8 = ((label_map == band_idx).astype(np.uint8)) * DETECT_MASK_ON
        band_u8 = cv2.morphologyEx(band_u8, cv2.MORPH_CLOSE, clean_kernel, iterations=DETECT_BAND_CLOSE_ITERATIONS)
        band_u8 = cv2.morphologyEx(band_u8, cv2.MORPH_OPEN,  clean_kernel, iterations=1)
        label_map[green_interior & (label_map == band_idx)] = -1
        label_map[green_interior & (band_u8 > 0)] = band_idx

    # Pre-compute the green perimeter contour once so endpoint snapping can use it
    _green_contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    _green_perimeter_pts = None
    if _green_contours:
        _biggest = max(_green_contours, key=cv2.contourArea).squeeze()
        if _biggest.ndim == 2 and len(_biggest) >= 3:
            _green_perimeter_pts = _biggest.astype(float)  # shape (N, 2) as (x, y)

    def _snap_to_green_perimeter(px, py):
        """Return the nearest point on the green perimeter to pixel (px, py)."""
        if _green_perimeter_pts is None:
            return int(px), int(py)
        dists = np.hypot(_green_perimeter_pts[:, 0] - px, _green_perimeter_pts[:, 1] - py)
        idx = int(np.argmin(dists))
        return int(_green_perimeter_pts[idx, 0]), int(_green_perimeter_pts[idx, 1])

    def extract_single_isoline(boundary_mask, num_pts=DETECT_ISOLINE_POINTS):
        """
        Extract ONE ordered polyline from a boundary mask, with endpoints
        snapped to the green perimeter so shapely.ops.split can divide the
        green polygon cleanly.

        All boundary pixels are pooled, skeletonized, and ordered along
        the principal axis via PCA.  Returns a list of {"x","y"} dicts,
        or [] if there aren't enough pixels.
        """
        from skimage.morphology import skeletonize

        if np.count_nonzero(boundary_mask) < DETECT_ISOLINE_MIN_PIXELS:
            return []

        # Merge fragments: close gaps in the boundary caused by crosshatch
        merge_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DETECT_ISOLINE_MERGE_KERNEL, DETECT_ISOLINE_MERGE_KERNEL))
        merged = cv2.morphologyEx(boundary_mask, cv2.MORPH_CLOSE, merge_kernel, iterations=DETECT_ISOLINE_MERGE_ITERATIONS)

        # Skeletonize the merged boundary into a thin line
        thin = skeletonize(merged > 0)
        pts_yx = np.column_stack(np.where(thin))
        if len(pts_yx) < DETECT_ISOLINE_MIN_POINTS:
            pts_yx = np.column_stack(np.where(merged > 0))
        if len(pts_yx) < DETECT_ISOLINE_MIN_POINTS:
            return []

        # Order points along the principal axis (PCA)
        pts_f = pts_yx.astype(float)
        mean = pts_f.mean(axis=0)
        centered = pts_f - mean
        cov = centered.T @ centered
        eigvals, eigvecs = np.linalg.eigh(cov)
        principal = eigvecs[:, -1]
        proj = centered @ principal
        order = np.argsort(proj)
        ordered = pts_yx[order]

        # Subsample to num_pts evenly spaced interior points
        indices = np.linspace(0, len(ordered) - 1, num_pts, dtype=int)
        sampled = ordered[indices]
        interior = [{KEY_X: int(p[1]), KEY_Y: int(p[0])} for p in sampled]

        # Snap first and last points to the nearest green perimeter point so
        # the isoline spans cleanly from one edge of the green to the other.
        # This is required for shapely.ops.split to work correctly.
        sx0, sy0 = _snap_to_green_perimeter(interior[0][KEY_X], interior[0][KEY_Y])
        sx1, sy1 = _snap_to_green_perimeter(interior[-1][KEY_X], interior[-1][KEY_Y])
        interior[0]  = {KEY_X: sx0, KEY_Y: sy0}
        interior[-1] = {KEY_X: sx1, KEY_Y: sy1}

        # Guard: if both endpoints snapped to the same perimeter point the line
        # is degenerate — drop it.
        if sx0 == sx1 and sy0 == sy1:
            return []

        return interior

    def band_side(polyline_pts, higher_band_mask):
        """Determine which side of the polyline the higher band is on."""
        if len(polyline_pts) < 2:
            return CONTOUR_DIRECTION_LEFT
        dx = polyline_pts[-1][KEY_X] - polyline_pts[0][KEY_X]
        dy = polyline_pts[-1][KEY_Y] - polyline_pts[0][KEY_Y]
        if dx == 0 and dy == 0:
            return CONTOUR_DIRECTION_LEFT
        ys, xs = np.where(higher_band_mask > 0)
        if len(xs) == 0:
            return CONTOUR_DIRECTION_LEFT
        cx, cy = float(xs.mean()), float(ys.mean())
        mid_x = polyline_pts[len(polyline_pts)//2][KEY_X]
        mid_y = polyline_pts[len(polyline_pts)//2][KEY_Y]
        cross = dx * (cy - mid_y) - dy * (cx - mid_x)
        return CONTOUR_DIRECTION_RIGHT if cross > 0 else CONTOUR_DIRECTION_LEFT

    contour_lines = []
    contour_counter = 1
    band_present = [
        np.count_nonzero(label_map == b) > DETECT_BAND_PRESENT_MIN_PX for b in range(NUM_BANDS)
    ]

    # Each adjacent band pair produces exactly ONE isoline
    # Iterate from highest band downward (red→blue) so the first contour
    # found is on the left/interior side of the green.
    for hi_band in range(NUM_BANDS - 1, 0, -1):
        lo_band = hi_band - 1
        if not band_present[lo_band] or not band_present[hi_band]:
            continue

        lo_mask = ((label_map == lo_band).astype(np.uint8)) * DETECT_MASK_ON
        hi_mask = ((label_map == hi_band).astype(np.uint8)) * DETECT_MASK_ON

        # Dilate each band slightly and intersect to find the boundary zone
        dil_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DETECT_BAND_DILATE_KERNEL, DETECT_BAND_DILATE_KERNEL))
        lo_dil = cv2.dilate(lo_mask, dil_kernel, iterations=DETECT_BAND_DILATE_ITERATIONS)
        hi_dil = cv2.dilate(hi_mask, dil_kernel, iterations=DETECT_BAND_DILATE_ITERATIONS)
        boundary = cv2.bitwise_and(lo_dil, hi_dil)

        # Keep only pixels inside the green
        boundary = cv2.bitwise_and(boundary, green_mask)

        if np.count_nonzero(boundary) < DETECT_ISOLINE_MIN_BOUNDARY_PX:
            continue

        # Extract one isoline from ALL boundary pixels for this band pair
        pts = extract_single_isoline(boundary, num_pts=DETECT_ISOLINE_POINTS)
        if len(pts) < 2:
            continue

        direction = band_side(pts, hi_mask)
        contour_lines.append({
            KEY_NAME: POLY_NAME_CONTOUR_FMT.format(n=contour_counter),
            KEY_TYPE: POLY_TYPE_CONTOUR,
            KEY_CLOSED: False,
            KEY_DIRECTION: direction,
            KEY_POINTS: pts,
        })
        contour_counter += 1
        break  # DEBUG: stop after first contour line found

    # Build response
    polygons = []

    # Green polygon (8 points)
    green_pts = mask_to_polygon(green_mask, DETECT_GREEN_POINTS)
    if green_pts:
        polygons.append({KEY_NAME: POLY_NAME_GREEN, KEY_TYPE: POLY_TYPE_GREEN, KEY_POINTS: green_pts})

    # Trap polygons (16 points each)
    for idx, (label_id, area) in enumerate(traps):
        t_mask = ((t_labels == label_id) * DETECT_MASK_ON).astype(np.uint8)
        # Smooth
        t_mask = cv2.GaussianBlur(t_mask, (DETECT_POLY_SMOOTH_KERNEL, DETECT_POLY_SMOOTH_KERNEL), 0)
        _, t_mask = cv2.threshold(t_mask, DETECT_MASK_THRESHOLD, DETECT_MASK_ON, cv2.THRESH_BINARY)
        trap_pts = mask_to_polygon(t_mask, DETECT_HAZARD_POINTS)
        if trap_pts:
            polygons.append({KEY_NAME: POLY_NAME_TRAP_FMT.format(n=idx+1), KEY_TYPE: POLY_TYPE_TRAP, KEY_POINTS: trap_pts})

    # Water polygons (16 points each — same as traps)
    for idx, (label_id, area) in enumerate(waters):
        w_mask = ((w_labels == label_id) * DETECT_MASK_ON).astype(np.uint8)
        # Smooth
        w_mask = cv2.GaussianBlur(w_mask, (DETECT_POLY_SMOOTH_KERNEL, DETECT_POLY_SMOOTH_KERNEL), 0)
        _, w_mask = cv2.threshold(w_mask, DETECT_MASK_THRESHOLD, DETECT_MASK_ON, cv2.THRESH_BINARY)
        water_pts = mask_to_polygon(w_mask, DETECT_HAZARD_POINTS)
        if water_pts:
            polygons.append({KEY_NAME: POLY_NAME_WATER_FMT.format(n=idx+1), KEY_TYPE: POLY_TYPE_WATER, KEY_POINTS: water_pts})

    # Contour detection disabled — using arrow-gradient Poisson surface instead
    # polygons.extend(contour_lines)

    # Clamp all generated points to the image frame before returning.
    # CV contours can occasionally produce points 1–2 px outside the image
    # boundary due to GaussianBlur padding or rounding; clamping here prevents
    # those points from ending up off-screen in the editor where they can't be
    # grabbed.  Consecutive duplicates that arise from multiple corners all
    # snapping to the same edge are deduplicated by _clamp_polygon_points.
    total_clamped = 0
    for poly in polygons:
        clamped_pts, n = _clamp_polygon_points(poly[KEY_POINTS], w, h)
        poly[KEY_POINTS] = clamped_pts
        total_clamped += n
    if total_clamped:
        print(f"[detect_boundaries] Clamped {total_clamped} point(s) to image frame "
              f"({w}x{h})")

    return jsonify({
        KEY_STATUS: STATUS_OK,
        KEY_IMAGE_SIZE: {KEY_WIDTH: w, KEY_HEIGHT: h},
        KEY_POLYGONS: polygons,
        KEY_CONTOUR_STEP: DETECT_DEFAULT_CONTOUR_STEP_MM,
    })


@app.route(ROUTE_API_FIND_CONTOURS, methods=[METHOD_POST])
def find_contours():
    """Find contour lines inside an existing green perimeter.

    Accepts JSON with:
      - image: source image filename
      - green_points: array of {x, y} — dense spline-sampled points along the
        green boundary (sent by the editor, not raw control points)
      - imageSize: {width, height}

    Returns:
      - contours: array of contour line objects with type, direction, points
    """
    import numpy as np
    from generate_stl_3mf import (
        remove_arrows_from_green,
        extract_contour_polylines_from_mask,
    )

    data = request.get_json()
    image_name = data.get(KEY_IMAGE, "")
    course = data.get(KEY_COURSE, "")
    image_course = data.get(KEY_IMAGE_COURSE, "") or course
    green_points = data.get(KEY_GREEN_POINTS, [])

    if not image_name or not green_points:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_NEED_IMAGE_AND_GREEN}), HTTP_BAD_REQUEST

    # Resolve image to absolute path, searching all course folders as fallback
    img_path = _find_image_path(image_name, preferred_course=image_course)
    print(f"[find_contours] image lookup: name={image_name!r} preferred_course={image_course!r} -> {img_path!r}")
    if img_path is None:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_IMAGE_NOT_FOUND_FMT.format(name=image_name)}), HTTP_BAD_REQUEST

    # The editor sends dense spline-sampled points — use them directly as the
    # green boundary polygon (Nx2 float64 array of (x, y) pixel coords).
    green_boundary_px = np.array(
        [[p[KEY_X], p[KEY_Y]] for p in green_points], dtype=np.float64
    )

    # Step 1: Remove slope arrows, isolate contour blobs.
    # remove_arrows_from_green saves its own debug image to owner_inbox/.
    try:
        cleaned_img, contour_keep_mask = remove_arrows_from_green(
            img_path, green_boundary_px
        )
    except FileNotFoundError as exc:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: str(exc)}), HTTP_BAD_REQUEST

    # Step 2: Extract ordered polylines from the contour blob mask.
    # extract_contour_polylines_from_mask saves its own debug image to owner_inbox/.
    polylines = extract_contour_polylines_from_mask(
        contour_keep_mask, green_boundary_px, source_image=cleaned_img
    )

    # Step 3: Convert Nx2 float64 arrays into the editor's expected format.
    contour_lines = []
    for i, polyline in enumerate(polylines):
        contour_lines.append({
            KEY_NAME: POLY_NAME_CONTOUR_FMT.format(n=i + 1),
            KEY_TYPE: POLY_TYPE_CONTOUR,
            KEY_CLOSED: False,
            KEY_DIRECTION: CONTOUR_DIRECTION_LEFT,
            KEY_POINTS: [{KEY_X: int(pt[0]), KEY_Y: int(pt[1])} for pt in polyline],
        })

    print(f"[find_contours] Returning {len(contour_lines)} contour(s) for {image_name}")

    return jsonify({
        KEY_STATUS: STATUS_OK,
        KEY_CONTOURS: contour_lines,
    })


@app.route(ROUTE_API_DEPENDENCIES, methods=[METHOD_GET])
def api_dependencies():
    """Report whether every package the 3MF generator needs is importable."""
    return jsonify(dependency_preflight.status_report())


@app.route(ROUTE_API_GENERATE_MODELS, methods=[METHOD_POST])
def generate_models():
    """Run the full gradient surface pipeline for a course/hole.

    Expects JSON: {"course": "<course name>", "hole": "<hole number>", ...}
    The EGM file must already exist on disk (saved by the editor).

    Returns:
        {KEY_STATUS: STATUS_OK, "file": {"name": ..., "path": ..., "type": "3mf"}}
    """
    # v5.75: dependency preflight BEFORE importing the pipeline, burning a serial,
    # or doing any heavy work. Missing packages stop generation with a clear message.
    try:
        dependency_preflight.check_dependencies()
    except dependency_preflight.MissingDependencyError as exc:
        print(f"[generate_models] {exc}")
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: str(exc)}), HTTP_SERVER_ERROR
    from gradient_surface_diagnostic import run_pipeline

    data = request.get_json(force=True)
    if not data:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_NO_JSON}), HTTP_BAD_REQUEST

    course = data.get(KEY_COURSE, "").strip()
    hole = data.get(KEY_HOLE, "").strip()
    if not course or not hole:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_MISSING_COURSE_OR_HOLE}), HTTP_BAD_REQUEST

    # Auto-derive a 5 mm boulders ring around each water polygon when checked
    # (replaces any manual boulders polygons in the EGM). The editor persists
    # this flag to the EGM via autoSave before calling /api/generate_models,
    # but we also forward the request-time value here so the route can override
    # the persisted value if the client ever wants to.
    include_boundary_region = bool(data.get(KEY_INCLUDE_BOUNDARY_REGION, False))
    # Fringe-frame cap toggle (task 669): default True preserves legacy behavior.
    # When False, the water-hole rule at gradient_surface_diagnostic line ~5854
    # skips the per-vertex boundary cap for the fringe mesh, letting the fringe
    # rise to its natural height even where it exceeds the plaque frame.
    # Missing key → True (legacy .egm files never persisted this flag).
    apply_fringe_frame_cap = bool(data.get(KEY_APPLY_FRINGE_FRAME_CAP, True))
    # Include fringe without grass (task 724): when True, a second plate is
    # generated holding a smooth (grass-less) fringe sample. Plate 1 always
    # gets grass unconditionally. Default False (single plate, no sample).
    # Old field from task 714 is intentionally ignored (semantics inverted).
    include_fringe_without_grass = bool(data.get(KEY_INCLUDE_FRINGE_WITHOUT_GRASS, False))
    open_in_slicer = bool(data.get(KEY_OPEN_IN_SLICER, False))

    hole_label = hole.zfill(HOLE_LABEL_WIDTH) if hole.isdigit() else hole
    egm_fname = EGM_FILENAME_FMT.format(course=course, hole_label=hole_label)
    # Look for EGM in course EGMs/ folder first, then owner_inbox fallback
    egm_path = None
    explicit_egm = data.get(KEY_EGM_PATH, "")
    if explicit_egm:   # EGM opened by full path: generate from THAT file (the one autosave wrote)
        egm_path, _path_err = _validate_egm_path(explicit_egm)
        if _path_err:
            return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: _path_err}), HTTP_BAD_REQUEST
    if egm_path is None and os.path.isdir(_EGM_BASE):
        candidate = os.path.abspath(os.path.join(_EGM_BASE, course, COURSE_SUBDIR_EGMS, egm_fname))
        if os.path.exists(candidate):
            egm_path = candidate
    if egm_path is None:
        _owner_inbox = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", DIR_OWNER_INBOX))
        candidate = os.path.join(_owner_inbox, egm_fname)
        if os.path.exists(candidate):
            egm_path = candidate
    if egm_path is None:
        return jsonify({
            KEY_STATUS: STATUS_ERROR,
            KEY_MSG: MSG_EGM_NOT_FOUND_FMT.format(name=egm_fname)
        }), HTTP_NOT_FOUND

    print(f"[generate_models] EGM path:        {egm_path}")

    # ── GPS backend pre-check ─────────────────────────────────────────────────
    # Read the EGM to inspect gpsBackend before committing a serial number.
    # Fail fast with a 400 + helpful message if GPS prereqs are not satisfied.
    import json as _json
    try:
        with open(egm_path) as _egm_fh:
            _egm_for_gps_check = _json.load(_egm_fh)
    except (OSError, ValueError) as _e:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_CANNOT_READ_EGM_FMT.format(err=_e)}), HTTP_SERVER_ERROR

    _gps_ok, _gps_err = _validate_gps_prereqs(_egm_for_gps_check)
    if not _gps_ok:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: _gps_err}), HTTP_BAD_REQUEST

    # ── Commit global serial at click time ───────────────────────────────────
    # The serial is burned here, BEFORE calling into the pipeline, so that:
    #  (a) The filename reflects this exact Generate press.
    #  (b) Even a pipeline failure leaves the counter advanced (serials are
    #      cheap; we never reuse one, even on error).
    from serial_engraver import commit_global_serial as _commit_global_serial
    _serial = _commit_global_serial()
    print(f"[generate_models] Global serial:   {_serial}")

    try:
        three_mf_path = run_pipeline(
            egm_path,
            include_boundary_region=include_boundary_region,
            apply_fringe_frame_cap=apply_fringe_frame_cap,
            include_fringe_without_grass=include_fringe_without_grass,
            serial=_serial,
        )
    except Exception as exc:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: str(exc)}), HTTP_SERVER_ERROR

    # run_pipeline returns the absolute path with serial in the filename.
    # If for any reason it returns None (old callers), fall back to the plain name.
    if three_mf_path and os.path.exists(three_mf_path):
        three_mf_name = os.path.basename(three_mf_path)
    else:
        # Fallback: old-style name without serial (file may not exist yet)
        three_mf_name = THREE_MF_FILENAME_FMT.format(course=course, hole_label=hole_label)
        three_mf_dir = os.path.abspath(os.path.join(_EGM_BASE, course, COURSE_SUBDIR_3MFS))
        three_mf_path = os.path.join(three_mf_dir, three_mf_name)
        if not os.path.exists(three_mf_path):
            _owner_inbox = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", DIR_OWNER_INBOX)
            )
            three_mf_path = os.path.join(_owner_inbox, three_mf_name)

    print(f"[generate_models] output 3MF path: {os.path.abspath(three_mf_path)}")

    result = {
        KEY_NAME: three_mf_name,
        KEY_PATH: os.path.relpath(three_mf_path, os.path.dirname(__file__)),
        KEY_TYPE: FILE_TYPE_3MF,
    }

    # ── Open in default slicer (macOS file-association) ──────────────────────
    # Uses `open <file>` so the OS hands the .3mf to whatever app owns the
    # extension — no hardcoded Bambu path. If `open` fails, surface stderr so
    # the user knows what went wrong; hint to use Finder as fallback.
    slicer_opened = None
    slicer_error  = None
    if open_in_slicer and three_mf_path and os.path.exists(three_mf_path):
        import subprocess
        try:
            proc = subprocess.run(
                [SLICER_OPEN_COMMAND, three_mf_path],
                capture_output=True,
                timeout=SLICER_OPEN_TIMEOUT_S,
            )
            if proc.returncode == 0:
                slicer_opened = True
            else:
                slicer_opened = False
                stderr_text = (proc.stderr or b"").decode(errors="replace").strip()
                slicer_error = (
                    stderr_text
                    or MSG_SLICER_EXIT_FMT.format(code=proc.returncode)
                )
        except subprocess.TimeoutExpired:
            slicer_opened = False
            slicer_error  = MSG_SLICER_TIMEOUT
        except Exception as exc:
            slicer_opened = False
            slicer_error  = str(exc)

    import gradient_surface_diagnostic as _gsd
    return jsonify({KEY_STATUS: STATUS_OK, KEY_FILE: result,
                    KEY_SLICER_OPENED: slicer_opened, KEY_SLICER_ERROR: slicer_error,
                    KEY_WARNINGS: list(_gsd.PIPELINE_WARNINGS)})


# ── GPS Heightmap Preview ─────────────────────────────────────────────────────

@app.route(ROUTE_API_GPS_HEIGHTMAP_PREVIEW)
def gps_heightmap_preview():
    """Return a server-side PNG heightmap preview for the GPS backend panel.

    Query params
    ------------
    gps_file   : str     absolute path to the .gps file
    bbox       : str     JSON object {"lat_min", "lng_min", "lat_max", "lng_max"}
    approach_m : float   (optional, default 8.0)
    grid_size  : int     (optional, default 100 — smaller for speed in preview)

    Returns image/png.  Results are cached in-process for 30 s.
    """
    import json as _json
    import io

    gps_file = request.args.get(QUERY_GPS_FILE, "").strip()
    bbox_raw = request.args.get(QUERY_BBOX, "").strip()

    if not gps_file:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_GPS_FILE_REQUIRED}), HTTP_BAD_REQUEST
    if not bbox_raw:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_BBOX_REQUIRED}), HTTP_BAD_REQUEST

    if not os.path.isfile(gps_file):
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_GPS_FILE_NOT_FOUND_FMT.format(path=gps_file)}), HTTP_NOT_FOUND

    try:
        bbox_dict = _json.loads(bbox_raw)
        bbox = tuple(float(bbox_dict[k]) for k in BBOX_KEYS)
    except (KeyError, TypeError, ValueError) as e:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_INVALID_BBOX_FMT.format(err=e)}), HTTP_BAD_REQUEST

    try:
        approach_m = float(request.args.get(QUERY_APPROACH_M, GPS_PREVIEW_DEFAULT_APPROACH_M))
    except ValueError:
        approach_m = GPS_PREVIEW_DEFAULT_APPROACH_M
    try:
        grid_size = int(request.args.get(QUERY_GRID_SIZE, GPS_PREVIEW_DEFAULT_GRID_SIZE))
    except ValueError:
        grid_size = GPS_PREVIEW_DEFAULT_GRID_SIZE
    grid_size = max(GPS_PREVIEW_GRID_MIN, min(GPS_PREVIEW_GRID_MAX, grid_size))

    # ── Cache check ────────────────────────────────────────────────────────────
    cache_key = _gps_preview_cache_key(gps_file, bbox_raw, approach_m, grid_size)
    cached = _gps_preview_cache_get(cache_key)
    if cached is not None:
        return cached, HTTP_OK, {HEADER_CONTENT_TYPE: CONTENT_TYPE_PNG, GPS_PREVIEW_CACHE_HEADER: GPS_PREVIEW_CACHE_HIT}

    # ── Build heightmap ────────────────────────────────────────────────────────
    try:
        from gps_heightmap import build_heightmap_from_gps
        import numpy as np
        import matplotlib
        matplotlib.use(GPS_PREVIEW_BACKEND)
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
    except ImportError as e:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_MISSING_DEPENDENCY_FMT.format(err=e)}), HTTP_SERVER_ERROR

    try:
        result = build_heightmap_from_gps(
            gps_path=Path(gps_file),
            bbox=bbox,
            green_polygon_latlng=[],   # no green mask for preview — show full bbox
            approach_m=approach_m,
            grid_size=(grid_size, grid_size),
            vert_exag=GPS_PREVIEW_VERT_EXAG,   # no exaggeration in preview
        )
    except Exception as exc:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_GPS_HEIGHTMAP_ERROR_FMT.format(err=exc)}), HTTP_SERVER_ERROR

    # ── Render to PNG ──────────────────────────────────────────────────────────
    try:
        fig, ax = plt.subplots(figsize=GPS_PREVIEW_FIGSIZE, dpi=GPS_PREVIEW_DPI)
        h = result.heights_mm.copy()
        # Replace NaN with min for display (NaN appears outside mask)
        h_min = float(np.nanmin(h)) if np.any(~np.isnan(h)) else 0.0
        h_display = np.where(np.isnan(h), h_min, h)
        im = ax.imshow(
            h_display,
            origin="lower",
            cmap=GPS_PREVIEW_CMAP,
            aspect="equal",
        )
        ax.set_title(f"{result.raw_points_used} GPS pts", fontsize=GPS_PREVIEW_TITLE_FONTSIZE)
        ax.axis("off")
        fig.colorbar(im, ax=ax, **GPS_PREVIEW_COLORBAR)
        fig.tight_layout(pad=GPS_PREVIEW_TIGHT_PAD)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=GPS_PREVIEW_DPI)
        plt.close(fig)
        png_bytes = buf.getvalue()
    except Exception as exc:
        return jsonify({KEY_STATUS: STATUS_ERROR, KEY_MSG: MSG_RENDER_ERROR_FMT.format(err=exc)}), HTTP_SERVER_ERROR

    _gps_preview_cache_set(cache_key, png_bytes)
    return png_bytes, HTTP_OK, {HEADER_CONTENT_TYPE: CONTENT_TYPE_PNG, GPS_PREVIEW_CACHE_HEADER: GPS_PREVIEW_CACHE_MISS}


@app.route(ROUTE_API_GPS_FILES)
def list_gps_files():
    """Return a list of .gps files found in the course folder for the given course.

    Query params
    ------------
    course : str   course name (looks in GolfCourses/<course>/)

    Returns {KEY_STATUS: STATUS_OK, "files": [{"name": ..., "path": ...}, ...]}
    """
    course = request.args.get(QUERY_COURSE, "").strip()
    files = []
    if course and os.path.isdir(_EGM_BASE):
        course_dir = os.path.join(_EGM_BASE, course)
        if os.path.isdir(course_dir):
            for fname in sorted(os.listdir(course_dir), key=str.casefold):
                if fname.lower().endswith(EXT_GPS):
                    files.append({
                        KEY_NAME: fname,
                        KEY_PATH: os.path.abspath(os.path.join(course_dir, fname)),
                    })
    # Also scan repo root ItWentIn/ for .gps files (legacy / Stracka exports)
    it_went_in = _GOLF_COURSES_PARENT
    if os.path.isdir(it_went_in):
        for fname in sorted(os.listdir(it_went_in), key=str.casefold):
            if fname.lower().endswith(EXT_GPS) or fname.lower().endswith(EXT_TXT):
                # Only include if it looks like GPS data (contains "stracka" or "gps")
                lower = fname.lower()
                if any(hint in lower for hint in GPS_NAME_HINTS):
                    abs_path = os.path.abspath(os.path.join(it_went_in, fname))
                    if not any(f[KEY_PATH] == abs_path for f in files):
                        files.append({KEY_NAME: fname, KEY_PATH: abs_path})
    return jsonify({KEY_STATUS: STATUS_OK, KEY_FILES: files})


# ── Arrow Diagnostic ─────────────────────────────────────────────────────────

@app.route(ROUTE_DIAGNOSTIC_ARROWS, methods=[METHOD_POST])
def diagnostic_arrows():
    """Return an annotated PNG showing every detected arrow in a source image.

    Accepts JSON with:
      - image:       source image filename
      - course:      course name (project's course)
      - imageCourse: course folder where the image lives (may differ)
      - green_points: array of {x, y} — dense spline-sampled boundary points

    Returns: image/png — annotated diagnostic image.

    The image is always returned (never 500 without a visual); errors are
    rendered as text overlaid on a black canvas so Thomas can see what went wrong.
    """
    import io
    import math as _math
    import numpy as _np
    import cv2 as _cv2
    from PIL import Image as _PILImage, ImageDraw as _PILDraw, ImageFont as _PILFont
    from flask import Response as _Response

    DIAG_VERSION = "arrow-diag v1.1"
    DIAG_DATE    = "2026-05-22"

    def _error_image(msg: str, w: int = 800, h: int = 400) -> bytes:
        """Return a PNG with the error message written across a dark canvas."""
        img = _PILImage.new("RGB", (w, h), color=(30, 30, 30))
        draw = _PILDraw.Draw(img)
        # Version badge top-left
        draw.rectangle([4, 4, 4 + 200, 4 + 22], fill=(40, 40, 80))
        draw.text((8, 6), DIAG_VERSION, fill=(180, 200, 255))
        # Error text centre
        draw.text((20, h // 2 - 30), "ERROR", fill=(255, 80, 80))
        # Wrap message crudely at ~80 chars
        words = msg.split()
        line, lines = [], []
        for w_ in words:
            if len(" ".join(line + [w_])) > 80:
                lines.append(" ".join(line))
                line = [w_]
            else:
                line.append(w_)
        if line:
            lines.append(" ".join(line))
        y = h // 2
        for ln in lines[:6]:
            draw.text((20, y), ln, fill=(255, 200, 200))
            y += 18
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _send_png(data: bytes) -> _Response:
        return _Response(data, mimetype="image/png",
                         headers={"Cache-Control": "no-store"})

    # ── Parse request ────────────────────────────────────────────────────────
    try:
        payload = request.get_json(force=True) or {}
        image_name    = payload.get("image", "")
        course        = payload.get("course", "")
        image_course  = payload.get("imageCourse", "") or course
        green_points  = payload.get("green_points", [])
        water_polygons_raw = payload.get("water_polygons", [])

        if not image_name:
            return _send_png(_error_image("No image specified in request."))
        if not green_points:
            return _send_png(_error_image("No green_points in request — draw a green polygon first."))

        # ── Resolve image path ───────────────────────────────────────────────
        img_path = _find_image_path(image_name, preferred_course=image_course)
        if img_path is None:
            return _send_png(_error_image(f"Image not found: {image_name!r}"))

        # ── Load image ───────────────────────────────────────────────────────
        bgr = _cv2.imread(img_path)
        if bgr is None:
            return _send_png(_error_image(f"cv2.imread failed for: {img_path}"))
        img_h, img_w = bgr.shape[:2]

        # ── Build green boundary polygon ─────────────────────────────────────
        green_boundary_px = _np.array(
            [[p[KEY_X], p[KEY_Y]] for p in green_points], dtype=_np.float64
        )

        # ── Build water boundary polygons (for false-positive filtering) ─────
        # Any dark blob whose centroid falls inside a water polygon is not a
        # gradient arrow — it's a water-edge glyph, yardage label, or
        # shoreline marking. Build int32 contours for cv2.pointPolygonTest.
        water_boundaries_i = []
        for wpoly in water_polygons_raw:
            if len(wpoly) >= 3:
                water_boundaries_i.append(
                    _np.array([[p["x"], p["y"]] for p in wpoly], dtype=_np.int32)
                )

        # ── Run arrow detector ───────────────────────────────────────────────
        from gradient_surface_diagnostic import detect_arrows
        all_arrows = detect_arrows(bgr, green_boundary_px, dark_threshold=50, max_arrow_area=600)

        # Filter out any arrow whose centroid is inside a water polygon.
        # These are water-shoreline glyphs that happen to sit inside the green
        # boundary polygon but are not gradient arrows.
        n_water_rejected = 0
        arrows = []
        for a in all_arrows:
            in_water = False
            for wb in water_boundaries_i:
                if _cv2.pointPolygonTest(wb, (float(a["cx"]), float(a["cy"])), measureDist=False) >= 0:
                    in_water = True
                    break
            if in_water:
                n_water_rejected += 1
            else:
                arrows.append(a)
        if n_water_rejected > 0:
            print(f"  diagnostic_arrows: rejected {n_water_rejected} arrow(s) whose centroid "
                  f"fell inside a water polygon (water-glyph false-positive class)")

    except Exception as exc:
        import traceback
        return _send_png(_error_image(f"Pipeline error: {exc}\n{traceback.format_exc()[:400]}"))

    # ── Render annotated image ───────────────────────────────────────────────
    try:
        # Convert BGR → RGB for PIL
        rgb = _cv2.cvtColor(bgr, _cv2.COLOR_BGR2RGB)
        pil_img = _PILImage.fromarray(rgb).convert("RGBA")
        overlay = _PILImage.new("RGBA", pil_img.size, (0, 0, 0, 0))
        draw = _PILDraw.Draw(overlay)

        # Draw green boundary — solid white outline so it's visually unambiguous
        # that all gradient arrows sit on the green, not on water or fringe.
        boundary_pts = [(float(pt[0]), float(pt[1])) for pt in green_boundary_px]
        if len(boundary_pts) >= 2:
            draw.line(boundary_pts + [boundary_pts[0]], fill=(255, 255, 255, 255), width=3)

        ARROW_COLOR  = (255, 0, 220, 230)   # magenta fill
        OUTLINE_COL  = (255, 255, 255, 230)  # white outline
        CIRCLE_R     = 8
        ARROW_LEN    = 24
        LABEL_COLOR  = (255, 255, 255, 255)

        for idx, a in enumerate(arrows):
            cx, cy = float(a["cx"]), float(a["cy"])
            dx, dy = a["dx"], a["dy"]
            label  = str(idx + 1)

            # Arrow glyph: white outline then magenta fill arrowedLine
            ex = cx + dx * ARROW_LEN
            ey = cy + dy * ARROW_LEN
            # Draw as a line with a manual arrowhead in the overlay
            draw.line([(cx, cy), (ex, ey)], fill=OUTLINE_COL, width=5)
            draw.line([(cx, cy), (ex, ey)], fill=ARROW_COLOR, width=3)

            # Arrowhead triangle
            angle = _math.atan2(dy, dx)
            tip_x, tip_y = ex, ey
            LEFT_ANGLE  = angle + _math.pi * 0.75
            RIGHT_ANGLE = angle - _math.pi * 0.75
            HEAD_LEN = 10
            lx = tip_x + _math.cos(LEFT_ANGLE)  * HEAD_LEN
            ly = tip_y + _math.sin(LEFT_ANGLE)  * HEAD_LEN
            rx = tip_x + _math.cos(RIGHT_ANGLE) * HEAD_LEN
            ry = tip_y + _math.sin(RIGHT_ANGLE) * HEAD_LEN
            draw.polygon([(tip_x, tip_y), (lx, ly), (rx, ry)], fill=ARROW_COLOR, outline=OUTLINE_COL)

            # Numbered circle at tail
            draw.ellipse(
                [cx - CIRCLE_R - 1, cy - CIRCLE_R - 1,
                 cx + CIRCLE_R + 1, cy + CIRCLE_R + 1],
                fill=OUTLINE_COL,
            )
            draw.ellipse(
                [cx - CIRCLE_R, cy - CIRCLE_R,
                 cx + CIRCLE_R, cy + CIRCLE_R],
                fill=(30, 0, 60, 230),
            )
            draw.text((cx - CIRCLE_R + 2, cy - CIRCLE_R + 1), label, fill=LABEL_COLOR)

        # Composite overlay onto source
        composite = _PILImage.alpha_composite(pil_img, overlay).convert("RGB")
        draw2 = _PILDraw.Draw(composite)

        # ── Version badge (top-left) ─────────────────────────────────────────
        badge_text = f"{DIAG_VERSION}  {DIAG_DATE}"
        bx0, by0 = 6, 6
        bx1, by1 = bx0 + len(badge_text) * 7 + 10, by0 + 20
        draw2.rectangle([bx0, by0, bx1, by1], fill=(20, 10, 50))
        draw2.rectangle([bx0, by0, bx1, by1], outline=(140, 100, 255), width=1)
        draw2.text((bx0 + 5, by0 + 3), badge_text, fill=(200, 180, 255))

        # ── Summary text (top-right) ─────────────────────────────────────────
        n = len(arrows)
        if n == 0:
            summary = "0 arrows detected"
            s_fill  = (255, 80, 80)
        elif n == 1:
            summary = "1 arrow detected"
            s_fill  = (100, 255, 120)
        else:
            summary = f"{n} arrows detected"
            s_fill  = (100, 255, 120)

        s_w = len(summary) * 8 + 16
        sx0 = img_w - s_w - 4
        draw2.rectangle([sx0 - 2, 6, img_w - 4, 28], fill=(20, 10, 50))
        draw2.rectangle([sx0 - 2, 6, img_w - 4, 28], outline=(80, 200, 80), width=1)
        draw2.text((sx0 + 5, 10), summary, fill=s_fill)

        # ── Legend (bottom-left) ─────────────────────────────────────────────
        if arrows:
            LEGEND_LINE_H = 16
            LEGEND_COLS   = 4  # max columns in legend box
            LEGEND_COL_W  = 180

            legend_lines = []
            for idx, a in enumerate(arrows):
                angle_deg = round(_math.degrees(_math.atan2(a["dy"], a["dx"])))
                legend_lines.append(
                    f"  {idx+1:>2}. ({int(a['cx'])}, {int(a['cy'])})  dir={angle_deg}°"
                )

            # Split into columns if many arrows
            n_rows = max(1, -(-len(legend_lines) // LEGEND_COLS))  # ceil div
            columns = []
            for c in range(LEGEND_COLS):
                col = legend_lines[c * n_rows: (c + 1) * n_rows]
                if col:
                    columns.append(col)

            box_h = n_rows * LEGEND_LINE_H + 24
            box_w = len(columns) * LEGEND_COL_W + 16
            lx0, ly0 = 6, img_h - box_h - 6

            draw2.rectangle([lx0, ly0, lx0 + box_w, ly0 + box_h], fill=(15, 8, 40, 210))
            draw2.rectangle([lx0, ly0, lx0 + box_w, ly0 + box_h], outline=(100, 80, 180), width=1)
            draw2.text((lx0 + 8, ly0 + 5), "Arrow  (x, y)  direction", fill=(160, 140, 220))

            for ci, col in enumerate(columns):
                for ri, line in enumerate(col):
                    draw2.text(
                        (lx0 + 8 + ci * LEGEND_COL_W, ly0 + 18 + ri * LEGEND_LINE_H),
                        line,
                        fill=(220, 210, 240),
                    )

        # ── Encode and return ────────────────────────────────────────────────
        buf = io.BytesIO()
        composite.save(buf, format="PNG")
        return _send_png(buf.getvalue())

    except Exception as exc:
        import traceback
        return _send_png(_error_image(f"Render error: {exc}\n{traceback.format_exc()[:400]}"))


# ── Life Manager routes ──────────────────────────────────────────────────────

def _life_next_due(current_due, recur_rule, recur_interval):
    """Return the next ISO due-date string given a recurrence rule."""
    from datetime import timedelta, date as _date
    import calendar

    if not current_due or not recur_rule:
        return None
    try:
        d = _date.fromisoformat(current_due)
    except ValueError:
        return None

    if recur_rule == "daily":
        d = d + timedelta(days=1)
    elif recur_rule == "weekly":
        d = d + timedelta(days=7)
    elif recur_rule == "monthly":
        # Advance one month, clamping to last day if needed
        month = d.month + 1 if d.month < 12 else 1
        year  = d.year if d.month < 12 else d.year + 1
        day   = min(d.day, calendar.monthrange(year, month)[1])
        d = d.replace(year=year, month=month, day=day)
    elif recur_rule == "yearly":
        try:
            d = d.replace(year=d.year + 1)
        except ValueError:
            # Feb 29 edge-case: fall back to Feb 28
            d = d.replace(year=d.year + 1, day=28)
    elif recur_rule == "interval" and recur_interval:
        d = d + timedelta(days=int(recur_interval))
    else:
        return None
    return d.isoformat()


@app.route("/life")
def life():
    area_filter    = request.args.get("area", "")
    priority_filter = request.args.get("priority", "")
    show_done      = request.args.get("show_done", "0") == "1"

    areas = query("SELECT * FROM life_areas ORDER BY sort_order, name")

    # Build base WHERE clause
    filters = ["li.status = 'open'"] if not show_done else ["li.status IN ('open','done')"]
    args = []
    if area_filter:
        filters.append("li.area_id = ?")
        args.append(area_filter)
    if priority_filter:
        filters.append("li.priority = ?")
        args.append(priority_filter)

    where = " AND ".join(filters)
    items = query(
        f"""SELECT li.*, la.name as area_name, la.color as area_color, la.icon as area_icon
            FROM life_items li
            LEFT JOIN life_areas la ON li.area_id = la.id
            WHERE {where}
            ORDER BY
              CASE li.priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END,
              li.due_date ASC NULLS LAST,
              li.created_at DESC""",
        args,
    )

    today_iso = date.today().isoformat()
    return render("life.html",
                  items=items, areas=areas,
                  area_filter=area_filter, priority_filter=priority_filter,
                  show_done=show_done, today_iso=today_iso)


@app.route("/life/quick-add", methods=["POST"])
def life_quick_add():
    f = request.form
    title = f.get("title", "").strip()
    if not title:
        return redirect(url_for("life"))
    execute(
        """INSERT INTO life_items (title, area_id, priority, due_date)
           VALUES (?, ?, ?, ?)""",
        (
            title,
            f.get("area_id") or None,
            f.get("priority", "normal"),
            f.get("due_date") or None,
        ),
    )
    execute(
        """INSERT INTO activity_log (actor, action, entity_type, details)
           VALUES ('Thomas', 'created_life_item', 'life_item', ?)""",
        (f'Quick-added: "{title}"',),
    )
    if _is_htmx():
        from flask import Response
        return Response("", status=200,
                        headers={"HX-Trigger": "lifeItemUpdated"})
    return redirect(url_for("life"))


@app.route("/life/<int:item_id>/edit", methods=["GET", "POST"])
def life_edit(item_id):
    item  = query("SELECT * FROM life_items WHERE id = ?", (item_id,), one=True)
    areas = query("SELECT * FROM life_areas ORDER BY sort_order, name")
    if not item:
        abort(404)
    if request.method == "POST":
        f = request.form
        execute(
            """UPDATE life_items SET
               title=?, notes=?, area_id=?, priority=?,
               due_date=?, recur_rule=?, recur_interval=?, escalation_days=?,
               updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
               WHERE id=?""",
            (
                f.get("title", "").strip(),
                f.get("notes", "").strip() or None,
                f.get("area_id") or None,
                f.get("priority", "normal"),
                f.get("due_date") or None,
                f.get("recur_rule") or None,
                f.get("recur_interval") or None,
                f.get("escalation_days") or 3,
                item_id,
            ),
        )
        return redirect(url_for("life"))
    return render("life_edit.html", item=item, areas=areas)


@app.route("/life/new", methods=["GET", "POST"])
def life_new():
    areas = query("SELECT * FROM life_areas ORDER BY sort_order, name")
    if request.method == "POST":
        f = request.form
        db = get_db()
        cur = db.execute(
            """INSERT INTO life_items (title, notes, area_id, priority, due_date,
               recur_rule, recur_interval, escalation_days)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f.get("title", "").strip(),
                f.get("notes", "").strip() or None,
                f.get("area_id") or None,
                f.get("priority", "normal"),
                f.get("due_date") or None,
                f.get("recur_rule") or None,
                f.get("recur_interval") or None,
                f.get("escalation_days") or 3,
            ),
        )
        db.commit()
        execute(
            """INSERT INTO activity_log (actor, action, entity_type, details)
               VALUES ('Thomas', 'created_life_item', 'life_item', ?)""",
            (f'Created: "{f.get("title", "").strip()}"',),
        )
        return redirect(url_for("life"))
    return render("life_edit.html", item=None, areas=areas)


@app.route("/life/<int:item_id>/complete", methods=["POST"])
def life_complete(item_id):
    item = query("SELECT * FROM life_items WHERE id = ?", (item_id,), one=True)
    if not item:
        abort(404)
    execute(
        """UPDATE life_items SET status='done', completed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'),
           updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
           WHERE id=?""",
        (item_id,),
    )
    # If recurring, spawn next occurrence
    if item["recur_rule"]:
        next_due = _life_next_due(item["due_date"], item["recur_rule"], item["recur_interval"])
        execute(
            """INSERT INTO life_items
               (title, notes, area_id, priority, due_date, recur_rule, recur_interval,
                recur_anchor, escalation_days)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["title"], item["notes"], item["area_id"], item["priority"],
                next_due, item["recur_rule"], item["recur_interval"],
                item["recur_anchor"], item["escalation_days"],
            ),
        )
    execute(
        """INSERT INTO activity_log (actor, action, entity_type, details)
           VALUES ('Thomas', 'completed_life_item', 'life_item', ?)""",
        (f'Completed: "{item["title"]}"',),
    )
    if _is_htmx():
        # Return a blank 200 so htmx can swap out the item row
        from flask import Response
        return Response("", status=200,
                        headers={"HX-Trigger": "lifeItemUpdated"})
    return redirect(url_for("life"))


@app.route("/life/<int:item_id>/snooze", methods=["POST"])
def life_snooze(item_id):
    item = query("SELECT * FROM life_items WHERE id = ?", (item_id,), one=True)
    if not item:
        abort(404)
    snoozed_until = request.form.get("snoozed_until", "")
    execute(
        """UPDATE life_items SET status='snoozed', snoozed_until=?,
           updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
           WHERE id=?""",
        (snoozed_until or None, item_id),
    )
    if _is_htmx():
        from flask import Response
        return Response("", status=200,
                        headers={"HX-Trigger": "lifeItemUpdated"})
    return redirect(url_for("life"))


@app.route("/life/<int:item_id>/delete", methods=["POST"])
def life_delete(item_id):
    item = query("SELECT * FROM life_items WHERE id = ?", (item_id,), one=True)
    if not item:
        abort(404)
    execute(
        """UPDATE life_items SET status='cancelled',
           updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
           WHERE id=?""",
        (item_id,),
    )
    if _is_htmx():
        from flask import Response
        return Response("", status=200,
                        headers={"HX-Trigger": "lifeItemUpdated"})
    return redirect(url_for("life"))


@app.route("/life/areas", methods=["GET", "POST"])
def life_areas():
    if request.method == "POST":
        action = request.form.get("action", "add")
        if action == "add":
            execute(
                "INSERT INTO life_areas (name, icon, color, sort_order) VALUES (?, ?, ?, ?)",
                (
                    request.form.get("name", "").strip(),
                    request.form.get("icon", "").strip() or None,
                    request.form.get("color", "#6B7280"),
                    request.form.get("sort_order", 99),
                ),
            )
        elif action == "edit":
            area_id = request.form.get("area_id")
            execute(
                """UPDATE life_areas SET name=?, icon=?, color=?,
                   updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
                   WHERE id=?""",
                (
                    request.form.get("name", "").strip(),
                    request.form.get("icon", "").strip() or None,
                    request.form.get("color", "#6B7280"),
                    area_id,
                ),
            )
        return redirect(url_for("life_areas"))

    areas = query("SELECT * FROM life_areas ORDER BY sort_order, name")
    return render("life_areas.html", areas=areas)


# ── Plaque text generator routes ────────────────────────────────────────────

owner_inbox = os.path.join(os.path.dirname(__file__), "..", "owner_inbox")


@app.route(ROUTE_PLAQUE)
def plaque_page():
    plate_text_path = os.path.join(os.path.dirname(__file__), "plate_text.py")
    try:
        mtime = os.path.getmtime(plate_text_path)
        from datetime import datetime
        last_modified = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
    except Exception:
        last_modified = ""
    return render("plaque.html", last_modified=last_modified)


@app.route(ROUTE_API_FONTS)
def api_fonts():
    from plate_text import list_available_fonts
    return jsonify({"fonts": list_available_fonts()})


def _slug_from_lines(line1: str, line2: str) -> str:
    return re.sub(PLATE_SLUG_STRIP_RE, '', (line1 or line2)).strip().replace(' ', '_') or PLATE_DEFAULT_SLUG


def _normalize_course_key(s: str) -> str:
    """Normalize a course name or user input for comparison.

    Rules applied in order:
    1. Lowercase.
    2. Replace en-dash (U+2013), em-dash (U+2014), and minus (U+2212) with ASCII hyphen.
    3. Collapse runs of whitespace to a single space.
    4. Strip all spaces immediately around hyphens so "a - b", "a-b", "a -b" all
       become the canonical form "a-b" (no spaces around hyphen).
    5. Strip leading/trailing whitespace.
    """
    s = s.lower()
    # Step 2 – Unicode dash variants → ASCII hyphen
    s = s.replace('–', '-').replace('—', '-').replace('−', '-')
    # Step 3 – collapse whitespace
    s = re.sub(r'\s+', ' ', s)
    # Step 4 – remove spaces around hyphens
    s = re.sub(r'\s*-\s*', '-', s)
    # Step 5 – strip edges
    return s.strip()


def _match_courses_from_line(course_line: str) -> list[str]:
    """Find all existing GolfCourses/ subfolders whose normalized name is a
    case-insensitive substring of the normalized course_line, or vice-versa.
    Returns all matches sorted longest-first so the caller can decide whether
    the result is unambiguous (1 match), ambiguous (>1), or absent (0)."""
    from generate_stl_3mf import EGM_BASE
    if not course_line or not os.path.isdir(EGM_BASE):
        return []
    try:
        entries = [e for e in os.listdir(EGM_BASE)
                   if os.path.isdir(os.path.join(EGM_BASE, e)) and not e.startswith('.')]
    except OSError:
        return []
    needle = _normalize_course_key(course_line)
    matches: list[str] = []
    for name in entries:
        haystack = _normalize_course_key(name)
        if needle in haystack or haystack in needle:
            matches.append(name)
    matches.sort(key=len, reverse=True)
    return matches


def _smtp_config():
    """Read SMTP settings from environment variables.

    Returns a 7-tuple:
        (smtp_host, smtp_port, smtp_user, smtp_pass, smtp_from, smtp_to, missing_vars)

    ``missing_vars`` is a list of env var names whose values are empty/absent
    from the three *required* vars (SMTP_HOST, SMTP_USER, SMTP_PASS).
    If ``missing_vars`` is non-empty the caller must treat SMTP as unconfigured.
    """
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    smtp_pass = os.environ.get("SMTP_PASS", "").strip()
    missing_vars = [
        name for name, val in [("SMTP_HOST", smtp_host), ("SMTP_USER", smtp_user), ("SMTP_PASS", smtp_pass)]
        if not val
    ]
    smtp_port = int(os.environ.get("SMTP_PORT", SMTP_DEFAULT_PORT))
    smtp_from = os.environ.get("SMTP_FROM", smtp_user).strip() or smtp_user
    smtp_to   = os.environ.get("SMTP_TO", SMTP_DEFAULT_TO).strip()
    return smtp_host, smtp_port, smtp_user, smtp_pass, smtp_from, smtp_to, missing_vars


@app.route(ROUTE_API_GENERATE_PLATE, methods=[METHOD_POST])
def api_generate_plate():
    import smtplib
    import tempfile
    from email.message import EmailMessage

    data = request.get_json(force=True)
    line1 = data.get("line1", "").strip()
    line2 = data.get("line2", "").strip()
    line3 = data.get("line3", "").strip()
    open_in_slicer = bool(data.get("open_in_slicer"))
    if not (line1 or line2 or line3):
        return jsonify({"status": "error", "msg": "Provide at least one line of text."}), 400

    # ── SMTP config from environment ──────────────────────────────────────────
    smtp_host, smtp_port, smtp_user, smtp_pass, smtp_from, smtp_to, missing_vars = _smtp_config()
    warnings: list[str] = []
    if missing_vars:
        email_mode = False
        missing_str = ", ".join(missing_vars)
        warning_msg = f"SMTP not configured — email skipped. Missing: {missing_str}"
        app.logger.warning(warning_msg)
        warnings.append(warning_msg)
    else:
        email_mode = True

    # ── Generate 3MF to a temp file ──────────────────────────────────────────
    slug = _slug_from_lines(line1, line2)
    attachment_name = f"{slug}.3mf"
    tmp_path = None
    try:
        from plate_text import generate_plate_3mf
        with tempfile.NamedTemporaryFile(suffix=".3mf", delete=False) as tf:
            tmp_path = tf.name
        generate_plate_3mf(line1, line2, line3, tmp_path,
                           font_family=PLATE_FONT_FAMILY, bold=PLATE_BOLD, italic=PLATE_ITALIC)
        with open(tmp_path, "rb") as fh:
            attachment_bytes = fh.read()
    except Exception as exc:
        return jsonify({"status": "error", "msg": f"3MF generation failed: {exc}"}), 500
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # ── Write local file when: SMTP is off, OR open_in_slicer requested ──────
    stable_path = None
    if (not email_mode) or open_in_slicer:
        stable_path = os.path.expanduser(PLATE_DOWNLOADS_FMT.format(name=attachment_name))
        with open(stable_path, "wb") as fh:
            fh.write(attachment_bytes)

    # ── Email path (only when fully configured) ───────────────────────────────
    email_sent = False
    smtp_error_resp = None
    if email_mode:
        # Build email
        subject_line = line1 or line2 or line3
        msg = EmailMessage()
        msg["Subject"] = f"Plaque: {subject_line}"
        msg["From"]    = smtp_from
        msg["To"]      = smtp_to
        body_lines = [f"Line 1: {line1}", f"Line 2: {line2}", f"Line 3: {line3}"]
        msg.set_content("\n".join(body_lines))
        msg.add_attachment(
            attachment_bytes,
            maintype="application",
            subtype="octet-stream",
            filename=attachment_name,
        )

        # ── Send via STARTTLS ─────────────────────────────────────────────────
        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=SMTP_TIMEOUT_S) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            email_sent = True
        except smtplib.SMTPAuthenticationError as exc:
            smtp_error_resp = jsonify({
                "status": "error",
                "msg": f"SMTP authentication failed (check SMTP_USER / SMTP_PASS): {exc.smtp_error.decode(errors='replace')}",
            }), 500
        except ConnectionRefusedError:
            smtp_error_resp = jsonify({
                "status": "error",
                "msg": f"Connection refused to {smtp_host}:{smtp_port}. Check SMTP_HOST / SMTP_PORT.",
            }), 500
        except smtplib.SMTPConnectError as exc:
            smtp_error_resp = jsonify({
                "status": "error",
                "msg": f"Could not connect to {smtp_host}:{smtp_port}: {exc}",
            }), 500
        except smtplib.SMTPException as exc:
            smtp_error_resp = jsonify({
                "status": "error",
                "msg": f"SMTP error: {exc}",
            }), 500
        except OSError as exc:
            smtp_error_resp = jsonify({
                "status": "error",
                "msg": f"Network error connecting to {smtp_host}:{smtp_port}: {exc}",
            }), 500

        if smtp_error_resp is not None:
            return smtp_error_resp

    # ── Open in default slicer (macOS file-association) ──────────────────────
    # Uses `open <file>` which honours the OS-registered .3mf handler —
    # whatever the user has set via Finder → Get Info → Open with → Change All.
    # If `open` exits non-zero there is no registered handler; surface the
    # error so the user can fix their file association rather than silently
    # falling back to a hardcoded app path.
    slicer_opened = None
    slicer_error  = None
    if open_in_slicer and stable_path:
        import subprocess
        try:
            result = subprocess.run(
                ["open", stable_path],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                slicer_opened = True
            else:
                slicer_opened = False
                stderr_text = (result.stderr or b"").decode(errors="replace").strip()
                slicer_error = stderr_text or (
                    f"`open` exited with code {result.returncode}. "
                    "Check your .3mf file association: Finder → right-click a .3mf → "
                    "Get Info → Open with → Change All."
                )
        except subprocess.TimeoutExpired:
            slicer_opened = False
            slicer_error  = "Timed out waiting for `open` to hand file to the default slicer."
        except Exception as exc:
            slicer_opened = False
            slicer_error  = str(exc)

    # ── Compose delivery field ────────────────────────────────────────────────
    if email_sent and stable_path:
        delivery = "email+local"
    elif email_sent:
        delivery = "email"
    else:
        delivery = "local"

    return jsonify({
        "status":        "ok",
        "delivery":      delivery,
        "email_to":      smtp_to if email_sent else None,
        "local_path":    stable_path,
        "warnings":      warnings,
        # Legacy fields kept for any existing clients
        "msg":           f"Emailed to {smtp_to}" if email_sent else f"Saved to {stable_path}",
        "recipient":     smtp_to if email_sent else None,
        "stable_path":   stable_path,
        "slicer_opened": slicer_opened,
        "slicer_error":  slicer_error,
    })


# ── Run ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # v5.75: surface missing generator packages at server start (never crash on it).
    try:
        _dep_status = dependency_preflight.status_report()
        if _dep_status["ok"]:
            print("[startup] Generator dependencies: all present.")
        else:
            print("[startup] WARNING: " + _dep_status["message"])
    except Exception as _dep_exc:
        print(f"[startup] Dependency check itself failed: {_dep_exc}")
    # use_reloader explicit so edits pick up regardless of how the process is launched.
    # debug=False avoids Werkzeug's DebuggedApplication wrapper, which creates a
    # multiprocessing.Value POSIX semaphore that leaked after ~16h and deadlocked
    # the worker on _PySemaphore_Wait (see owner_inbox/dashboard_deadlock_rca_2026-10-13.md).
    app.run(debug=False, host=SERVER_HOST, port=SERVER_PORT, use_reloader=SERVER_USE_RELOADER)
