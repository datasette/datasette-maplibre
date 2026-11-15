import json
import nest_asyncio
from playwright import sync_api
import pytest
import re

nest_asyncio.apply()
expect = sync_api.expect


@pytest.fixture
def errors(page):
    errors = []
    page.on("pageerror", lambda error: errors.append(error))
    yield errors
    assert errors == []


def ready(page):
    "The overview map, once its style and layers have loaded"
    overview = page.locator(".dmap")
    expect(overview).to_have_attribute("data-style-ready", "true")
    expect(overview.locator(".dmap-map canvas")).to_be_visible()
    return overview


def click_feature(page, lng, lat):
    page.wait_for_function("() => datasette.maplibre.map.loaded()")
    point = page.evaluate(
        "([lng, lat]) => { const p = datasette.maplibre.map.project([lng, lat]); return [p.x, p.y]; }",
        [lng, lat],
    )
    page.locator(".dmap-map canvas").click(position={"x": point[0], "y": point[1]})


@pytest.mark.parametrize(
    "path",
    ("/data/two_points", "/data?sql=select+*+from+two_points"),
)
def test_points_are_displayed(ds_server, page, errors, path):
    page.goto(ds_server + path)
    overview = ready(page)
    expect(overview).to_have_attribute("data-points", "2")
    expect(overview).to_have_attribute("data-complete", "true")
    # Every row has a location and they have all loaded
    expect(overview.locator(".dmap-progress")).to_be_empty()
    assert page.evaluate("() => Boolean(datasette.maplibre.map.getLayer('dmap-point'))")


def test_row_page(ds_server, page, errors):
    page.goto(ds_server + "/data/two_points/1")
    expect(ready(page)).to_have_attribute("data-points", "1")


def test_load_all_paginates_through_table(ds_server, page, errors):
    responses = []
    page.on(
        "response",
        lambda response: ".json" in response.url and responses.append(response),
    )
    page.goto(ds_server + "/data/paginated")
    overview = ready(page)
    progress = overview.locator(".dmap-progress")
    expect(progress).to_contain_text("Showing 10 of 25 (40%)")
    progress.get_by_role("button", name="load all").click()
    expect(overview).to_have_attribute("data-points", "25")
    expect(progress).to_be_empty()
    assert [response.status for response in responses] == [200, 200, 200]


def test_loading_more_rows_does_not_move_a_map_that_has_been_moved(
    ds_server, page, errors
):
    page.goto(ds_server + "/data/paginated")
    overview = ready(page)
    page.evaluate("() => datasette.maplibre.map.jumpTo({center: [10, 50], zoom: 5})")
    overview.get_by_role("button", name="load all").click()
    expect(overview).to_have_attribute("data-points", "25")
    assert page.evaluate("() => datasette.maplibre.map.getZoom()") == 5


def test_map_is_fitted_to_all_rows_as_they_load(ds_server, page, errors):
    page.goto(ds_server + "/data/paginated")
    overview = ready(page)
    before = page.evaluate("() => datasette.maplibre.map.getZoom()")
    overview.get_by_role("button", name="load all").click()
    expect(overview).to_have_attribute("data-points", "25")
    assert page.evaluate("() => datasette.maplibre.map.getZoom()") < before
    expect(overview).to_have_attribute("data-moved", "false")


def test_scrolling_the_page_does_not_zoom_the_map(ds_server, page, errors):
    page.goto(ds_server + "/data/two_points")
    ready(page)
    page.wait_for_function("() => datasette.maplibre.map.loaded()")
    before = page.evaluate("() => datasette.maplibre.map.getZoom()")
    page.locator(".dmap-map canvas").hover()
    page.mouse.wheel(0, 300)
    page.wait_for_timeout(500)
    assert page.evaluate("() => datasette.maplibre.map.getZoom()") == before


@pytest.mark.parametrize(
    "path",
    ("/data/no_locations", "/data?sql=select+*+from+no_locations"),
)
def test_no_map_if_no_rows_have_a_location(ds_server, page, errors, path):
    with page.expect_response(lambda response: ".json" in response.url):
        page.goto(ds_server + path)
    page.wait_for_load_state("networkidle")
    expect(page.locator("table.rows-and-columns")).to_be_visible()
    expect(page.locator(".dmap")).to_have_count(0)


