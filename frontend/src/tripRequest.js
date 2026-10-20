/** Check form input before sending it to Django. */
export function validateTrip(form) {
  const origin = String(form.origin ?? "").trim();
  const destination = String(form.destination ?? "").trim();
  if (!origin || !destination) return "Enter both an origin and a destination.";
  if (origin.toLowerCase() === destination.toLowerCase()) {
    return "Origin and destination must be different.";
  }

  const departure = String(form.departure_time ?? "");
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(departure);
  if (!match) return "Choose a valid departure date and time.";
  const [, year, month, day, hour, minute] = match.map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day, hour, minute));
  if (
    parsed.getUTCFullYear() !== year ||
    parsed.getUTCMonth() + 1 !== month ||
    parsed.getUTCDate() !== day ||
    parsed.getUTCHours() !== hour ||
    parsed.getUTCMinutes() !== minute
  )
    return "Choose a valid departure date and time.";

  const load = Number(form.load_weight_lb);
  if (
    String(form.load_weight_lb ?? "").trim() === "" ||
    !Number.isSafeInteger(load) ||
    load <= 0
  ) {
    return "Load weight must be a positive whole number of pounds.";
  }
  const spacing = Number(form.checkpoint_miles);
  if (![10, 25, 50].includes(spacing)) {
    return "Checkpoint spacing must be 10, 25, or 50 miles.";
  }
  return null;
}

export function makeTripPayload(form) {
  return {
    origin: String(form.origin).trim(),
    destination: String(form.destination).trim(),
    departure_time: form.departure_time,
    load_weight_lb: Number(form.load_weight_lb),
    checkpoint_miles: Number(form.checkpoint_miles),
  };
}

export function apiEndpoint(baseUrl, endpoint) {
  return `${String(baseUrl).replace(/\/+$/, "")}/${endpoint.replace(/^\/+/, "")}`;
}

export function errorMessage(data) {
  if (!data || typeof data !== "object")
    return "The server returned an unexpected response.";
  if (typeof data.error === "string" && data.error.trim()) return data.error;
  if (data.errors && typeof data.errors === "object") {
    const details = Object.entries(data.errors)
      .map(([field, messages]) => {
        const message = Array.isArray(messages)
          ? messages.join(", ")
          : typeof messages === "string"
            ? messages
            : JSON.stringify(messages);
        return `${field}: ${message}`;
      })
      .join(" | ");
    if (details) return details;
  }
  if (typeof data.detail === "string" && data.detail.trim()) return data.detail;
  return "Something went wrong while calculating routes.";
}

const finite = (value) => typeof value === "number" && Number.isFinite(value);
const position = (value) =>
  Array.isArray(value) &&
  value.length === 2 &&
  finite(value[0]) &&
  finite(value[1]) &&
  Math.abs(value[0]) <= 180 &&
  Math.abs(value[1]) <= 90;
const dateTime = (value) =>
  typeof value === "string" &&
  /(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
  Number.isFinite(Date.parse(value));

function validCheckpoint(checkpoint) {
  return (
    checkpoint &&
    Number.isInteger(checkpoint.id) &&
    finite(checkpoint.mile) &&
    checkpoint.mile >= 0 &&
    finite(checkpoint.lat) &&
    Math.abs(checkpoint.lat) <= 90 &&
    finite(checkpoint.lon) &&
    Math.abs(checkpoint.lon) <= 180 &&
    dateTime(checkpoint.eta) &&
    checkpoint.risk &&
    typeof checkpoint.risk.level === "string" &&
    (checkpoint.weather === null ||
      (checkpoint.weather &&
        ["wind_mph", "rain_in_hr", "snow_in_hr"].every(
          (key) =>
            finite(checkpoint.weather[key]) && checkpoint.weather[key] >= 0,
        )))
  );
}

function validRoute(route) {
  const summary = route?.risk_summary;
  return (
    Number.isInteger(route?.id) &&
    typeof route.name === "string" &&
    finite(route.distance_meters) &&
    route.distance_meters > 0 &&
    finite(route.distance_miles) &&
    route.distance_miles >= 0 &&
    finite(route.duration_seconds) &&
    route.duration_seconds >= 0 &&
    dateTime(route.departure_time) &&
    dateTime(route.arrival_time) &&
    Array.isArray(route.geometry) &&
    route.geometry.length >= 2 &&
    route.geometry.every(position) &&
    Array.isArray(route.checkpoints) &&
    route.checkpoints.length >= 2 &&
    route.checkpoints.every(validCheckpoint) &&
    summary &&
    ["eligible", "incomplete", "no_travel"].includes(summary.status) &&
    finite(summary.coverage_percent) &&
    summary.coverage_percent >= 0 &&
    summary.coverage_percent <= 100 &&
    Number.isInteger(summary.checkpoint_count) &&
    Number.isInteger(summary.forecasted_checkpoints) &&
    summary.checkpoint_count === route.checkpoints.length &&
    summary.forecasted_checkpoints <= summary.checkpoint_count &&
    (route.geometry_road_progress == null ||
      (Array.isArray(route.geometry_road_progress) &&
        route.geometry_road_progress.every(
          (anchor) =>
            Array.isArray(anchor) &&
            anchor.length === 2 &&
            Number.isInteger(anchor[0]) &&
            finite(anchor[1]),
        )))
  );
}

/** Reject incomplete data before passing it to the map. */
export function validateTripResponse(data) {
  if (
    !data ||
    !Array.isArray(data.routes) ||
    data.routes.length < 1 ||
    data.routes.length > 3
  ) {
    throw new Error("No usable routes were returned by the routing API.");
  }
  if (
    typeof data.origin?.name !== "string" ||
    typeof data.destination?.name !== "string" ||
    !data.trip ||
    data.routes.some((route) => !validRoute(route))
  ) {
    throw new Error("The routing API returned incomplete trip information.");
  }
  if (
    data.heatmap != null &&
    (!dateTime(data.heatmap.start_time) ||
      data.heatmap.hour_count !== 49 ||
      !Array.isArray(data.heatmap.samples) ||
      data.heatmap.samples.some(
        (sample) =>
          !finite(sample.lat) ||
          !finite(sample.lon) ||
          !Array.isArray(sample.hours) ||
          sample.hours.length !== 49,
      ))
  ) {
    throw new Error("The routing API returned invalid weather data.");
  }
  return data;
}

/** Handle errors even when the server does not return JSON. */
export async function fetchTripRoutes(
  baseUrl,
  payload,
  { signal, fetchImpl = fetch } = {},
) {
  let response;
  try {
    response = await fetchImpl(apiEndpoint(baseUrl, "routes/"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new Error(
      "Cannot reach the routing service. Check that Django is running and try again.",
      { cause: error },
    );
  }
  let data;
  try {
    data = await response.json();
  } catch {
    if (!response.ok)
      throw new Error(
        `Routing service error (HTTP ${response.status}). Please try again.`,
      );
    throw new Error("The routing service returned invalid JSON.");
  }
  if (!response.ok) throw new Error(errorMessage(data));
  return validateTripResponse(data);
}

export function recommendedOrFirstId(routes, recommendedId) {
  return (
    routes.find((route) => route.id === recommendedId)?.id ??
    routes[0]?.id ??
    null
  );
}
