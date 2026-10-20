import { useEffect, useRef, useState } from "react";
import {
  Map as MapLibreMap,
  NavigationControl,
  Marker,
  Popup,
  LngLatBounds,
  setWorkerUrl,
} from "maplibre-gl";

import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import "./RouteMap.css";
import { RISK_COLORS, RISK_LEVELS, formatETA } from "./riskUtils";
import {
  checkpointForecastComparison,
  formatSliderForecastTime,
} from "./forecastPopupUtils";
import {
  sampleKey,
  buildCorridorFeatures,
  buildForecastMarkerFeatures,
  riskStateUpdates,
} from "./corridorUtils";
import {
  createRouteGeoJSON,
  createCheckpointGeoJSON,
  selectedRouteFilter,
  displayedForecastHour,
  forecastHourLimit,
} from "./routeMapUtils";

setWorkerUrl(workerUrl);

const MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";
const ROUTE_SOURCE = "truck-routes";
const CHECKPOINT_SOURCE = "weather-checkpoints";
const HEATMAP_SOURCE = "hourly-corridor-forecast";
const HEATMAP_LAYER = "forecast-heatmap";
const HEATMAP_GLOW_LAYER = "forecast-heatmap-glow";
const FORECAST_MARKER_SOURCE = "forecast-hour-markers";
const FORECAST_MARKER_HALO = "forecast-marker-outer-halo";
const FORECAST_MARKER_RING = "forecast-marker-risk-ring";
const SELECTED_LAYER = "selected-route";
const RECOMMENDED_LAYER = "recommended-route-halo";
const CHECKPOINT_LAYER = "checkpoint-circles";

function emptyGeoJSON() {
  return { type: "FeatureCollection", features: [] };
}

// Move only the risk colors when the slider changes.
const CORRIDOR_RISK_COLOR = [
  "match",
  ["feature-state", "riskLevel"],
  "Low",
  RISK_COLORS.Low,
  "Moderate",
  RISK_COLORS.Moderate,
  "High",
  RISK_COLORS.High,
  "Severe",
  RISK_COLORS.Severe,
  "No Travel",
  RISK_COLORS["No Travel"],
  RISK_COLORS.Unknown,
];

// Show more forecast rings as the driver zooms in.
function forecastMarkerVisibility(opacity) {
  return [
    "step",
    ["zoom"],
    ["case", ["get", "overview"], opacity, 0],
    5.5,
    ["case", ["get", "midZoom"], opacity, 0],
    8.5,
    opacity,
  ];
}

const FORECAST_MARKER_RADIUS = [
  "interpolate",
  ["linear"],
  ["zoom"],
  3,
  10,
  6,
  13,
  10,
  17,
];
const FORECAST_MARKER_OUTER_RADIUS = [
  "interpolate",
  ["linear"],
  ["zoom"],
  3,
  15,
  6,
  18,
  10,
  22,
];

function updateForecastMarkerGeometry(map, routes, markerRef) {
  const source = map.getSource(FORECAST_MARKER_SOURCE);
  if (!source) return;
  const features = buildForecastMarkerFeatures(routes);
  markerRef.current = features;
  source.setData({ type: "FeatureCollection", features });
}

function updateCorridorGeometry(map, routes, corridorRef) {
  const source = map.getSource(HEATMAP_SOURCE);
  if (!source) return;
  const features = buildCorridorFeatures(routes);
  corridorRef.current = features;
  source.setData({ type: "FeatureCollection", features });
}

function updateHeatmap(map, heatmap, hour, visible, features, markers) {
  if (!map.getSource(HEATMAP_SOURCE)) return;
  const show = Boolean(visible && heatmap?.samples?.length && features.length);
  for (const layerId of [
    HEATMAP_GLOW_LAYER,
    HEATMAP_LAYER,
    FORECAST_MARKER_HALO,
    FORECAST_MARKER_RING,
  ]) {
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, "visibility", show ? "visible" : "none");
    }
  }
  if (!show) return;
  for (const update of riskStateUpdates(features, heatmap, hour)) {
    map.setFeatureState(
      { source: HEATMAP_SOURCE, id: update.id },
      { riskLevel: update.riskLevel },
    );
  }
  for (const update of riskStateUpdates(markers, heatmap, hour)) {
    map.setFeatureState(
      { source: FORECAST_MARKER_SOURCE, id: update.id },
      { riskLevel: update.riskLevel },
    );
  }
}