def test_map_appears_once_a_location_has_loaded(ds_server, page, errors):
    page.goto(ds_server + "/data/locations_on_last_page")
    progress = page.locator(".dmap-progress")
    expect(progress).to_contain_text("No locations in the first 10 of 25 rows")
    expect(page.locator(".dmap-map")).to_have_count(0)
    progress.get_by_role("button", name="load all").click()
    overview = ready(page)
    expect(overview).to_have_attribute("data-points", "5")
    expect(progress).to_have_text("5 of 25 rows have a location")


def test_view_can_be_switched(ds_server, page, errors):
    page.goto(ds_server + "/data/paginated")
    overview = ready(page)
    expect(overview).to_have_attribute("data-view", "clusters")
    assert page.evaluate("() => Boolean(datasette.maplibre.map.getLayer('dmap-cluster'))")
    overview.locator("select[name=dmap-view]").select_option("heatmap")
    expect(overview).to_have_attribute("data-view", "heatmap")
    layers = page.evaluate(
        "() => ['dmap-heat', 'dmap-cluster'].map(id => Boolean(datasette.maplibre.map.getLayer(id)))"
    )
    assert layers == [True, False]


def test_view_is_configurable(ds_server, page, errors):
    page.goto(ds_server + "/data/two_points")
    expect(ready(page)).to_have_attribute("data-view", "points")
    assert page.evaluate(
        "() => datasette.maplibre.map.getSource('dmap-points').serialize().cluster"
    ) in (False, None)


def test_style_can_be_switched(ds_server, page, errors):
    page.goto(ds_server + "/data/two_points")
    overview = ready(page)
    select = overview.locator("select[name=dmap-style]")
    expect(select).to_have_value("Custom")
    select.select_option("Other")
    page.wait_for_function(
        "() => Boolean(datasette.maplibre.map.getLayer('background'))"
        " && Boolean(datasette.maplibre.map.getLayer('dmap-point'))"
    )
    expect(overview).to_have_attribute("data-points", "2")


def test_color_by_category(ds_server, page, errors):
    page.goto(ds_server + "/data/paginated")
    overview = ready(page)
    select = overview.locator("select[name=dmap-color]")
    # Not the latitude and longitude columns
    assert select.locator("option").all_text_contents() == [
        "(none)",
        "id",
        "category",
        "score",
    ]
    select.select_option("category")
    items = overview.locator(".dmap-legend-item")
    expect(items).to_have_text(["red (4)", "green (3)", "blue (3)"])
    # The legend is updated as more rows load
    overview.get_by_role("button", name="load all").click()
    expect(items).to_have_text(["red (9)", "green (8)", "blue (8)"])
    select.select_option("")
    expect(items).to_have_count(0)


def test_color_by_number(ds_server, page, errors):
    page.goto(ds_server + "/data/paginated")
    overview = ready(page)
    overview.get_by_role("button", name="load all").click()
    expect(overview).to_have_attribute("data-points", "25")
    overview.locator("select[name=dmap-color]").select_option("score")
    expect(overview.locator(".dmap-legend")).to_have_text("score: 0240")
    expect(overview.locator(".dmap-ramp")).to_be_visible()


def test_filter_to_this_area(ds_server, page, errors):
    page.goto(ds_server + "/data/paginated")
    overview = ready(page)
    expect(overview.locator(".dmap-clear-area")).to_have_count(0)
    page.evaluate(
        "() => datasette.maplibre.map.fitBounds([[-122.045, 37.0], [-122.0, 37.045]], {animate: false, padding: 0})"
    )
    overview.get_by_role("button", name="Filter to this area").click()
    page.wait_for_url(re.compile("latitude__gte="))
    for param in ("latitude__lte", "longitude__gte", "longitude__lte"):
        assert param + "=" in page.url
    overview = ready(page)
    count = int(overview.get_attribute("data-points"))
    assert 5 <= count < 10
    expect(page.locator("table.rows-and-columns tbody tr")).to_have_count(count)
    overview.get_by_role("button", name="Clear area filter").click()
    page.wait_for_url(ds_server + "/data/paginated")


