/** Road-following forecast bands for the map. */
import { RISK_LEVELS } from "./riskUtils.js";

const EARTH_RADIUS_METERS = 6371008.8;

function haversineMeters(a, b) {
  const rad = Math.PI / 180;
  const lat1 = a[1] * rad;
  const lat2 = b[1] * rad;
  const dLat = lat2 - lat1;
  const dLon = (b[0] - a[0]) * rad;
  const x =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_METERS * Math.asin(Math.min(1, Math.sqrt(x)));
}

export function sampleKey(lat, lon) {
  if (lat == null || lon == null || lat === "" || lon === "") return null;
  const latitude = Number(lat);
  const longitude = Number(lon);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  // Match the backend's (round(lat, 4), round(lon, 4)) cache key.
  return `${latitude.toFixed(4)},${longitude.toFixed(4)}`;
}

function lowerBound(values, target) {
  let left = 0;
  let right = values.length;
  while (left < right) {
    const middle = Math.floor((left + right) / 2);
    if (values[middle] < target) left = middle + 1;
    else right = middle;
  }
  return left;
}

export function routeLineDistances(geometry, anchors) {
  const distances = [0];
  for (let i = 1; i < geometry.length; i++) {
    distances.push(
      distances[i - 1] + haversineMeters(geometry[i - 1], geometry[i]),
    );
  }
  if (!Array.isArray(anchors) || anchors.length < 2) return distances;
  const valid = anchors.every(
    (pair, index) =>
      Array.isArray(pair) &&
      pair.length === 2 &&
      Number.isInteger(pair[0]) &&
      Number.isFinite(pair[1]) &&
      pair[1] >= 0 &&
      pair[0] >= 0 &&
      pair[0] < geometry.length &&
      (index === 0 ||
        (pair[0] > anchors[index - 1][0] && pair[1] > anchors[index - 1][1])),
  );
  if (
    !valid ||
    anchors[0][0] !== 0 ||
    anchors.at(-1)[0] !== geometry.length - 1
  ) {
    return distances;
  }
  const road = [...distances];
  for (let i = 1; i < anchors.length; i++) {
    const [startIndex, startDistance] = anchors[i - 1];
    const [endIndex, endDistance] = anchors[i];
    const span = distances[endIndex] - distances[startIndex];
    if (span <= 0) return distances;
    for (let j = startIndex; j <= endIndex; j++) {
      road[j] =
        startDistance +
        ((distances[j] - distances[startIndex]) / span) *
          (endDistance - startDistance);
    }
  }
  return road.every((value, i) => i === 0 || value > road[i - 1])
    ? road
    : distances;
}

function pointAtDistance(geometry, distances, distance) {
  if (distance <= 0) return geometry[0];
  const total = distances[distances.length - 1];
  if (distance >= total) return geometry[geometry.length - 1];
  const index = lowerBound(distances, distance);
  const previous = index - 1;
  const length = distances[index] - distances[previous];
  if (length === 0) return geometry[index];
  const ratio = (distance - distances[previous]) / length;
  return [
    geometry[previous][0] +
      ratio * (geometry[index][0] - geometry[previous][0]),
    geometry[previous][1] +
      ratio * (geometry[index][1] - geometry[previous][1]),
  ];
}

function sliceGeometry(geometry, distances, start, end) {
  const coordinates = [pointAtDistance(geometry, distances, start)];
  for (
    let index = lowerBound(distances, start);
    index < distances.length;
    index++
  ) {
    if (distances[index] >= end) break;
    if (distances[index] > start) coordinates.push(geometry[index]);
  }
  coordinates.push(pointAtDistance(geometry, distances, end));
  return coordinates.filter(
    (point, i) =>
      i === 0 ||
      point[0] !== coordinates[i - 1][0] ||
      point[1] !== coordinates[i - 1][1],
  );
}

