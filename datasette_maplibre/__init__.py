from datasette import hookimpl
from typing import List
import json

PLUGIN_NAME = "datasette-maplibre"

OPENFREEMAP_STYLES = {
    name.title(): "https://tiles.openfreemap.org/styles/{}".format(name)
    for name in ("liberty", "bright", "positron", "dark", "fiord")
}
DEFAULT_STYLE = "Liberty"
VIEWS = ("clusters", "points", "heatmap")

GEOJSON_TYPES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
    "GeometryCollection",
    "Feature",
    "FeatureCollection",
}


@hookimpl(tryfirst=True)
def render_cell(value):
    # If value is JSON that looks like GeoJSON, return it so no other
    # plugin interferes with it - the JavaScript turns it into a map
    if not isinstance(value, str):
        return None
    try:
        data = json.loads(value)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("type"), str):
        return None
    if data["type"] in GEOJSON_TYPES:
        # Reduce floating point accuracy to something sensible
        return json.dumps(round_floats(data))
    return None


def round_floats(o):
    if isinstance(o, float):
        return round(o, 5)
    if isinstance(o, dict):
        return {k: round_floats(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [round_floats(x) for x in o]
    return o


@hookimpl
def extra_js_urls(columns, datasette):
    if not columns:
        return []
    return [
        {
            "url": datasette.urls.static_plugins(PLUGIN_NAME, "datasette-maplibre.js"),
            "module": True,
        }
    ]


@hookimpl
def extra_body_script(database, table, columns, datasette):
    if not columns:
        return ""
    config = plugin_config(datasette, database, table)
    latitude_column, longitude_column = find_columns(columns, config) or (None, None)
    styles, style = resolve_styles(config)
    view = config.get("view")
    js_config = {
        "maplibreUrl": datasette.urls.static_plugins(PLUGIN_NAME, "maplibre-gl.mjs"),
        "cssUrl": datasette.urls.static_plugins(PLUGIN_NAME, "maplibre-gl.css"),
        "latitudeColumn": latitude_column,
        "longitudeColumn": longitude_column,
        "styles": styles,
        "style": style,
        "view": view if view in VIEWS else VIEWS[0],
        "height": config.get("height") or "500px",
        "container": config.get("container"),
        "colorColumn": config.get("color_column"),
        "maxCellMaps": config.get("max_cell_maps") or 8,
        "clusterRadius": config.get("cluster_radius") or 50,
    }
    return (
        "window.datasette = window.datasette || {};\n"
        "datasette.maplibre = " + json_for_script(js_config) + ";\n"
    )


def json_for_script(value):
    # Safe to embed in a <script> block: no "</script>" or "<!--"
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def plugin_config(datasette, database=None, table=None):
    # Datasette returns only the most specific configuration. Merge the
    # levels instead, so a table can override one setting and keep the rest.
    config = {}
    levels = [{}]
    if database:
        levels.append({"database": database})
        if table:
            levels.append({"database": database, "table": table})
    for level in levels:
        config.update(datasette.plugin_config(PLUGIN_NAME, **level) or {})
    return config


def resolve_styles(config):
    "Returns ({label: style URL or style object}, label of the default style)"
    styles = dict(OPENFREEMAP_STYLES)
    styles.update(config.get("styles") or {})
    style = config.get("style") or DEFAULT_STYLE
    if isinstance(style, str):
        for label in styles:
            if label.lower() == style.lower():
                return styles, label
    styles["Custom"] = style
    return styles, "Custom"


def find_columns(columns, config):
    if not columns:
        return []
    latitude_column = config.get("latitude_column")
    longitude_column = config.get("longitude_column")
    if not latitude_column or not longitude_column:
        return location_columns_from_columns(columns)
    lowercase_columns = [column.lower() for column in columns]
    if (
        latitude_column.lower() in lowercase_columns
        and longitude_column.lower() in lowercase_columns
    ):
        return [latitude_column, longitude_column]
    return []


def _match(pattern, column):
    # latitude matches "latitude" or "foo_latitude"
    return column.lower() == pattern or column.lower().endswith("_" + pattern)


LATITUDE_PATTERNS = ["latitude", "lat"]
LONGITUDE_PATTERNS = ["longitude", "lon", "lng", "long"]
LOCATION_PRIORITIES = (
    ("latitude", "longitude"),
    ("lat", "lon"),
    ("lat", "lng"),
    ("lat", "long"),
)


def location_columns_from_columns(columns: List[str]) -> List[str]:
    latitude_col = None
    longitude_col = None
    cols_to_case = {col.lower(): col for col in columns}

    # First look for the priority pairings - return if found
    for lat, lon in LOCATION_PRIORITIES:
        if lat in cols_to_case and lon in cols_to_case:
            return [cols_to_case[lat], cols_to_case[lon]]

    # Now try for the wildcard patterns instead
    for col in columns:
        if any(_match(lat, col) for lat in LATITUDE_PATTERNS):
            if latitude_col is not None:
                # Already have latitude, so this is ambiguous
                return []
            latitude_col = col
        elif any(_match(lon, col) for lon in LONGITUDE_PATTERNS):
            if longitude_col is not None:
                return []
            longitude_col = col

    if latitude_col is None or longitude_col is None:
        return []
    return [latitude_col, longitude_col]
