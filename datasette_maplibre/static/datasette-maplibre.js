// datasette-maplibre: MapLibre GL + OpenFreeMap maps for Datasette
//
// 1. An overview map above the table, for rows with latitude/longitude
//    columns and for GeoJSON columns, loaded from the Datasette JSON API
// 2. A map in every table cell that contains GeoJSON

const config = (window.datasette && window.datasette.maplibre) || null;

const GEOJSON_TYPES = new Set([
  "Point",
  "MultiPoint",
  "LineString",
  "MultiLineString",
  "Polygon",
  "MultiPolygon",
  "GeometryCollection",
  "Feature",
  "FeatureCollection",
]);
const POINT_COLOR = "#2563eb";
const HIGHLIGHT_COLOR = "#f59e0b";
const OTHER_COLOR = "#9ca3af";
const CATEGORY_COLORS = [
  "#2563eb",
  "#e11d48",
  "#059669",
  "#d97706",
  "#7c3aed",
  "#0891b2",
  "#be185d",
  "#65a30d",
  "#92400e",
  "#475569",
];
const RAMP_COLORS = ["#440154", "#21918c", "#fde725"];
const VIEWS = { clusters: "Clusters", points: "Points", heatmap: "Heatmap" };

const CSS = `
.dmap { margin-bottom: 1.5em; }
.dmap-toolbar { display: flex; flex-wrap: wrap; gap: 0.4em 1em; align-items: center;
  font-size: 0.8rem; margin-bottom: 0.4em; }
.dmap-toolbar label { display: inline-flex; align-items: center; gap: 0.3em; }
.dmap-toolbar select { font-size: 0.8rem; max-width: 12em; }
.dmap-toolbar .dmap-spacer { flex: 1; }
.dmap-toolbar button, .dmap-progress button { color: #fff; background-color: #007bff; border: 1px solid #0062cc;
  cursor: pointer; padding: 0.3em 0.7em; font-size: 0.75rem; line-height: 1.2;
  border-radius: 0.25rem; }
.dmap-toolbar button.dmap-secondary { color: #333; background: #fff; border-color: #bbb; }
.dmap-toolbar button[aria-pressed="true"] { background: #333; color: #fff; border-color: #333; }
.dmap-map { width: 100%; background: #eee; }
.dmap-legend { display: flex; flex-wrap: wrap; gap: 0.2em 1em; font-size: 0.75rem;
  margin-top: 0.4em; align-items: center; }
.dmap-legend:empty { display: none; }
.dmap-swatch { display: inline-block; width: 0.9em; height: 0.9em; border-radius: 50%;
  margin-right: 0.3em; vertical-align: -0.1em; }
.dmap-ramp { display: inline-block; width: 10em; height: 0.8em; margin: 0 0.5em;
  vertical-align: -0.05em; border-radius: 2px; }
.dmap-progress { font-size: 0.8rem; margin-top: 0.4em; min-height: 1.2em; }
.dmap-popup { max-height: 240px; overflow: auto; font-size: 0.8rem; color: #222; }
.dmap-popup dl { margin: 0; }
.dmap-popup dt { font-weight: bold; }
.dmap-popup dd { margin: 0 0 0.3em 0.7em; overflow-wrap: anywhere; }
.dmap-popup dd span { color: #999; font-size: 0.85em; }
.dmap-popup img { max-width: 100%; display: block; }
.dmap-popup p { margin: 0 0 0.4em 0; }
.dmap-popup a.dmap-popup-link { text-decoration: none; color: inherit; display: block; }
.dmap-popup .dmap-popup-row { display: block; margin-top: 0.5em; }
tr.dmap-row-active > td { background-color: #fff3c4 !important; }
.dmap-cell { position: relative; width: 100%; min-width: 360px; height: 280px;
  background: #f1f3f5; overflow: hidden; }
.dmap-cell svg, .dmap-cell .dmap-cell-map { position: absolute; inset: 0;
  width: 100%; height: 100%; }
.dmap-cell svg { padding: 12px; box-sizing: border-box; }
.dmap-cell-error { position: absolute; left: 0; right: 0; bottom: 0; padding: 0.3em;
  font-size: 0.7rem; color: #666; background: rgba(255,255,255,0.8); }
`;

/* ---------- Small helpers ---------- */

function h(tag, attrs, children) {
  const el = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([key, value]) => {
    if (key === "class") {
      el.className = value;
    } else if (key.startsWith("on")) {
      el.addEventListener(key.slice(2), value);
    } else if (value !== null && value !== undefined) {
      el.setAttribute(key, value);
    }
  });
  [].concat(children || []).forEach((child) => {
    el.appendChild(
      typeof child === "string" ? document.createTextNode(child) : child
    );
  });
  return el;
}

let cssInjected = false;
function injectCss() {
  if (!cssInjected) {
    cssInjected = true;
    document.head.appendChild(h("style", {}, CSS));
  }
}

let libraryPromise = null;
function loadLibrary() {
  if (!libraryPromise) {
    injectCss();
    const css = new Promise((resolve) => {
      const link = h("link", { rel: "stylesheet", href: config.cssUrl });
      link.onload = resolve;
      link.onerror = resolve;
      document.head.appendChild(link);
    });
    libraryPromise = Promise.all([import(config.maplibreUrl), css]).then(
      ([library]) => library
    );
  }
  return libraryPromise;
}

function isValidLatitude(value) {
  const number = parseFloat(value);
  return !isNaN(number) && number >= -90 && number <= 90;
}