function addPopupLine(container, label, value) {
  const line = document.createElement("div");
  const labelNode = document.createElement("strong");
  labelNode.textContent = `${label}: `;
  line.append(labelNode, document.createTextNode(String(value)));
  container.append(line);
}

function formatReading(value, decimals, unit) {
  return value == null || !Number.isFinite(Number(value))
    ? "Unavailable"
    : `${Number(value).toFixed(decimals)} ${unit}`;
}

function appendRiskSection(content, title, time, level, weather, reason) {
  const section = document.createElement("section");
  section.className = "checkpoint-popup-section";

  const header = document.createElement("div");
  header.className = "checkpoint-popup-section-header";
  const heading = document.createElement("strong");
  heading.textContent = title;
  const badge = document.createElement("span");
  badge.className = "checkpoint-popup-level";
  badge.style.color = RISK_COLORS[level] || RISK_COLORS.Unknown;
  badge.textContent = level;
  header.append(heading, badge);
  section.append(header);

  addPopupLine(section, "Time", time);
  if (reason) addPopupLine(section, "Reason", reason);
  if (weather) {
    addPopupLine(section, "Wind", formatReading(weather.wind_mph, 1, "mph"));
    addPopupLine(
      section,
      "Rain",
      formatReading(weather.rain_in_hr, 3, "in/hr"),
    );
    addPopupLine(
      section,
      "Snow",
      formatReading(weather.snow_in_hr, 3, "in/hr"),
    );
  } else {
    addPopupLine(section, "Forecast", "Unavailable");
  }
  content.append(section);
}

// Both weather markers show this popup; the slider updates its reading.
function checkpointPopup(properties, coordinates, heatmap, hour) {
  const content = document.createElement("div");
  content.className = "checkpoint-popup";
  const title = document.createElement("strong");
  title.className = "checkpoint-popup-title";
  title.textContent = `${properties.routeName ?? "Route"}, mile ${properties.mile ?? "?"}`;
  content.append(title);

  const comparison = checkpointForecastComparison(
    properties,
    coordinates,
    heatmap,
    hour,
  );
  appendRiskSection(
    content,
    "At truck arrival",
    `${formatETA(comparison.arrival.eta)} (device time)`,
    comparison.arrival.level,
    comparison.arrival.weather,
    comparison.arrival.reason,
  );
  if (heatmap?.samples?.length) {
    appendRiskSection(
      content,
      `At forecast slider (+${hour}h)`,
      comparison.slider.time,
      comparison.slider.level,
      comparison.slider.weather,
      null,
    );
  }

  const note = document.createElement("p");
  note.className = "checkpoint-popup-note";
  note.textContent =
    "Route safety and recommendations use weather at truck arrival, not the forecast slider hour.";
  content.append(note);
  return content;
}

function removeActivePopup(activePopupRef) {
  activePopupRef.current?.popup.remove();
  activePopupRef.current = null;
}

function refreshActivePopup(activePopupRef, heatmap, hour) {
  const active = activePopupRef.current;
  if (!active) return;
  active.popup.setDOMContent(
    checkpointPopup(active.properties, active.coordinates, heatmap, hour),
  );
}

function openCheckpointPopup(map, activePopupRef, feature, heatmap, hour) {
  removeActivePopup(activePopupRef);
  const popup = new Popup({ closeButton: true, maxWidth: "380px" })
    .setLngLat(feature.geometry.coordinates)
    .setDOMContent(
      checkpointPopup(
        feature.properties || {},
        feature.geometry.coordinates,
        heatmap,
        hour,
      ),
    )
    .addTo(map);
  const active = {
    popup,
    properties: feature.properties || {},
    coordinates: feature.geometry.coordinates,
  };
  activePopupRef.current = active;
  popup.on("close", () => {
    if (activePopupRef.current === active) activePopupRef.current = null;
  });
}

