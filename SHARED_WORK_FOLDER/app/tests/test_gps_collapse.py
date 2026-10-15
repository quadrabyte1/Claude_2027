"""
test_gps_collapse.py  —  v4.60 · GPS backend panel collapse tests
Bug→TDD: RED written first against pre-v4.60 editor.html (no wrapper div),
then GREEN after adding #gps-backend-body + toggle handler.

Since there is no JS runtime in the Python test suite, tests use:
  1. HTML structure assertions (regex / string search over the served page).
  2. JS code-shape guards (regex over the inline JS) to confirm the toggle
     binding and init call are present.

Test numbers continue from Phase 2 (T1-T15 used).  This file: T16-T19.
"""
import os
import re
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def editor_html_source():
    """Return the raw text of editor.html from the templates folder."""
    here = os.path.dirname(__file__)
    tpl_path = os.path.join(here, "..", "templates", "editor.html")
    with open(tpl_path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    """Flask test client with a temp DB so the live DB is never touched."""
    tmp_db = str(tmp_path / "workspace.db")
    import app as _app_module
    monkeypatch.setattr(_app_module, "DB_PATH", tmp_db)
    _app_module.app.config["TESTING"] = True
    with _app_module.app.test_client() as client:
        yield client


# ──────────────────────────────────────────────────────────────────────────────
# T16–T18 (updated): GPS Backend panel is REMOVED from the editor UI.
# The JS GPS state/load/save code stays so EGM gpsBackend blocks round-trip,
# but no markup for the panel should be rendered any more.
# ──────────────────────────────────────────────────────────────────────────────

GPS_PANEL_MARKERS = [
    'id="gps-backend-body"',
    '>GPS Backend<',
    'Use GPS backend',
    'x-model="gpsEnabled"',
    'x-ref="gpsMapCanvas"',
    'x-model="gpsFile"',
    'x-model.number="gpsVertExag"',
    'x-model.number="gpsApproachM"',
    'x-model.number="gpsGridSize"',
    'Snap to green',
    'GPS Backend panel',
]


class TestGpsBackendPanelRemoved:

    def test_source_has_no_gps_panel_markup(self, editor_html_source):
        """T16a: editor.html renders no GPS Backend panel markup."""
        for marker in GPS_PANEL_MARKERS:
            assert marker not in editor_html_source, (
                f"GPS panel marker still present in editor.html: {marker}"
            )

    def test_js_gps_state_retained(self, editor_html_source):
        """T16b: JS GPS state is kept so EGM gpsBackend blocks still round-trip."""
        assert "gpsEnabled: false," in editor_html_source
        assert "gpsBackend = {" in editor_html_source or "data.gpsBackend = {" in editor_html_source


# ──────────────────────────────────────────────────────────────────────────────
# T18: Served page — /editor route has no GPS panel
# ──────────────────────────────────────────────────────────────────────────────

class TestServedEditorPageNoGps:

    def test_served_page_has_no_gps_panel(self, app_client):
        """T18: GET /editor returns 200 and no GPS Backend panel markup."""
        resp = app_client.get("/editor")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8", errors="replace")
        assert "GPS Backend" not in html
        assert 'id="gps-backend-body"' not in html
        assert 'x-model="gpsEnabled"' not in html


# ──────────────────────────────────────────────────────────────────────────────
# T19: Persistence — gpsEnabled state initialisation in loadProject / startNew
# ──────────────────────────────────────────────────────────────────────────────

class TestGpsEnabledPersistence:

    def test_load_project_sets_gps_enabled_true(self, editor_html_source):
        """T19a: loadProject() assigns gpsEnabled from gpsBackend.enabled (true path)."""
        # Verify the JS line that sets gpsEnabled from loaded data is present
        assert "this.gpsEnabled  = gps.enabled === true;" in editor_html_source or \
               "this.gpsEnabled = gps.enabled === true;" in editor_html_source, (
            "loadProject() must set this.gpsEnabled from gps.enabled."
        )

    def test_start_new_project_resets_gps_enabled_false(self, editor_html_source):
        """T19b: startNewProject() resets gpsEnabled to false."""
        # The startNewProject reset block should set gpsEnabled to false
        assert "this.gpsEnabled   = false;" in editor_html_source or \
               "this.gpsEnabled = false;" in editor_html_source, (
            "startNewProject() must reset this.gpsEnabled = false."
        )

    def test_gps_enabled_default_is_false_in_data(self, editor_html_source):
        """T19c: The Alpine data initializer declares gpsEnabled: false as default."""
        assert "gpsEnabled: false," in editor_html_source, (
            "The data() object must initialize gpsEnabled: false so new "
            "projects and page-loads start with the panel collapsed."
        )