function isValidLongitude(value) {
  const number = parseFloat(value);
  return !isNaN(number) && number >= -180 && number <= 180;
}

function safeUrl(url) {
  // Only http(s) and relative URLs - never javascript: or data:
  try {
    const parsed = new URL(url, location.href);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
  } catch (e) {
    return null;
  }
}

/* ---------- GeoJSON helpers ---------- */

function parseGeoJSON(value) {
  // Returns a GeoJSON object, or null if value does not look like GeoJSON
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed[0] !== "{" || trimmed.indexOf('"type"') === -1) {
      return null;
    }
    try {
      value = JSON.parse(trimmed);
    } catch (e) {
      return null;
    }
  }
  if (!value || typeof value !== "object" || !GEOJSON_TYPES.has(value.type)) {
    return null;
  }
  return value;
}

function toGeometries(geojson) {
  // Flattens any GeoJSON object to a list of simple geometries
  if (!geojson) {
    return [];
  }
  if (geojson.type === "FeatureCollection") {
    return (geojson.features || []).flatMap(toGeometries);
  }
  if (geojson.type === "Feature") {
    return toGeometries(geojson.geometry);
  }
  if (geojson.type === "GeometryCollection") {
    return (geojson.geometries || []).flatMap(toGeometries);
  }
  return Array.isArray(geojson.coordinates) ? [geojson] : [];
}

function eachPosition(coordinates, callback) {
  if (!Array.isArray(coordinates)) {
    return;
  }
  if (typeof coordinates[0] === "number") {
    if (isFinite(coordinates[0]) && isFinite(coordinates[1])) {
      callback(coordinates);
    }
  } else {
    coordinates.forEach((item) => eachPosition(item, callback));
  }
}

function extendBounds(bounds, geometry) {
  // bounds is [west, south, east, north], or null
  eachPosition(geometry.coordinates, ([lng, lat]) => {
    if (!bounds) {
      bounds = [lng, lat, lng, lat];
    } else {
      bounds[0] = Math.min(bounds[0], lng);
      bounds[1] = Math.min(bounds[1], lat);
      bounds[2] = Math.max(bounds[2], lng);
      bounds[3] = Math.max(bounds[3], lat);
    }
  });
  return bounds;
}

function mapBounds(bounds) {
  return [
    [bounds[0], Math.max(bounds[1], -85)],
    [bounds[2], Math.min(bounds[3], 85)],
  ];
}

function featureCollection(features) {
  return { type: "FeatureCollection", features };
}

function centerFeature(geometry, properties) {
  // A point in the middle of the geometry. z is the zoom level at which
  // the geometry is about 24 pixels across, on 512 pixel tiles.
  const [west, south, east, north] = extendBounds(null, geometry);
  const span = Math.max(east - west, north - south, 1e-6);
  return {
    type: "Feature",
    properties: { ...properties, z: Math.log2((24 * 360) / (512 * span)) },
    geometry: {
      type: "Point",
      coordinates: [(west + east) / 2, (south + north) / 2],
    },
  };
}

/* ---------- SVG outline of a geometry: instant, and needs no WebGL ---------- */

function geojsonToSvg(geometries) {
  const SVG = "http://www.w3.org/2000/svg";
  const project = ([lng, lat]) => {
    const clamped = Math.max(-85, Math.min(85, lat));
    const y = Math.log(Math.tan(Math.PI / 4 + (clamped * Math.PI) / 360));
    return [(lng * Math.PI) / 180, -y];
  };
  let box = null;
  geometries.forEach((geometry) =>
    eachPosition(geometry.coordinates, (position) => {
      const [x, y] = project(position);
      box = box
        ? [
            Math.min(box[0], x),
            Math.min(box[1], y),
            Math.max(box[2], x),
            Math.max(box[3], y),
          ]
        : [x, y, x, y];
    })
  );
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Outline of this geometry");
  if (!box) {
    return svg;
  }
  const size = Math.max(box[2] - box[0], box[3] - box[1]) || 1;
  const scale = 1000 / size;
  const width = Math.max((box[2] - box[0]) * scale, 1);
  const height = Math.max((box[3] - box[1]) * scale, 1);
  svg.setAttribute("viewBox", `-20 -20 ${width + 40} ${height + 40}`);
  const point = (position) => {
    const [x, y] = project(position);
    return [
      Math.round((x - box[0]) * scale * 10) / 10,
      Math.round((y - box[1]) * scale * 10) / 10,
    ];
  };
  const line = (positions) =>
    positions.map((p, i) => (i ? "L" : "M") + point(p).join(" ")).join("");
  const add = (tag, attrs) => {
    const el = document.createElementNS(SVG, tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    el.setAttribute("stroke", POINT_COLOR);
    el.setAttribute("stroke-width", "2");
    el.setAttribute("vector-effect", "non-scaling-stroke");
    svg.appendChild(el);
  };
  const polygon = (rings) =>
    add("path", {
      d: rings.map((ring) => line(ring) + "Z").join(""),
      fill: POINT_COLOR,
      "fill-opacity": "0.2",
      "fill-rule": "evenodd",
    });
  const lineString = (positions) =>
    add("path", { d: line(positions), fill: "none" });
  const circle = (position) => {
    const [cx, cy] = point(position);
    add("circle", { cx, cy, r: 12, fill: POINT_COLOR, "fill-opacity": "0.6" });
  };
  geometries.forEach(({ type, coordinates }) => {
    try {
      if (type === "Polygon") polygon(coordinates);
      else if (type === "MultiPolygon") coordinates.forEach(polygon);
      else if (type === "LineString") lineString(coordinates);
      else if (type === "MultiLineString") coordinates.forEach(lineString);
      else if (type === "Point") circle(coordinates);
      else if (type === "MultiPoint") coordinates.forEach(circle);
    } catch (e) {
      console.warn("datasette-maplibre: could not draw geometry", e);
    }
  });
  return svg;
}

/* ---------- Layers shared by the overview map and the cell maps ---------- */

const POLYGONS = ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]];
const NOT_POINTS = [
  "!",
  ["in", ["geometry-type"], ["literal", ["Point", "MultiPoint"]]],
];
const POINTS = ["in", ["geometry-type"], ["literal", ["Point", "MultiPoint"]]];

