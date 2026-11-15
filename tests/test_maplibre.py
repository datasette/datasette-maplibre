from datasette.app import Datasette
from datasette_maplibre import location_columns_from_columns, render_cell
import json
import pytest
import re


def config_from_html(html):
    match = re.search(r"datasette\.maplibre = (\{.*?\});\n", html, re.DOTALL)
    assert match, "datasette.maplibre config not found in page"
    return json.loads(match.group(1))


async def make_datasette(plugin_config=None, table_plugin_config=None):
    config = {}
    if plugin_config:
        config["plugins"] = {"datasette-maplibre": plugin_config}
    if table_plugin_config:
        config["databases"] = {
            "data": {
                "tables": {
                    "places": {"plugins": {"datasette-maplibre": table_plugin_config}}
                }
            }
        }
    ds = Datasette(memory=True, config=config)
    db = ds.add_memory_database("data")
    await db.execute_write(
        "create table if not exists places "
        "(id integer primary key, name text, latitude float, longitude float, xlat float, xlng float)"
    )
    await db.execute_write(
        "create table if not exists plain (id integer primary key, name text)"
    )
    await db.execute_write("delete from places")
    await db.execute_write(
        "insert into places (name, latitude, longitude, xlat, xlng) "
        "values ('</script><b>', 37.0, -122.0, 1.0, 2.0)"
    )
    return ds


@pytest.mark.parametrize(
    "columns,expected",
    (
        (["id", "latitude", "longitude"], ["latitude", "longitude"]),
        (["lat", "lon"], ["lat", "lon"]),
        (["lat", "lng"], ["lat", "lng"]),
        (["lat", "long"], ["lat", "long"]),
        (["Latitude", "Longitude"], ["Latitude", "Longitude"]),
        (["foo_latitude", "foo_longitude"], ["foo_latitude", "foo_longitude"]),
        (["start_lat", "start_lng"], ["start_lat", "start_lng"]),
        # Exact pairs win over wildcard matches
        (["lat", "lon", "other_lat"], ["lat", "lon"]),
        # Ambiguous
        (["a_lat", "b_lat", "a_lng"], []),
        (["id", "name"], []),
        (["latitude"], []),
    ),
)
def test_location_columns_from_columns(columns, expected):
    assert location_columns_from_columns(columns) == expected


@pytest.mark.parametrize(
    "value,should_render",
    (
        ("", False),
        (3, False),
        (None, False),
        (b"blob", False),
        ("{not-json", False),
        ("{}", False),
        ("[1, 2]", False),
        ('{"type": "Bad"}', False),
        ('{"type": {"type": "string"}}', False),
        ('{"type": "Polygon"}', True),
        ('{"type": "FeatureCollection"}', True),
    ),
)
def test_render_cell(value, should_render):
    assert render_cell(value) == (value if should_render else None)


def test_render_cell_rounds_floats():
    value = json.dumps(
        {"type": "Point", "coordinates": [-122.3300578616492, 37.44676099830318]}
    )
    assert json.loads(render_cell(value)) == {
        "type": "Point",
        "coordinates": [-122.33006, 37.44676],
    }


@pytest.mark.asyncio
async def test_default_config_on_table_page():
    ds = await make_datasette()
    response = await ds.client.get("/data/places")
    assert response.status_code == 200
    config = config_from_html(response.text)
    assert config["latitudeColumn"] == "latitude"
    assert config["longitudeColumn"] == "longitude"
    assert config["style"] == "https://tiles.openfreemap.org/styles/liberty"
    assert "styles" not in config
    assert config["view"] == "clusters"
    assert config["height"] == "500px"
    assert config["maxCellMaps"] == 8
    assert config["clusterRadius"] == 25
    assert config["scrollZoom"] is False
    assert config["colorColumn"] is None
    assert config["container"] is None
    assert config["maplibreUrl"].endswith(
        "/-/static-plugins/datasette-maplibre/maplibre-gl.mjs"
    )
    assert config["cssUrl"].endswith(
        "/-/static-plugins/datasette-maplibre/maplibre-gl.css"
    )
    assert "datasette-maplibre.js" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,has_location",
    (
        ("/data/places", True),
        ("/data/places/1", True),
        ("/data?sql=select+*+from+places", True),
        ("/data?sql=select+latitude+as+lat,+longitude+as+lng+from+places", True),
        ("/data/plain", False),
        ("/data?sql=select+name+from+places", False),
    ),
)
async def test_location_columns_detected_per_page(path, has_location):
    ds = await make_datasette()
    # /data?sql= redirects to /data/-/query?sql=
    response = await ds.client.get(path, follow_redirects=True)
    assert response.status_code == 200
    config = config_from_html(response.text)
    assert (config["latitudeColumn"] is not None) == has_location
    # The script is still loaded, because GeoJSON cells can be on any page
    assert "datasette-maplibre.js" in response.text


@pytest.mark.asyncio
async def test_no_script_on_pages_without_columns():
    ds = await make_datasette()
    response = await ds.client.get("/")
    assert "datasette-maplibre.js" not in response.text
    assert "datasette.maplibre" not in response.text


@pytest.mark.asyncio
async def test_configured_columns():
    ds = await make_datasette({"latitude_column": "xlat", "longitude_column": "xlng"})
    config = config_from_html((await ds.client.get("/data/places")).text)
    assert config["latitudeColumn"] == "xlat"
    assert config["longitudeColumn"] == "xlng"


@pytest.mark.asyncio
async def test_table_level_configuration():
    ds = await make_datasette(
        {"view": "points", "style": "https://example.com/style.json"},
        {
            "view": "heatmap",
            "color_column": "name",
            "height": "300px",
            "scroll_zoom": True,
        },
    )
    config = config_from_html((await ds.client.get("/data/places")).text)
    assert config["view"] == "heatmap"
    # Settings the table does not override are inherited
    assert config["style"] == "https://example.com/style.json"
    assert config["colorColumn"] == "name"
    assert config["height"] == "300px"
    assert config["scrollZoom"] is True
    config = config_from_html((await ds.client.get("/data/plain")).text)
    assert config["view"] == "points"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "style",
    (
        "https://example.com/style.json",
        {"version": 8, "sources": {}, "layers": []},
    ),
)
async def test_style_configuration(style):
    ds = await make_datasette({"style": style})
    config = config_from_html((await ds.client.get("/data/places")).text)
    assert config["style"] == style


@pytest.mark.asyncio
async def test_config_cannot_break_out_of_script_tag():
    ds = await make_datasette({"container": "</script><script>alert(1)</script>"})
    html = (await ds.client.get("/data/places")).text
    assert "</script><script>alert(1)" not in html
    assert (
        config_from_html(html)["container"] == "</script><script>alert(1)</script>"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename",
    (
        "datasette-maplibre.js",
        "maplibre-gl.mjs",
        "maplibre-gl-worker.mjs",
        "maplibre-gl.css",
    ),
)
async def test_static_assets(filename):
    ds = await make_datasette()
    response = await ds.client.get("/-/static-plugins/datasette-maplibre/" + filename)
    assert response.status_code == 200
