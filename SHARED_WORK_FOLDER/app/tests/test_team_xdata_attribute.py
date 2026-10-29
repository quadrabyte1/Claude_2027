"""
test_team_xdata_attribute.py  -  Bug->TDD: /team model-tier x-data must survive HTML parsing.

Bug: `versions: {{ model_versions | tojson }}` emitted raw double quotes inside a
double-quoted x-data attribute, truncating it; Alpine skipped the component.
Renders /team against a TEMP DB (never the live db/workspace.db).
"""
import os
import sys
from html.parser import HTMLParser

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TEAM_URL = "/team"
TEMP_DB_NAME = "team_xdata_test.db"
XDATA_ATTR = "x-data"
MODEL_ATTR_MARKER = "versions:"
CLOAK_ATTR = "x-cloak"
DROPDOWN_PANEL_ATTR = "x-show"
DROPDOWN_PANEL_VALUE = "open"


class _AttrCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.xdata = []
        self.panels = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if XDATA_ATTR in d and MODEL_ATTR_MARKER in (d[XDATA_ATTR] or ""):
            self.xdata.append(d[XDATA_ATTR])
        if d.get(DROPDOWN_PANEL_ATTR) == DROPDOWN_PANEL_VALUE:
            self.panels.append(d)


@pytest.fixture
def parsed(tmp_path, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / TEMP_DB_NAME))
    app_module.init_db()
    html = app_module.app.test_client().get(TEAM_URL).get_data(as_text=True)
    p = _AttrCollector()
    p.feed(html)
    return app_module, p


def test_xdata_contains_every_model_version(parsed):
    app_module, p = parsed
    assert p.xdata, "no model-tier x-data component found on /team"
    for tier, info in app_module.MODEL_VERSIONS.items():
        for value in (info["label"], info["id"]):
            assert value in p.xdata[0], f"{tier}:{value} missing from parsed x-data"


def test_dropdown_panel_is_cloaked(parsed):
    _, p = parsed
    assert p.panels, "dropdown panel not found"
    assert all(CLOAK_ATTR in d for d in p.panels)
