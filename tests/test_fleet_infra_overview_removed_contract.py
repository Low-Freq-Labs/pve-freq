from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_HTML = (ROOT / "freq/data/web/app.html").read_text()
APP_JS = (ROOT / "freq/data/web/js/app.js").read_text()


def test_fleet_infra_page_does_not_render_overview_section():
    assert 'id="fleet-sec-overview"' not in APP_HTML
    fleet_view = APP_HTML.split('id="fleet-view"', 1)[1].split('<!-- DOCKER VIEW -->', 1)[0]
    assert "<h3>Overview</h3>" not in fleet_view
    assert "home-pve-summary" not in fleet_view
    assert "home-infra" not in fleet_view
    assert "home-media" not in fleet_view


def test_fleet_section_registry_skips_removed_overview_section():
    assert "fleet-sec-overview" not in APP_JS.split("var VIEW_SECTIONS=", 1)[1].split("};", 1)[0]