def test_no_filter_button_for_sql_queries(ds_server, page, errors):
    page.goto(ds_server + "/data?sql=select+*+from+two_points")
    overview = ready(page)
    expect(overview.locator(".dmap-filter-area")).to_have_count(0)
    expect(overview.locator(".dmap-download")).to_be_visible()


def test_click_point_shows_popup_and_marks_table_row(ds_server, page, errors):
    page.goto(ds_server + "/data/two_points")
    overview = ready(page)
    click_feature(page, -121.9511, 37.3184)
    popup = overview.locator(".dmap-popup")
    expect(popup).to_contain_text("San Jose")
    expect(popup.locator("dt")).to_have_text(["id", "name", "lat", "lng"])
    rows = page.locator("table.rows-and-columns tbody tr")
    expect(rows.nth(1)).to_have_class(re.compile("dmap-row-active"))
    expect(rows.nth(0)).not_to_have_class(re.compile("dmap-row-active"))
    expect(popup.get_by_text("Show in table")).to_be_visible()


def test_popup_escapes_html(ds_server, page, errors):
    page.goto(ds_server + "/data/two_points")
    overview = ready(page)
    click_feature(page, -122.0024, 37.0167)
    popup = overview.locator(".dmap-popup")
    expect(popup).to_contain_text("Santa Cruz <b>")
    expect(popup.locator("b")).to_have_count(0)


def test_hovering_table_row_highlights_it_on_the_map(ds_server, page, errors):
    page.goto(ds_server + "/data/two_points")
    overview = ready(page)
    page.locator("table.rows-and-columns tbody tr").nth(1).hover()
    expect(overview).to_have_attribute("data-highlight", "1")
    highlighted = page.evaluate(
        "() => datasette.maplibre.map.getSource('dmap-highlight').serialize().data.features.length"
    )
    assert highlighted == 1


def test_download_geojson(ds_server, page, errors):
    page.goto(ds_server + "/data/two_points")
    overview = ready(page)
    with page.expect_download() as download_info:
        overview.get_by_role("button", name="Download GeoJSON").click()
    download = download_info.value
    assert download.suggested_filename == "two_points.geojson"
    with open(download.path()) as fp:
        collection = json.load(fp)
    assert collection["type"] == "FeatureCollection"
    assert [f["properties"]["name"] for f in collection["features"]] == [
        "Santa Cruz <b>",
        "San Jose",
    ]
    assert collection["features"][1]["geometry"] == {
        "type": "Point",
        "coordinates": [-121.9511, 37.3184],
    }


def test_map_position_is_kept_in_the_url(ds_server, page, errors):
    page.goto(ds_server + "/data/two_points")
    ready(page)
    page.evaluate("() => datasette.maplibre.map.jumpTo({center: [10, 50], zoom: 5})")
    page.wait_for_url(re.compile(r"#map=5/50/10"))
    # Reloading keeps that position instead of fitting to the points
    page.reload()
    ready(page)
    page.wait_for_function("() => datasette.maplibre.map.loaded()")
    assert page.evaluate("() => datasette.maplibre.map.getZoom()") == 5


def test_toolbar_state_is_kept_in_the_url(ds_server, page, errors):
    page.goto(ds_server + "/data/paginated")
    overview = ready(page)
    overview.locator("select[name=dmap-view]").select_option("heatmap")
    overview.locator("select[name=dmap-color]").select_option("category")
    overview.locator("select[name=dmap-style]").select_option("Other")
    page.wait_for_url(re.compile("style=Other"))
    for expected in ("view=heatmap", "color=category", "map="):
        assert expected in page.url
    # Going back to the configured defaults removes them again
    overview.locator("select[name=dmap-view]").select_option("clusters")
    overview.locator("select[name=dmap-color]").select_option("")
    assert "view=" not in page.url
    assert "color=" not in page.url