function clearMarkers(markersRef) {
  markersRef.current.forEach((marker) => marker.remove());
  markersRef.current = [];
}

function updateCheckpoints(map, routeData, routeId) {
  const source = map.getSource(CHECKPOINT_SOURCE);
  if (source) source.setData(createCheckpointGeoJSON(routeData, routeId));
}

function drawRoutes(map, routeData, markersRef) {
  const source = map.getSource(ROUTE_SOURCE);
  if (!source) return;

  const validRoutes = routeData.filter(
    (route) => Array.isArray(route.geometry) && route.geometry.length >= 2,
  );

  source.setData(createRouteGeoJSON(validRoutes));
  clearMarkers(markersRef);
  if (!validRoutes.length) return;

  const bounds = new LngLatBounds();
  validRoutes.forEach((route) =>
    route.geometry.forEach((point) => bounds.extend(point)),
  );

  const firstRoute = validRoutes[0];
  const origin = firstRoute.geometry[0];
  const destination = firstRoute.geometry.at(-1);

  markersRef.current = [
    new Marker({ color: "#16a34a" })
      .setLngLat(origin)
      .setPopup(new Popup().setText("Origin"))
      .addTo(map),
    new Marker({ color: "#dc2626" })
      .setLngLat(destination)
      .setPopup(new Popup().setText("Destination"))
      .addTo(map),
  ];

  map.fitBounds(bounds, { padding: 60, maxZoom: 12, duration: 600 });
}