function addShapeLayers(map, source, prefix, color) {
  map.addLayer({
    id: prefix + "-fill",
    type: "fill",
    source,
    filter: POLYGONS,
    paint: { "fill-color": color, "fill-opacity": 0.25 },
  });
  map.addLayer({
    id: prefix + "-line",
    type: "line",
    source,
    filter: NOT_POINTS,
    layout: { "line-join": "round", "line-cap": "round" },
    paint: { "line-color": color, "line-width": 2 },
  });
  map.addLayer({
    id: prefix + "-circle",
    type: "circle",
    source,
    filter: POINTS,
    paint: {
      "circle-color": color,
      "circle-radius": 6,
      "circle-stroke-color": "#fff",
      "circle-stroke-width": 1.5,
    },
  });
  return ["-fill", "-line", "-circle"].map((suffix) => prefix + suffix);
}

function resolveStyle(label) {
  return config.styles[label] || config.styles[config.style];
}

/* ---------- GeoJSON cells ---------- */

function findGeoJSONCells() {
  const cells = [];
  document.querySelectorAll("table.rows-and-columns td").forEach((td) => {
    const text = td.textContent;
    if (!text || text.trim()[0] !== "{") {
      return;
    }
    const geometries = toGeometries(parseGeoJSON(text));
    const bounds = geometries.reduce(extendBounds, null);
    if (bounds) {
      cells.push({ td, geometries, bounds, map: null, visible: false });
    }
  });
  return cells;
}

function setUpCells(cells) {
  // Browsers only allow a limited number of WebGL contexts per page, so
  // only maxCellMaps cells are interactive maps at any one time. The rest
  // show an SVG outline, which is also what is displayed while a map loads.
  const live = [];

  const deactivate = (cell) => {
    if (cell.map) {
      cell.map.remove();
      cell.map = null;
    }
    if (cell.mapEl) {
      cell.mapEl.remove();
      cell.mapEl = null;
    }
    cell.svg.style.visibility = "";
    cell.el.dataset.live = "false";
    const index = live.indexOf(cell);
    if (index > -1) {
      live.splice(index, 1);
    }
  };

  const activate = (cell) => {
    if (cell.map || cell.failed) {
      return;
    }
    if (live.length >= config.maxCellMaps) {
      // Evict the oldest map that is off screen, else the oldest map
      deactivate(live.find((other) => !other.visible) || live[0]);
    }
    live.push(cell);
    loadLibrary().then((library) => {
      if (live.indexOf(cell) === -1 || cell.map) {
        return;
      }
      cell.mapEl = h("div", { class: "dmap-cell-map" });
      cell.el.appendChild(cell.mapEl);
      try {
        const map = new library.Map({
          container: cell.mapEl,
          style: resolveStyle(config.style),
          bounds: mapBounds(cell.bounds),
          fitBoundsOptions: { padding: 30, maxZoom: 14 },
          // Scrolling the page should not zoom every map the mouse passes over
          cooperativeGestures: true,
          attributionControl: { compact: true },
        });
        cell.map = map;
        map.on("load", () => {
          map.addSource("geojson", {
            type: "geojson",
            data: featureCollection(
              cell.geometries.map((geometry) => ({
                type: "Feature",
                properties: {},
                geometry,
              }))
            ),
          });
          addShapeLayers(map, "geojson", "geojson", POINT_COLOR);
          // The attribution starts expanded, which hides a lot of a small map
          const attribution = cell.mapEl.querySelector(".maplibregl-ctrl-attrib");
          if (attribution) {
            attribution.classList.remove("maplibregl-compact-show");
            attribution.removeAttribute("open");
          }
          cell.svg.style.visibility = "hidden";
          cell.el.dataset.live = "true";
        });
      } catch (error) {
        console.warn("datasette-maplibre: map creation failed", error);
        cell.failed = true;
        deactivate(cell);
        cell.el.appendChild(
          h("div", { class: "dmap-cell-error" }, "Interactive map unavailable")
        );
      }
    });
  };

  const byElement = new Map();
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        const cell = byElement.get(entry.target);
        cell.visible = entry.isIntersecting;
        if (cell.visible) {
          activate(cell);
        }
      });
    },
    { rootMargin: "100px" }
  );

  if (cells.length) {
    injectCss();
  }
  cells.forEach((cell) => {
    cell.svg = geojsonToSvg(cell.geometries);
    cell.el = h("div", { class: "dmap-cell", "data-live": "false" });
    cell.el.appendChild(cell.svg);
    cell.td.replaceChildren(cell.el);
    byElement.set(cell.el, cell);
    observer.observe(cell.el);
  });
}

/* ---------- Popups ---------- */

