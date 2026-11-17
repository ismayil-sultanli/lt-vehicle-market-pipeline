"""Headless smoke tests of the Streamlit dashboard (streamlit.testing.AppTest).

They run the real app script against the committed snapshot of the marts and
fail on any exception, so a renamed column in dbt breaks CI, not the live page.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from lt_vehicle_market.export import EXPORTED_MARTS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dashboard" / "app.py"
SNAPSHOT = ROOT / "dashboard" / "snapshot"


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AppTest:
    # point away from any local pipeline output so the snapshot is used
    monkeypatch.delenv("LVM_MARTS_URL", raising=False)
    monkeypatch.setenv("LVM_DATA_DIR", str(tmp_path))
    return AppTest.from_file(str(APP), default_timeout=60)


def test_snapshot_contains_every_exported_mart():
    assert {p.stem for p in SNAPSHOT.glob("*.parquet")} == set(EXPORTED_MARTS)
    for mart in EXPORTED_MARTS:
        assert len(pd.read_parquet(SNAPSHOT / f"{mart}.parquet")) > 0, mart


def test_both_tabs_render_without_errors(app: AppTest):
    app.run()
    assert not app.exception, app.exception
    assert not app.error, [e.value for e in app.error]
    assert [tab.label for tab in app.tabs] == ["Vehicle market", "Vehicle fleet"]
    headings = {h.value for h in app.subheader}
    assert "Did the cash limit change how cars are paid for?" in headings
    assert "Models on the road" in headings
    assert "snapshot" in app.caption[0].value


def test_filters_and_make_selector_do_not_break_the_page(app: AppTest):
    app.run()
    first_year = app.select_slider[0].options[0]
    app.select_slider[0].set_value((first_year, first_year)).run()
    assert not app.exception, app.exception

    app.selectbox[0].set_value("Toyota").run()
    assert not app.exception, app.exception
    assert not app.error, [e.value for e in app.error]


def test_missing_marts_show_an_error_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("LVM_MARTS_URL", str(tmp_path / "nowhere"))
    app = AppTest.from_file(str(APP), default_timeout=60)
    app.run()
    assert not app.exception
    assert any("Could not read the marts" in e.value for e in app.error)
