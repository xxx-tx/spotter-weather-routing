import { RISK_LEVELS, ROUTE_COLORS } from "./riskUtils.js";

/**
 * The route card uses the displayed index, not the backend route ID, for its
 * color swatch. Put that same color on the GeoJSON feature so both stay in
 * sync if the backend reorders routes or returns non-consecutive IDs.
 */
export function createRouteGeoJSON(routes) {
  return {
    type: "FeatureCollection",
    features: (routes ?? []).flatMap((route, index) => {
      const geometry = route?.geometry;
      if (
        !Array.isArray(geometry) ||
        geometry.length < 2 ||
        !geometry.every(
          (point) =>
            Array.isArray(point) &&
            point.length >= 2 &&
            Number.isFinite(point[0]) &&
            Number.isFinite(point[1]),
        )
      ) {
        return [];
      }

      return [
        {
          type: "Feature",
          properties: {
            routeId: route.id,
            routeColor: ROUTE_COLORS[index % ROUTE_COLORS.length],
            recommended: route.is_recommended === true,
          },
          geometry: {
            type: "LineString",
            coordinates: geometry,
          },
        },
      ];
    }),
  };
}

// Every route's checkpoints are drawn; the selected route's are emphasised.
export function createCheckpointGeoJSON(routes, selectedRouteId) {
  return {
    type: "FeatureCollection",
    features: routes.flatMap((route) =>
      (route.checkpoints || [])
        .filter(
          (checkpoint) =>
            checkpoint.lon != null &&
            checkpoint.lat != null &&
            Number.isFinite(Number(checkpoint.lon)) &&
            Number.isFinite(Number(checkpoint.lat)),
        )
        .map((checkpoint) => ({
          type: "Feature",
          properties: {
            routeId: route.id,
            routeName: route.name,
            selected: route.id === selectedRouteId,
            mile: checkpoint.mile,
            eta: checkpoint.eta ?? "",
            riskLevel: RISK_LEVELS.includes(checkpoint.risk?.level)
              ? checkpoint.risk.level
              : "Unknown",
            riskReason:
              checkpoint.risk?.reason ?? "No risk assessment available",
            weatherAvailable: checkpoint.weather != null,
            wind: checkpoint.weather?.wind_mph ?? null,
            rain: checkpoint.weather?.rain_in_hr ?? null,
            snow: checkpoint.weather?.snow_in_hr ?? null,
          },
          geometry: {
            type: "Point",
            coordinates: [Number(checkpoint.lon), Number(checkpoint.lat)],
          },
        })),
    ),
  };
}

/** Selecting a route is ID-based, never dependent on the display position. */
export function selectedRouteFilter(routeId) {
  return ["==", ["get", "routeId"], routeId ?? null];
}

/** Keep the forecast slider within the API's 0–48-hour contract. */
export function forecastHourLimit(heatmap) {
  const count = heatmap?.hour_count;
  return Number.isInteger(count) && count >= 1 ? Math.min(48, count - 1) : 48;
}

/** A new trip has a new heatmap: it must open at hour zero, not the old hour. */
export function displayedForecastHour(selection, heatmap) {
  if (selection?.heatmap !== heatmap) return 0;
  const hour = Number(selection.hour);
  if (!Number.isFinite(hour)) return 0;
  return Math.min(forecastHourLimit(heatmap), Math.max(0, Math.floor(hour)));
}