/** Split the road at midpoints between weather checkpoints. */
export function buildCorridorFeatures(routes) {
  const features = [];
  for (const route of routes ?? []) {
    const geometry = route.geometry;
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
    )
      continue;

    const distances = routeLineDistances(
      geometry,
      route.geometry_road_progress,
    );
    const totalGeometryMeters = distances[distances.length - 1];
    const routeMiles = Number(route.distance_meters) / 1609.344;
    if (!(totalGeometryMeters > 0 && routeMiles > 0)) continue;

    const checkpoints = (route.checkpoints ?? [])
      .filter(
        (checkpoint) =>
          sampleKey(checkpoint.lat, checkpoint.lon) &&
          Number.isFinite(Number(checkpoint.mile)) &&
          Number(checkpoint.mile) >= 0 &&
          Number(checkpoint.mile) <= routeMiles + 0.1,
      )
      .sort((a, b) => Number(a.mile) - Number(b.mile));

    for (let i = 0; i < checkpoints.length; i++) {
      const current = checkpoints[i];
      const startMile =
        i === 0
          ? 0
          : (Number(checkpoints[i - 1].mile) + Number(current.mile)) / 2;
      const endMile =
        i === checkpoints.length - 1
          ? routeMiles
          : (Number(current.mile) + Number(checkpoints[i + 1].mile)) / 2;
      const start = Math.max(
        0,
        Math.min(
          totalGeometryMeters,
          (startMile / routeMiles) * totalGeometryMeters,
        ),
      );
      const end = Math.max(
        0,
        Math.min(
          totalGeometryMeters,
          (endMile / routeMiles) * totalGeometryMeters,
        ),
      );
      if (end <= start) continue;
      const coordinates = sliceGeometry(geometry, distances, start, end);
      if (coordinates.length < 2) continue;
      features.push({
        type: "Feature",
        id: features.length,
        properties: {
          routeId: route.id,
          sampleKey: sampleKey(current.lat, current.lon),
        },
        geometry: { type: "LineString", coordinates },
      });
    }
  }
  return features;
}

/** Place forecast rings at checkpoint positions. */
export function buildForecastMarkerFeatures(routes) {
  const features = [];
  for (const route of routes ?? []) {
    const checkpoints = route.checkpoints ?? [];
    const valid = checkpoints.filter((checkpoint) => {
      const lon = Number(checkpoint.lon);
      const lat = Number(checkpoint.lat);
      return (
        checkpoint.lat != null &&
        checkpoint.lon != null &&
        String(checkpoint.lat).trim() !== "" &&
        String(checkpoint.lon).trim() !== "" &&
        Number.isFinite(lat) &&
        Number.isFinite(lon) &&
        Math.abs(lat) <= 90 &&
        Math.abs(lon) <= 180 &&
        sampleKey(lat, lon)
      );
    });
    // Show fewer rings when the map is zoomed out.
    const firstMile = Number(valid[0]?.mile);
    const secondMile = Number(valid[1]?.mile);
    const spacing = secondMile - firstMile;
    const validSpacing = Number.isFinite(spacing) && spacing > 0 ? spacing : 50;
    const overviewStep = Math.max(1, Math.round(50 / validSpacing));
    const midStep = Math.max(1, Math.round(25 / validSpacing));
    const seen = new Set();

    for (let i = 0; i < valid.length; i++) {
      const checkpoint = valid[i];
      const lon = Number(checkpoint.lon);
      const lat = Number(checkpoint.lat);
      const key = sampleKey(lat, lon);
      if (seen.has(key)) continue;
      seen.add(key);
      const last = i === valid.length - 1;
      features.push({
        type: "Feature",
        id: features.length,
        properties: {
          routeId: route.id,
          sampleKey: key,
          overview: i % overviewStep === 0 || last,
          midZoom: i % midStep === 0 || last,
        },
        geometry: { type: "Point", coordinates: [lon, lat] },
      });
    }
  }
  return features;
}

/** Update risk colors without rebuilding road lines. */
export function riskStateUpdates(features, heatmap, hour) {
  const riskBySample = new Map();
  for (const sample of heatmap?.samples ?? []) {
    const key = sampleKey(sample.lat, sample.lon);
    if (!key) continue;
    const reading = sample.hours?.[hour];
    const level =
      reading &&
      Number.isFinite(reading.score) &&
      RISK_LEVELS.includes(reading.level)
        ? reading.level
        : "Unknown";
    riskBySample.set(key, level);
  }
  return features.map((feature) => ({
    id: feature.id,
    riskLevel: riskBySample.get(feature.properties.sampleKey) ?? "Unknown",
  }));
}