function popupContent(row) {
  const root = h("div", { class: "dmap-popup" });
  let popup = row.popup;
  if (typeof popup === "string") {
    try {
      popup = JSON.parse(popup);
    } catch (e) {
      popup = null;
    }
  }
  if (
    popup &&
    typeof popup === "object" &&
    (popup.image || popup.title || popup.description || popup.link)
  ) {
    const parts = [];
    if (popup.title) {
      parts.push(h("p", {}, h("strong", {}, String(popup.title))));
    }
    const image = popup.image && safeUrl(popup.image);
    if (image) {
      parts.push(h("img", { src: image, alt: popup.alt || "" }));
    }
    if (popup.description) {
      parts.push(h("p", {}, String(popup.description)));
    }
    const link = popup.link && safeUrl(popup.link);
    root.appendChild(
      link ? h("a", { class: "dmap-popup-link", href: link }, parts) : h("div", {}, parts)
    );
    return root;
  }
  const dl = h("dl");
  Object.entries(row).forEach(([key, value]) => {
    if (parseGeoJSON(value)) {
      // No point showing kilobytes of coordinates
      value = "GeoJSON " + parseGeoJSON(value).type;
    }
    const dd = h("dd");
    if (value && typeof value === "object") {
      if (value.label !== undefined && value.value !== undefined) {
        dd.appendChild(document.createTextNode(String(value.label)));
        dd.appendChild(h("span", {}, " " + value.value));
      } else {
        dd.appendChild(document.createTextNode(JSON.stringify(value)));
      }
    } else {
      dd.appendChild(document.createTextNode(value === null ? "" : String(value)));
    }
    dl.appendChild(h("dt", {}, key));
    dl.appendChild(dd);
  });
  root.appendChild(dl);
  return root;
}

/* ---------- Colour by column ---------- */

function displayValue(value) {
  if (value && typeof value === "object") {
    return value.label !== undefined ? value.label : JSON.stringify(value);
  }
  return value;
}