export default function RouteMap({
  routes = [],
  selectedRouteId = 0,
  heatmap = null,
}) {
  const containerRef = useRef(null);
  const [mapError, setMapError] = useState("");
  const mapRef = useRef(null);
  const markersRef = useRef([]);
  const activePopupRef = useRef(null);
  const popupHeatmapRef = useRef(heatmap);
  const routesRef = useRef(routes);
  const selectedRef = useRef(selectedRouteId);
  const heatmapRef = useRef(heatmap);
  // Reset the slider when the trip changes.
  const [forecastSelection, setForecastSelection] = useState({
    heatmap,
    hour: 0,
  });
  const forecastHour = displayedForecastHour(forecastSelection, heatmap);
  const maxForecastHour = forecastHourLimit(heatmap);
  const [showHeatmap, setShowHeatmap] = useState(true);
  const hourRef = useRef(forecastHour);
  const visibleRef = useRef(showHeatmap);
  const corridorRef = useRef([]);
  const forecastMarkersRef = useRef([]);
  const heatmapFrameRef = useRef(null);

  useEffect(() => {
    routesRef.current = routes;
    selectedRef.current = selectedRouteId;
  }, [routes, selectedRouteId]);

  useEffect(() => {
    if (popupHeatmapRef.current !== heatmap) {
      removeActivePopup(activePopupRef);
      popupHeatmapRef.current = heatmap;
    }
    heatmapRef.current = heatmap;
    hourRef.current = forecastHour;
    visibleRef.current = showHeatmap;
    if (heatmapFrameRef.current !== null) {
      cancelAnimationFrame(heatmapFrameRef.current);
    }
    heatmapFrameRef.current = requestAnimationFrame(() => {
      heatmapFrameRef.current = null;
      const map = mapRef.current;
      if (map)
        updateHeatmap(
          map,
          heatmap,
          forecastHour,
          showHeatmap,
          corridorRef.current,
          forecastMarkersRef.current,
        );
      refreshActivePopup(activePopupRef, heatmap, forecastHour);
    });
    return () => {
      if (heatmapFrameRef.current !== null) {
        cancelAnimationFrame(heatmapFrameRef.current);
        heatmapFrameRef.current = null;
      }
    };
  }, [heatmap, forecastHour, showHeatmap]);

  useEffect(() => {
    if (!containerRef.current) return;

    const map = new MapLibreMap({
      container: containerRef.current,
      style: MAP_STYLE,
      center: [-105, 39],
      zoom: 4,
    });

    mapRef.current = map;
    map.addControl(new NavigationControl(), "top-right");

    // Resize the map when its container changes size.
    let resizeFrame = null;
    const resizeObserver =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => {
            if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
            resizeFrame = requestAnimationFrame(() => {
              resizeFrame = null;
              if (mapRef.current === map) map.resize();
            });
          })
        : null;
    if (resizeObserver) resizeObserver.observe(containerRef.current);

    function handleMapLoad() {
      setMapError("");
      map.addSource(ROUTE_SOURCE, { type: "geojson", data: emptyGeoJSON() });

      // Draw weather bands along the roads.
      map.addSource(HEATMAP_SOURCE, {
        type: "geojson",
        data: emptyGeoJSON(),
      });
      map.addSource(FORECAST_MARKER_SOURCE, {
        type: "geojson",
        data: emptyGeoJSON(),
      });
      map.addLayer({
        id: HEATMAP_GLOW_LAYER,
        type: "line",
        source: HEATMAP_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": CORRIDOR_RISK_COLOR,
          "line-width": ["interpolate", ["linear"], ["zoom"], 3, 15, 10, 32],
          "line-opacity": 0.24,
          "line-blur": 3,
        },
      });
      map.addLayer({
        id: HEATMAP_LAYER,
        type: "line",
        source: HEATMAP_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": CORRIDOR_RISK_COLOR,
          "line-width": ["interpolate", ["linear"], ["zoom"], 3, 8, 10, 19],
          "line-opacity": 0.55,
          "line-blur": 1,
        },
      });

      map.addLayer({
        id: "all-routes",
        type: "line",
        source: ROUTE_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": ["get", "routeColor"],
          "line-width": 5,
          "line-opacity": 0.55,
        },
      });

      // Keep the recommended route visible when selecting another.
      map.addLayer({
        id: RECOMMENDED_LAYER,
        type: "line",
        source: ROUTE_SOURCE,
        filter: ["==", ["get", "recommended"], true],
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": "#16a34a",
          "line-width": 11,
          "line-opacity": 0.75,
          "line-dasharray": [2, 1],
        },
      });

      map.addLayer({
        id: SELECTED_LAYER,
        type: "line",
        source: ROUTE_SOURCE,
        filter: selectedRouteFilter(selectedRef.current),
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": ["get", "routeColor"],
          "line-width": 8,
        },
      });

      // Rings show slider weather; dots show arrival weather.
      map.addLayer({
        id: FORECAST_MARKER_HALO,
        type: "circle",
        source: FORECAST_MARKER_SOURCE,
        filter: selectedRouteFilter(selectedRef.current),
        paint: {
          "circle-radius": FORECAST_MARKER_OUTER_RADIUS,
          "circle-color": "#ffffff",
          "circle-opacity": forecastMarkerVisibility(0.8),
          "circle-stroke-color": "#334155",
          "circle-stroke-width": 1.5,
          "circle-stroke-opacity": forecastMarkerVisibility(0.55),
        },
      });
      map.addLayer({
        id: FORECAST_MARKER_RING,
        type: "circle",
        source: FORECAST_MARKER_SOURCE,
        filter: selectedRouteFilter(selectedRef.current),
        paint: {
          "circle-radius": FORECAST_MARKER_RADIUS,
          "circle-color": CORRIDOR_RISK_COLOR,
          "circle-opacity": forecastMarkerVisibility(0.7),
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 2,
          "circle-stroke-opacity": forecastMarkerVisibility(1),
        },
      });

      map.addSource(CHECKPOINT_SOURCE, {
        type: "geojson",
        data: emptyGeoJSON(),
      });

      map.addLayer({
        id: CHECKPOINT_LAYER,
        type: "circle",
        source: CHECKPOINT_SOURCE,
        layout: { "circle-sort-key": ["case", ["get", "selected"], 1, 0] },
        paint: {
          "circle-radius": ["case", ["get", "selected"], 7, 4.5],
          "circle-opacity": ["case", ["get", "selected"], 1, 0.7],
          "circle-color": [
            "match",
            ["get", "riskLevel"],
            "Low",
            RISK_COLORS.Low,
            "Moderate",
            RISK_COLORS.Moderate,
            "High",
            RISK_COLORS.High,
            "Severe",
            RISK_COLORS.Severe,
            "No Travel",
            RISK_COLORS["No Travel"],
            RISK_COLORS.Unknown,
          ],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": ["case", ["get", "selected"], 2, 1],
        },
      });

      drawRoutes(map, routesRef.current, markersRef);
      updateCheckpoints(map, routesRef.current, selectedRef.current);
      updateCorridorGeometry(map, routesRef.current, corridorRef);
      updateForecastMarkerGeometry(map, routesRef.current, forecastMarkersRef);
      updateHeatmap(
        map,
        heatmapRef.current,
        hourRef.current,
        visibleRef.current,
        corridorRef.current,
        forecastMarkersRef.current,
      );
    }

    function handleCheckpointClick(event) {
      const feature = event.features?.[0];
      if (!feature) return;
      openCheckpointPopup(
        map,
        activePopupRef,
        feature,
        heatmapRef.current,
        hourRef.current,
      );
    }

    function handleForecastRingClick(event) {
      const ring = event.features?.[0];
      if (!ring) return;
      // Do not open two popups when the dot and ring overlap.
      if (
        map.queryRenderedFeatures(event.point, {
          layers: [CHECKPOINT_LAYER],
        }).length
      )
        return;

      // Use the checkpoint data for both types of popup.
      const feature = createCheckpointGeoJSON(
        routesRef.current,
        selectedRef.current,
      ).features.find(
        (checkpoint) =>
          checkpoint.properties.routeId === ring.properties.routeId &&
          sampleKey(
            checkpoint.geometry.coordinates[1],
            checkpoint.geometry.coordinates[0],
          ) === ring.properties.sampleKey,
      );
      if (!feature) return;
      openCheckpointPopup(
        map,
        activePopupRef,
        feature,
        heatmapRef.current,
        hourRef.current,
      );
    }

    function handleMouseEnter() {
      map.getCanvas().style.cursor = "pointer";
    }

    function handleMouseLeave() {
      map.getCanvas().style.cursor = "";
    }

    function handleMapError() {
      if (!map.isStyleLoaded()) {
        setMapError(
          "Map tiles could not load. Check your connection and refresh.",
        );
      }
    }

    map.on("error", handleMapError);
    map.on("load", handleMapLoad);
    map.on("click", CHECKPOINT_LAYER, handleCheckpointClick);
    map.on("click", FORECAST_MARKER_RING, handleForecastRingClick);
    map.on("mouseenter", CHECKPOINT_LAYER, handleMouseEnter);
    map.on("mouseleave", CHECKPOINT_LAYER, handleMouseLeave);
    map.on("mouseenter", FORECAST_MARKER_RING, handleMouseEnter);
    map.on("mouseleave", FORECAST_MARKER_RING, handleMouseLeave);

    return () => {
      map.off("error", handleMapError);
      map.off("load", handleMapLoad);
      map.off("click", CHECKPOINT_LAYER, handleCheckpointClick);
      map.off("click", FORECAST_MARKER_RING, handleForecastRingClick);
      map.off("mouseenter", CHECKPOINT_LAYER, handleMouseEnter);
      map.off("mouseleave", CHECKPOINT_LAYER, handleMouseLeave);
      map.off("mouseenter", FORECAST_MARKER_RING, handleMouseEnter);
      map.off("mouseleave", FORECAST_MARKER_RING, handleMouseLeave);
      resizeObserver?.disconnect();
      if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
      removeActivePopup(activePopupRef);
      clearMarkers(markersRef);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource(ROUTE_SOURCE)) return;

    removeActivePopup(activePopupRef);
    drawRoutes(map, routes, markersRef);
    updateCheckpoints(map, routes, selectedRef.current);
    updateCorridorGeometry(map, routes, corridorRef);
    updateForecastMarkerGeometry(map, routes, forecastMarkersRef);
    updateHeatmap(
      map,
      heatmapRef.current,
      hourRef.current,
      visibleRef.current,
      corridorRef.current,
      forecastMarkersRef.current,
    );
  }, [routes]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getLayer(SELECTED_LAYER)) return;

    removeActivePopup(activePopupRef);
    map.setFilter(SELECTED_LAYER, selectedRouteFilter(selectedRouteId));
    for (const layerId of [FORECAST_MARKER_HALO, FORECAST_MARKER_RING]) {
      if (map.getLayer(layerId)) {
        map.setFilter(layerId, selectedRouteFilter(selectedRouteId));
      }
    }
    updateCheckpoints(map, routes, selectedRouteId);
  }, [selectedRouteId, routes]);

  return (
    <div className="route-map-frame">
      <div
        ref={containerRef}
        className="route-map"
        aria-label="Interactive truck routes and weather risk map"
      />
      {mapError && (
        <p className="map-error" role="alert">
          {mapError}
        </p>
      )}
      {heatmap?.samples?.length > 0 && (
        <div
          className="map-forecast-panel"
          aria-label="Forecast heatmap controls"
        >
          <div className="map-forecast-top">
            <strong>Weather heatmap</strong>
            <label className="map-forecast-toggle">
              <input
                type="checkbox"
                checked={showHeatmap}
                onChange={(event) => setShowHeatmap(event.target.checked)}
              />
              Show
            </label>
          </div>
          <label className="map-forecast-time" htmlFor="forecast-hour">
            +{forecastHour} hours —{" "}
            {formatSliderForecastTime(heatmap, forecastHour)}
          </label>
          <input
            id="forecast-hour"
            type="range"
            min="0"
            max={maxForecastHour}
            step="1"
            value={forecastHour}
            onChange={(event) =>
              setForecastSelection({
                heatmap,
                hour: Number(event.target.value),
              })
            }
            aria-label="Forecast hour from departure"
          />
          <div className="map-forecast-range">
            <span>0h</span>
            <span>{Math.round(maxForecastHour / 2)}h</span>
            <span>{maxForecastHour}h</span>
          </div>
          <details className="map-forecast-about">
            <summary>About this layer</summary>
            <p className="map-forecast-note">
              Coloured bands follow the road and show risk at the nearest
              sampled weather checkpoint; conditions between checkpoints are
              estimated, not continuously measured. Grey means Unknown. Hour 0
              is departure rounded up to the next UTC hour. Checkpoint dots use
              the truck's own estimated arrival time instead.
            </p>
          </details>
          {heatmap.samples.every((sample) => !sample.hours?.[forecastHour]) && (
            <p className="map-forecast-missing">
              No forecast is available for this hour.
            </p>
          )}
        </div>
      )}
      {routes.length > 0 && (
        <div className="map-risk-legend" aria-label="Map weather risk legend">
          <div className="map-risk-legend-title">
            Risk level (checkpoints and corridor)
          </div>
          <div className="map-risk-legend-levels">
            {[...RISK_LEVELS, "Unknown"].map((level) => (
              <span className="map-risk-legend-item" key={level}>
                <span
                  className="map-risk-dot"
                  style={{ backgroundColor: RISK_COLORS[level] }}
                />
                {level}
              </span>
            ))}
          </div>
          <div className="map-route-legend">
            <span>
              <span className="map-line selected" /> Selected
            </span>
            <span>
              <span className="map-line recommended" /> Recommended
            </span>
          </div>
          {heatmap?.samples?.length > 0 && showHeatmap && (
            <div className="map-weather-marker-guide">
              <span className="map-forecast-ring-key" aria-hidden="true">
                <span />
              </span>
              Outer rings: forecast at +{forecastHour}h. Center dots: weather at
              truck arrival. Click either for both readings.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
