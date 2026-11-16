# datasette-maplibre specification

A Datasette plugin combining the features of datasette-cluster-map and
datasette-leaflet-geojson, rebuilt on [MapLibre GL JS](https://maplibre.org/)
vector maps with [OpenFreeMap](https://openfreemap.org/) styles. No API keys.

## Python side

- [x] Vendor MapLibre GL JS 6 (ES module + worker + CSS) as plugin static files
- [x] Detect latitude/longitude columns (same rules as datasette-cluster-map), overridable with `latitude_column` / `longitude_column`
- [x] `render_cell` passes GeoJSON values through (rounded to 5 decimal places) so other plugins leave them alone
- [x] `extra_body_script` publishes one JSON config object as `datasette.maplibre`
- [x] `extra_js_urls` loads the plugin module on pages that show columns
- [x] Config: `style`, `styles`, `container`, `height`, `view`, `color_column`, `max_cell_maps`, `cluster_radius`

## Overview map (table, query and row pages)

- [x] Points from latitude/longitude columns, clustered, loaded from the JSON API
- [x] Shapes from GeoJSON columns drawn on the same map
- [x] "Load all" / "pause" pagination with progress
- [x] No map until a row with a location has loaded
- [x] Popups: `popup` column JSON (title/image/alt/description/link) or the full row
- [x] View modes: clusters, individual points, heatmap
- [x] ~~Style switcher~~ (removed)
- [x] Colour by column: categorical legend or numeric ramp
- [x] "Filter to this area": turn the visible map bounds into table filters
- [x] Table <-> map linking: hover a table row to highlight it on the map, click a feature to highlight its table row
- [x] Globe, fullscreen, scale controls
- [x] Map position kept in the URL hash
- [x] Download what is on the map as GeoJSON

## GeoJSON cells

- [x] Each GeoJSON cell becomes an instant SVG outline (no WebGL needed)
- [x] Cells upgrade to interactive maps as they scroll into view
- [x] Cap on live maps (`max_cell_maps`): the oldest falls back to its SVG outline, so pages with hundreds of shapes do not exhaust WebGL contexts

## Tests

- [x] pytest unit tests for the Python hooks
- [x] Playwright tests for the browser behaviour, with map styles stubbed so they run offline

## Added while building

- [x] Table-level plugin configuration is merged over database and instance configuration
- [x] Shapes too small to see at the current zoom get a marker at their centre
- [x] Scrolling the page does not zoom the map unless `scroll_zoom` is set
- [x] Loading more rows never moves a map that has already been moved
- [x] Heatmap intensity scales with the number of points
- [x] View, colour and style are kept in the URL hash and can be set by a link
- [x] Heatmap intensity is normalised by the density of the points
- [x] The map never zooms out far enough to repeat the world
- [x] Popup images have a fixed height, so popups are positioned correctly before the image loads
- [x] Rows at exactly the same point: a numbered disc at any zoom in every view, and one popup that pages through them (a cluster made only of such rows opens the popup instead of zooming)
- [x] Demo instance in `demo/` with a guided tour of every feature
- [x] "All N rows are on the map" line when the map has more rows than the page of the table
- [x] Globe toggle in the toolbar, replacing the 3D button and the globe control on the map
- [x] Style menu removed: `style` is now just a URL or style object, default Liberty
- [x] GeoJSON maps on Datasette 1.0 row pages are not collapsed behind "Show all N characters"
- [x] Requires Datasette 1.0a43 or later: no workarounds for earlier versions, configuration in datasette.yaml
- [x] Shapes that cross the antimeridian (Fiji, Russia) are fitted to their real extent, not the whole world

## Ideas not built

- [ ] SpatiaLite geometry blobs and WKT values, not just GeoJSON text
- [ ] Row links in popups for rows that are not on the current page
- [ ] Draw a polygon on the map to filter by
- [x] Datasette 1.0 alpha support: row pages are a `<dl class="row-fields">` there, and `/db?sql=` redirects to `/db/-/query`