function colorScale(rows, column) {
  // Returns {expression, legend, value(row)} for colouring features
  const values = rows.map((row) => displayValue(row[column]));
  const present = values.filter((v) => v !== null && v !== undefined && v !== "");
  const distinct = new Set(present);
  const numeric =
    present.length > 0 &&
    distinct.size > CATEGORY_COLORS.length &&
    present.every((v) => typeof v === "number" && isFinite(v));
  if (numeric) {
    let min = Infinity;
    let max = -Infinity;
    present.forEach((v) => {
      min = Math.min(min, v);
      max = Math.max(max, v);
    });
    const middle = (min + max) / 2;
    return {
      value: (row) => {
        const v = displayValue(row[column]);
        return typeof v === "number" && isFinite(v) ? v : null;
      },
      expression: [
        "case",
        ["==", ["typeof", ["get", "c"]], "number"],
        min === max
          ? RAMP_COLORS[1]
          : [
              "interpolate",
              ["linear"],
              ["get", "c"],
              min,
              RAMP_COLORS[0],
              middle,
              RAMP_COLORS[1],
              max,
              RAMP_COLORS[2],
            ],
        OTHER_COLOR,
      ],
      legend: { type: "ramp", min, max },
    };
  }
  const counts = new Map();
  present.forEach((v) => {
    const key = String(v);
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  const top = Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, CATEGORY_COLORS.length);
  const match = ["match", ["to-string", ["get", "c"]]];
  top.forEach(([key], i) => match.push(key, CATEGORY_COLORS[i]));
  match.push(OTHER_COLOR);
  return {
    value: (row) => {
      const v = displayValue(row[column]);
      return v === null || v === undefined ? "" : String(v);
    },
    expression: top.length ? match : OTHER_COLOR,
    legend: {
      type: "categories",
      items: top.map(([key, count], i) => ({
        label: key,
        count,
        color: CATEGORY_COLORS[i],
      })),
      other: counts.size > top.length || present.length < values.length,
    },
  };
}

/* ---------- The overview map ---------- */

function overviewMap({ latitudeColumn, longitudeColumn, pageType }) {
  const POINTS_SOURCE = "dmap-points";
  const SHAPES_SOURCE = "dmap-shapes";
  const HIGHLIGHT_SOURCE = "dmap-highlight";
  const CENTERS_SOURCE = "dmap-centers";

  const rows = [];
  const points = [];
  const shapes = [];
  // A point for every shape, shown while the shape is too small to see
  const centers = [];
  let shapeRows = 0;
  let bounds = null;
  let library = null;
  let map = null;
  let styleReady = false;
  let layerIds = [];
  let lastFit = null;
  let keepGoing = false;
  let complete = false;
  let view = config.view;
  let styleLabel = config.style;
  let colorColumn = null;
  let scale = null;
  let columnsListed = false;
  const hadHash = /(^#|&)map=/.test(location.hash);
  const domRows = Array.from(
    document.querySelectorAll("table.rows-and-columns tbody tr")
  );

  /* DOM */
  const mapEl = h("div", { class: "dmap-map" });
  mapEl.style.height = config.height;
  const legendEl = h("div", { class: "dmap-legend" });
  const progressEl = h("div", { class: "dmap-progress" });
  const select = (label, name, options, onchange) => {
    const el = h(
      "select",
      { name, onchange: (ev) => onchange(ev.target.value) },
      options.map(([value, text]) => h("option", { value }, text))
    );
    return [h("label", {}, [label + " ", el]), el];
  };
  const [viewLabel, viewSelect] = select(
    "View",
    "dmap-view",
    Object.entries(VIEWS),
    (value) => {
      view = value;
      installLayers();
    }
  );
  viewSelect.value = view;
  const [styleLabelEl, styleSelect] = select(
    "Style",
    "dmap-style",
    Object.keys(config.styles).map((label) => [label, label]),
    (value) => {
      styleLabel = value;
      styleReady = false;
      map.setStyle(resolveStyle(value), { diff: false });
    }
  );
  styleSelect.value = styleLabel;
  const [colorLabel, colorSelect] = select(
    "Colour by",
    "dmap-color",
    [["", "(none)"]],
    (value) => setColorColumn(value || null)
  );
  const tiltButton = h(
    "button",
    {
      type: "button",
      class: "dmap-secondary dmap-tilt",
      "aria-pressed": "false",
      onclick: () => {
        const tilted = map.getPitch() > 0;
        map.easeTo({ pitch: tilted ? 0 : 55 });
        tiltButton.setAttribute("aria-pressed", String(!tilted));
      },
    },
    "3D"
  );
  const toolbar = h("div", { class: "dmap-toolbar" }, [
    viewLabel,
    colorLabel,
    styleLabelEl,
    tiltButton,
    h("span", { class: "dmap-spacer" }),
  ]);
  const canFilter = pageType === "table" && latitudeColumn && longitudeColumn;
  const areaParams = canFilter
    ? [
        latitudeColumn + "__gte",
        latitudeColumn + "__lte",
        longitudeColumn + "__gte",
        longitudeColumn + "__lte",
      ]
    : [];
  if (canFilter) {
    toolbar.appendChild(
      h(
        "button",
        {
          type: "button",
          class: "dmap-filter-area",
          title: "Only show rows that are inside the area visible on the map",
          onclick: filterToArea,
        },
        "Filter to this area"
      )
    );
    const current = new URL(location.href);
    if (areaParams.some((param) => current.searchParams.has(param))) {
      toolbar.appendChild(
        h(
          "button",
          {
            type: "button",
            class: "dmap-secondary dmap-clear-area",
            onclick: () => {
              areaParams.forEach((param) => current.searchParams.delete(param));
              current.searchParams.delete("_next");
              current.hash = "";
              location.href = current.href;
            },
          },
          "Clear area filter"
        )
      );
    }
  }
  toolbar.appendChild(
    h(
      "button",
      { type: "button", class: "dmap-secondary dmap-download", onclick: download },
      "Download GeoJSON"
    )
  );
  const wrapper = h("div", { class: "dmap" }, [progressEl]);

  const addToPage = () => {
    if (wrapper.parentNode) {
      return;
    }
    const container = config.container && document.querySelector(config.container);
    if (container) {
      container.appendChild(wrapper);
    } else {
      const table =
        document.querySelector(".table-wrapper") ||
        document.querySelector("table.rows-and-columns");
      table.parentNode.insertBefore(wrapper, table);
    }
  };

  const updateStatus = () => {
    wrapper.dataset.rows = rows.length;
    wrapper.dataset.points = points.length;
    wrapper.dataset.shapes = shapes.length;
    wrapper.dataset.moved = String(Boolean(map) && movedSinceFit());
    wrapper.dataset.complete = String(complete);
    wrapper.dataset.view = view;
    wrapper.dataset.styleReady = String(styleReady);
  };

  /* Map */
  function showMap() {
    if (map) {
      return;
    }
    addToPage();
    wrapper.insertBefore(toolbar, progressEl);
    wrapper.insertBefore(mapEl, progressEl);
    wrapper.insertBefore(legendEl, progressEl);
    try {
      map = new library.Map({
        container: mapEl,
        style: resolveStyle(styleLabel),
        center: [0, 20],
        zoom: 1,
        // Keeps the position of the map in the URL, as #map=zoom/lat/lng
        hash: "map",
        // Scrolling the page should not zoom the map: ctrl + scroll does
        cooperativeGestures: !config.scrollZoom,
      });
    } catch (error) {
      console.warn("datasette-maplibre: map creation failed", error);
      mapEl.textContent = "Could not display the map: " + error;
      return;
    }
    map.addControl(new library.NavigationControl({ visualizePitch: true }));
    map.addControl(new library.GlobeControl());
    map.addControl(new library.FullscreenControl());
    map.addControl(new library.ScaleControl(), "bottom-left");
    map.on("style.load", () => {
      styleReady = true;
      installLayers();
    });
    map.on("click", onClick);
    map.on("mousemove", (ev) => {
      map.getCanvas().style.cursor = featuresAt(ev.point).length ? "pointer" : "";
    });
    domRows.forEach((tr, index) => {
      tr.addEventListener("mouseenter", () => highlightRow(index));
      tr.addEventListener("mouseleave", () => highlightRow(null));
    });
    // For debugging, and for other plugins
    config.map = map;
  }

  function fontForLabels() {
    // The cluster count labels need a font that the style can provide
    const style = map.getStyle();
    if (!style || !style.glyphs) {
      return null;
    }
    for (const layer of style.layers || []) {
      const font = layer.layout && layer.layout["text-font"];
      if (Array.isArray(font) && font.every((name) => typeof name === "string")) {
        return font;
      }
    }
    return null;
  }

  function installLayers() {
    updateStatus();
    if (!map || !styleReady) {
      return;
    }
    layerIds.forEach((id) => map.getLayer(id) && map.removeLayer(id));
    [POINTS_SOURCE, SHAPES_SOURCE, HIGHLIGHT_SOURCE, CENTERS_SOURCE].forEach(
      (id) => map.getSource(id) && map.removeSource(id)
    );
    const color = scale ? scale.expression : POINT_COLOR;
    map.addSource(SHAPES_SOURCE, {
      type: "geojson",
      data: featureCollection(shapes),
    });
    map.addSource(POINTS_SOURCE, {
      type: "geojson",
      data: featureCollection(points),
      cluster: view === "clusters",
      clusterRadius: config.clusterRadius,
      clusterMaxZoom: 14,
    });
    map.addSource(HIGHLIGHT_SOURCE, {
      type: "geojson",
      data: featureCollection([]),
    });
    map.addSource(CENTERS_SOURCE, {
      type: "geojson",
      data: featureCollection(centers),
    });
    layerIds = addShapeLayers(map, SHAPES_SOURCE, "dmap-shapes", color);
    map.addLayer({
      id: "dmap-center",
      type: "circle",
      source: CENTERS_SOURCE,
      // Only while the map is zoomed out too far for the shape to be visible
      filter: [">", ["get", "z"], ["zoom"]],
      paint: {
        "circle-color": color,
        "circle-radius": 6,
        "circle-opacity": 0.6,
        "circle-stroke-color": color,
        "circle-stroke-width": 2,
      },
    });
    layerIds.push("dmap-center");
    const pointPaint = {
      "circle-color": color,
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 4, 12, 7],
      "circle-stroke-color": "#fff",
      "circle-stroke-width": 1.5,
    };
    if (view === "heatmap") {
      map.addLayer({
        id: "dmap-heat",
        type: "heatmap",
        source: POINTS_SOURCE,
        maxzoom: 15,
        paint: {
          "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 0, 6, 9, 24, 15, 40],
          "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 0, 1, 15, 3],
          "heatmap-opacity": ["interpolate", ["linear"], ["zoom"], 12, 0.85, 15, 0],
        },
      });
      // Individual points fade in as the heatmap fades out
      const fade = ["interpolate", ["linear"], ["zoom"], 11, 0, 13, 1];
      map.addLayer({
        id: "dmap-point",
        type: "circle",
        source: POINTS_SOURCE,
        minzoom: 11,
        paint: { ...pointPaint, "circle-opacity": fade, "circle-stroke-opacity": fade },
      });
      layerIds.push("dmap-heat", "dmap-point");
    } else {
      map.addLayer({
        id: "dmap-cluster",
        type: "circle",
        source: POINTS_SOURCE,
        filter: ["has", "point_count"],
        paint: {
          "circle-color": [
            "step",
            ["get", "point_count"],
            "#60a5fa",
            10,
            "#3b82f6",
            100,
            "#1d4ed8",
            1000,
            "#1e3a8a",
          ],
          "circle-opacity": 0.85,
          "circle-radius": ["step", ["get", "point_count"], 15, 10, 19, 100, 24, 1000, 30],
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });
      layerIds.push("dmap-cluster");
      const font = fontForLabels();
      if (font) {
        map.addLayer({
          id: "dmap-cluster-count",
          type: "symbol",
          source: POINTS_SOURCE,
          filter: ["has", "point_count"],
          layout: {
            "text-field": ["get", "point_count_abbreviated"],
            "text-font": font,
            "text-size": 12,
            "text-allow-overlap": true,
          },
          paint: { "text-color": "#fff" },
        });
        layerIds.push("dmap-cluster-count");
      }
      map.addLayer({
        id: "dmap-point",
        type: "circle",
        source: POINTS_SOURCE,
        filter: ["!", ["has", "point_count"]],
        paint: pointPaint,
      });
      layerIds.push("dmap-point");
    }
    // The table row being hovered over, drawn on top of everything else
    map.addLayer({
      id: "dmap-highlight-line",
      type: "line",
      source: HIGHLIGHT_SOURCE,
      filter: NOT_POINTS,
      paint: { "line-color": HIGHLIGHT_COLOR, "line-width": 4 },
    });
    map.addLayer({
      id: "dmap-highlight-circle",
      type: "circle",
      source: HIGHLIGHT_SOURCE,
      filter: POINTS,
      paint: {
        "circle-color": HIGHLIGHT_COLOR,
        "circle-radius": 11,
        "circle-stroke-color": "#fff",
        "circle-stroke-width": 3,
      },
    });
    layerIds.push("dmap-highlight-line", "dmap-highlight-circle");
    updateStatus();
  }

  function camera() {
    const center = map.getCenter();
    return [center.lng, center.lat, map.getZoom()];
  }

  function movedSinceFit() {
    // Once the map has been moved, by the user or by other code, stop
    // fitting it to the data as more rows load
    return (
      lastFit !== null &&
      camera().some((value, i) => Math.abs(value - lastFit[i]) > 1e-6)
    );
  }

  function updateData() {
    if (map && styleReady && map.getSource(POINTS_SOURCE)) {
      map.getSource(POINTS_SOURCE).setData(featureCollection(points));
      map.getSource(SHAPES_SOURCE).setData(featureCollection(shapes));
      map.getSource(CENTERS_SOURCE).setData(featureCollection(centers));
    }
    if (map && bounds && !hadHash && !movedSinceFit()) {
      map.fitBounds(mapBounds(bounds), { padding: 50, maxZoom: 14, animate: false });
      lastFit = camera();
    }
    updateStatus();
  }

  /* Rows */
  function addRow(row) {
    const index = rows.push(row) - 1;
    const properties = { _row: index };
    if (scale) {
      properties.c = scale.value(row);
    }
    let located = false;
    const add = (geometry) => {
      const feature = { type: "Feature", properties, geometry };
      (geometry.type === "Point" ? points : shapes).push(feature);
      bounds = extendBounds(bounds, geometry);
      if (geometry.type !== "Point") {
        centers.push(centerFeature(geometry, properties));
      }
      located = true;
    };
    if (
      latitudeColumn &&
      isValidLatitude(row[latitudeColumn]) &&
      isValidLongitude(row[longitudeColumn])
    ) {
      add({
        type: "Point",
        coordinates: [
          parseFloat(row[longitudeColumn]),
          parseFloat(row[latitudeColumn]),
        ],
      });
    }
    let hasShape = false;
    Object.values(row).forEach((value) => {
      toGeometries(parseGeoJSON(value)).forEach((geometry) => {
        if (extendBounds(null, geometry)) {
          add(geometry);
          hasShape = true;
        }
      });
    });
    if (hasShape) {
      shapeRows += 1;
    }
    return located;
  }

  function featuresForRow(index) {
    return points.concat(shapes).filter((f) => f.properties._row === index);
  }

  let activeRow = null;
  function highlightRow(index) {
    if (!map || !styleReady || !map.getSource(HIGHLIGHT_SOURCE)) {
      return;
    }
    map
      .getSource(HIGHLIGHT_SOURCE)
      .setData(featureCollection(index === null ? [] : featuresForRow(index)));
    wrapper.dataset.highlight = index === null ? "" : index;
  }

  function markTableRow(index) {
    if (activeRow) {
      activeRow.classList.remove("dmap-row-active");
    }
    activeRow = domRows[index] || null;
    if (activeRow) {
      activeRow.classList.add("dmap-row-active");
    }
  }

  /* Interaction */
  function featuresAt(point) {
    const layers = layerIds.filter(
      (id) => !id.startsWith("dmap-highlight") && id !== "dmap-heat" && map.getLayer(id)
    );
    return layers.length ? map.queryRenderedFeatures(point, { layers }) : [];
  }

  function onClick(ev) {
    const features = featuresAt(ev.point);
    if (!features.length) {
      return;
    }
    // Prefer points and clusters over the shapes underneath them
    const feature =
      features.find((f) => f.layer.type === "circle" || f.layer.type === "symbol") ||
      features[0];
    if (feature.properties.cluster) {
      map
        .getSource(POINTS_SOURCE)
        .getClusterExpansionZoom(feature.properties.cluster_id)
        .then((zoom) => {
          map.easeTo({ center: feature.geometry.coordinates, zoom });
        });
      return;
    }
    const index = feature.properties._row;
    const row = rows[index];
    if (!row) {
      return;
    }
    const content = popupContent(row);
    if (domRows[index] && pageType !== "row") {
      content.appendChild(
        h(
          "a",
          {
            href: "#",
            class: "dmap-popup-row",
            onclick: (click) => {
              click.preventDefault();
              domRows[index].scrollIntoView({ behavior: "smooth", block: "center" });
            },
          },
          "Show in table ↓"
        )
      );
    }
    markTableRow(index);
    new library.Popup({ maxWidth: "320px" })
      .setLngLat(
        feature.geometry.type === "Point" ? feature.geometry.coordinates : ev.lngLat
      )
      .setDOMContent(content)
      .addTo(map);
    wrapper.dataset.popupRow = index;
  }

  function filterToArea() {
    const round = (n) => Math.round(n * 100000) / 100000;
    const area = map.getBounds();
    const url = new URL(location.href);
    areaParams.forEach((param) => url.searchParams.delete(param));
    url.searchParams.delete("_next");
    url.searchParams.set(areaParams[0], round(Math.max(area.getSouth(), -90)));
    url.searchParams.set(areaParams[1], round(Math.min(area.getNorth(), 90)));
    if (area.getEast() - area.getWest() < 360) {
      url.searchParams.set(areaParams[2], round(Math.max(area.getWest(), -180)));
      url.searchParams.set(areaParams[3], round(Math.min(area.getEast(), 180)));
    }
    location.href = url.href;
  }

  function download() {
    const features = points.concat(shapes).map((feature) => {
      const properties = {};
      Object.entries(rows[feature.properties._row]).forEach(([key, value]) => {
        if (!parseGeoJSON(value)) {
          properties[key] = displayValue(value);
        }
      });
      return { type: "Feature", properties, geometry: feature.geometry };
    });
    const blob = new Blob([JSON.stringify(featureCollection(features))], {
      type: "application/geo+json",
    });
    const name = decodeURIComponent(location.pathname.split("/").pop() || "map");
    const a = h("a", { href: URL.createObjectURL(blob), download: name + ".geojson" });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  /* Colour */
  function listColumns() {
    if (columnsListed || !rows.length) {
      return;
    }
    columnsListed = true;
    Object.keys(rows[0]).forEach((column) => {
      if (
        column !== latitudeColumn &&
        column !== longitudeColumn &&
        column !== "popup" &&
        !parseGeoJSON(rows[0][column])
      ) {
        colorSelect.appendChild(h("option", { value: column }, column));
      }
    });
    const wanted = (config.colorColumn || "").toLowerCase();
    const match = Object.keys(rows[0]).find((c) => c.toLowerCase() === wanted);
    if (wanted && match) {
      colorSelect.value = match;
      colorColumn = match;
    }
  }

  function setColorColumn(column) {
    colorColumn = column;
    applyColor();
    installLayers();
  }

  function applyColor() {
    scale = colorColumn ? colorScale(rows, colorColumn) : null;
    points.concat(shapes, centers).forEach((feature) => {
      if (scale) {
        feature.properties.c = scale.value(rows[feature.properties._row]);
      } else {
        delete feature.properties.c;
      }
    });
    legendEl.replaceChildren();
    wrapper.dataset.colorColumn = colorColumn || "";
    if (!scale) {
      return;
    }
    if (scale.legend.type === "ramp") {
      const ramp = h("span", { class: "dmap-ramp" });
      ramp.style.background = `linear-gradient(to right, ${RAMP_COLORS.join(", ")})`;
      legendEl.appendChild(
        h("span", {}, [
          colorColumn + ": " + scale.legend.min.toLocaleString(),
          ramp,
          scale.legend.max.toLocaleString(),
        ])
      );
    } else {
      const item = (color, label) => {
        const swatch = h("span", { class: "dmap-swatch" });
        swatch.style.background = color;
        return h("span", { class: "dmap-legend-item" }, [swatch, label]);
      };
      scale.legend.items.forEach(({ label, count, color }) =>
        legendEl.appendChild(item(color, `${label} (${count.toLocaleString()})`))
      );
      if (scale.legend.other) {
        legendEl.appendChild(item(OTHER_COLOR, "Other"));
      }
    }
  }

  /* Loading */
  function loadRows(path) {
    return fetch(path)
      .then((response) => {
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        return response.json();
      })
      .then((data) => {
        const pageRows = data.rows || [];
        let located = false;
        pageRows.forEach((row) => {
          located = addRow(row) || located;
        });
        listColumns();
        if (located) {
          showMap();
        }
        if (colorColumn) {
          // The scale depends on every row loaded so far
          applyColor();
          installLayers();
        }
        // Fix for http v.s. https
        let nextUrl = data.next_url;
        if (nextUrl && location.protocol === "https:") {
          nextUrl = nextUrl.replace(/^https?:/, "https:");
        }
        complete = !nextUrl;
        updateData();
        // Datasette 1.0 returns "count", earlier versions used
        // "filtered_table_rows_count". count_truncated means it is a lower bound.
        const total = data.count || data.filtered_table_rows_count;
        let ofTotal = "";
        let percent = "";
        if (total && data.count_truncated) {
          ofTotal = ` of ${(total - 1).toLocaleString()}+`;
        } else if (total) {
          ofTotal = ` of ${total.toLocaleString()}`;
          percent = ` (${Math.round((rows.length / total) * 10000) / 100}%)`;
        }
        const mapped = points.length + shapeRows;
        if (nextUrl) {
          addToPage();
          progressEl.textContent = map
            ? `Showing ${rows.length.toLocaleString()}${ofTotal}${percent} `
            : `No locations in the first ${rows.length.toLocaleString()}${ofTotal} rows `;
          progressEl.appendChild(
            keepGoing
              ? h(
                  "button",
                  { type: "button", onclick: () => (keepGoing = false) },
                  "pause"
                )
              : h(
                  "button",
                  {
                    type: "button",
                    onclick: () => {
                      keepGoing = true;
                      loadRows(nextUrl);
                    },
                  },
                  "load all"
                )
          );
          if (keepGoing) {
            return loadRows(nextUrl);
          }
        } else if (map) {
          progressEl.textContent =
            mapped === rows.length
              ? ""
              : `${mapped.toLocaleString()} of ${rows.length.toLocaleString()} rows have a location`;
        } else {
          // Every row has been fetched and none of them had a location
          wrapper.remove();
        }
      })
      .catch((error) => {
        console.warn("datasette-maplibre: could not load rows", error);
        if (wrapper.parentNode) {
          progressEl.textContent = "Could not load rows for the map: " + error.message;
        }
      });
  }

  let path = location.pathname + ".json";
  const params = new URLSearchParams(location.search);
  params.set("_shape", "objects");
  if (pageType !== "row") {
    params.set("_size", "max");
    params.set("_labels", "on");
  }
  if (pageType === "table") {
    // Datasette 1.0 rejects ?_extra= values it does not know about, and
    // count is only available for tables and views
    params.set("_extra", "count");
  }
  path += "?" + params.toString();
  return loadLibrary().then((loaded) => {
    library = loaded;
    return loadRows(path);
  });
}

/* ---------- Start ---------- */

function start() {
  if (!config || !document.querySelector("table.rows-and-columns")) {
    return;
  }
  const body = document.body.classList;
  const pageType = body.contains("table")
    ? "table"
    : body.contains("row")
      ? "row"
      : "query";
  const cells = findGeoJSONCells();
  const columns = Array.from(
    document.querySelectorAll("table.rows-and-columns th")
  ).map((th) => (th.getAttribute("data-column") || th.textContent).trim());
  const find = (name) =>
    (name && columns.find((c) => c.toLowerCase() === name.toLowerCase())) || null;
  const latitudeColumn = find(config.latitudeColumn);
  const longitudeColumn = find(config.longitudeColumn);
  const hasLocationColumns = Boolean(latitudeColumn && longitudeColumn);
  // Rows with a single GeoJSON value already get a map in their cell, so an
  // overview of shapes is only useful when there are several of them
  const rowsWithCells = new Set(cells.map((cell) => cell.td.parentNode)).size;
  if (hasLocationColumns || (pageType !== "row" && rowsWithCells > 1)) {
    overviewMap({
      latitudeColumn: hasLocationColumns ? latitudeColumn : null,
      longitudeColumn: hasLocationColumns ? longitudeColumn : null,
      pageType,
    });
  }
  setUpCells(cells);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", start);
} else {
  start();
}
