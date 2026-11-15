# datasette-maplibre specification

A Datasette plugin combining the features of datasette-cluster-map and
datasette-leaflet-geojson, rebuilt on [MapLibre GL JS](https://maplibre.org/)
vector maps with [OpenFreeMap](https://openfreemap.org/) styles. No API keys.

## Python side

- [ ] Vendor MapLibre GL JS 6 (ES module + worker + CSS) as plugin static files
- [ ] Detect latitude/longitude columns (same rules as datasette-cluster-map), overridable with `latitude_column` / `longitude_column`
- [ ] `render_cell` passes GeoJSON values through (rounded to 5 decimal places) so other plugins leave them alone
- [ ] `extra_body_script` publishes one JSON config object as `datasette.maplibre`
- [ ] `extra_js_urls` loads the plugin module on pages that show columns
- [ ] Config: `style`, `styles`, `container`, `height`, `view`, `color_column`, `max_cell_maps`, `cluster_radius`

## Overview map (table, query and row pages)

- [ ] Points from latitude/longitude columns, clustered, loaded from the JSON API
- [ ] Shapes from GeoJSON columns drawn on the same map
- [ ] "Load all" / "pause" pagination with progress
- [ ] No map until a row with a location has loaded
- [ ] Popups: `popup` column JSON (title/image/alt/description/link) or the full row
- [ ] View modes: clusters, individual points, heatmap
- [ ] Style switcher across the OpenFreeMap styles plus any configured ones
- [ ] Colour by column: categorical legend or numeric ramp
- [ ] "Filter to this area": turn the visible map bounds into table filters
- [ ] Table <-> map linking: hover a table row to highlight it on the map, click a feature to highlight its table row
- [ ] 3D tilt, globe, fullscreen, scale controls
- [ ] Map position kept in the URL hash
- [ ] Download what is on the map as GeoJSON

## GeoJSON cells

- [ ] Each GeoJSON cell becomes an instant SVG outline (no WebGL needed)
- [ ] Cells upgrade to interactive maps as they scroll into view
- [ ] Cap on live maps (`max_cell_maps`): the oldest falls back to its SVG outline, so pages with hundreds of shapes do not exhaust WebGL contexts

## Tests

- [ ] pytest unit tests for the Python hooks
- [ ] Playwright tests for the browser behaviour, with map styles stubbed so they run offline