def test_toolbar_state_can_be_set_by_a_link(ds_server, page, errors):
    page.goto(
        ds_server
        + "/data/paginated#map=5/50/10&view=points&color=category&style=Other"
    )
    overview = ready(page)
    expect(overview).to_have_attribute("data-view", "points")
    expect(overview.locator("select[name=dmap-view]")).to_have_value("points")
    expect(overview.locator("select[name=dmap-color]")).to_have_value("category")
    expect(overview.locator("select[name=dmap-style]")).to_have_value("Other")
    expect(overview.locator(".dmap-legend-item")).to_have_count(3)
    page.wait_for_function(
        "() => Boolean(datasette.maplibre.map.getLayer('background'))"
    )
    assert page.evaluate("() => datasette.maplibre.map.getZoom()") == 5
    # Moving the map keeps the other parameters
    page.evaluate("() => datasette.maplibre.map.jumpTo({zoom: 6})")
    page.wait_for_url(re.compile("map=6/"))
    assert "view=points" in page.url and "style=Other" in page.url


def test_world_is_not_repeated_side_by_side(ds_server, page, errors):
    page.set_viewport_size({"width": 1200, "height": 900})
    page.goto(ds_server + "/data/two_points")
    ready(page)
    page.evaluate("() => datasette.maplibre.map.jumpTo({zoom: 0})")
    zoom, width = page.evaluate(
        "() => [datasette.maplibre.map.getZoom(), datasette.maplibre.map.getContainer().clientWidth]"
    )
    # MapLibre tiles are 512 pixels, so the world is 512 * 2 ** zoom wide
    assert 512 * 2**zoom == pytest.approx(width)


def test_geojson_cells(ds_server, page, errors):
    page.set_viewport_size({"width": 1200, "height": 900})
    page.goto(ds_server + "/data/shapes")
    cells = page.locator("td .dmap-cell")
    expect(cells).to_have_count(6)
    # Every cell has an SVG outline straight away
    expect(cells.locator("svg path")).to_have_count(6)
    # The cells on screen become maps, up to max_cell_maps
    expect(page.locator(".dmap-cell[data-live=true]")).to_have_count(2)
    # The overview map shows all six shapes, without points or clusters
    overview = ready(page)
    expect(overview).to_have_attribute("data-shapes", "6")
    expect(overview).to_have_attribute("data-points", "0")
    # Shapes too small to see at this zoom level are marked with a circle
    page.wait_for_function("() => datasette.maplibre.map.loaded()")
    count_centers = "() => datasette.maplibre.map.queryRenderedFeatures({layers: ['dmap-center']}).length"
    page.evaluate("() => datasette.maplibre.map.jumpTo({zoom: 10})")
    page.wait_for_function("() => datasette.maplibre.map.loaded()")
    assert page.evaluate(count_centers) == 0
    page.evaluate("() => datasette.maplibre.map.jumpTo({zoom: 1})")
    page.wait_for_function("() => datasette.maplibre.map.loaded()")
    assert page.evaluate(count_centers) > 0
    # Scrolling to the last cell makes it live, and another falls back to SVG
    cells.nth(5).scroll_into_view_if_needed()
    expect(cells.nth(5)).to_have_attribute("data-live", "true")
    expect(page.locator(".dmap-cell[data-live=true]")).to_have_count(2)
    expect(page.locator(".dmap-cell .maplibregl-canvas")).to_have_count(2)


def test_single_geojson_cell_has_no_overview_map(ds_server, page, errors):
    page.goto(ds_server + "/data/shapes/1")
    expect(page.locator(".dmap-cell[data-live=true]")).to_have_count(1)
    expect(page.locator(".dmap")).to_have_count(0)


def test_points_and_shapes_on_one_map(ds_server, page, errors):
    page.goto(ds_server + "/data/mixed")
    overview = ready(page)
    expect(overview).to_have_attribute("data-points", "1")
    expect(overview).to_have_attribute("data-shapes", "1")
    # One row with both a point and a shape is still one row
    expect(overview.locator(".dmap-progress")).to_be_empty()
    click_feature(page, -121.95, 37.05)
    popup = overview.locator(".dmap-popup")
    expect(popup).to_contain_text("Popup title")
    expect(popup).to_contain_text("Popup description")
    # javascript: links are not allowed
    expect(popup.locator("a.dmap-popup-link")).to_have_count(0)
