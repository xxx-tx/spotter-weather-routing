// Shared risk vocabulary so the map, route cards and checkpoint list agree.

export const RISK_LEVELS = ["Low", "Moderate", "High", "Severe", "No Travel"];

export const RISK_COLORS = {
  Low: "#15803d",
  Moderate: "#ca8a04",
  High: "#ea580c",
  Severe: "#dc2626",
  "No Travel": "#7f1d1d",
  Unknown: "#64748b",
};

// One colour per route, used for the map line and the card swatch.
export const ROUTE_COLORS = ["#2563eb", "#8b5cf6", "#d97706"];

export const STATUS_LABELS = {
  eligible: "Complete forecast",
  no_travel: "Has No Travel conditions",
  incomplete: "Forecast incomplete",
};

export function formatMiles(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "Unknown";
  return `${number.toLocaleString(undefined, { maximumFractionDigits: 1 })} mi`;
}

export function formatDuration(seconds) {
  if (seconds == null || !Number.isFinite(Number(seconds))) return "Unknown";

  const totalMinutes = Math.round(Number(seconds) / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;

  return hours === 0 ? `${minutes} min` : `${hours}h ${minutes}m`;
}

// The headline risk for a route: its worst condition, or why it has none.
export function routeRisk(route) {
  const summary = route?.risk_summary;
  if (!summary) return { label: "No data", color: RISK_COLORS.Unknown };

  if (summary.status === "no_travel") {
    return { label: "No Travel", color: RISK_COLORS["No Travel"] };
  }
  if (summary.status === "incomplete") {
    return { label: "Incomplete", color: RISK_COLORS.Unknown };
  }

  const worst = [...RISK_LEVELS]
    .reverse()
    .find((level) => (summary.miles_by_level?.[level] ?? 0) > 0);
  const level = worst ?? "Low";
  return { label: level, color: RISK_COLORS[level] };
}

// Segments for the stacked "miles at each risk level" bar.
export function riskSegments(route) {
  const miles = route?.risk_summary?.miles_by_level ?? {};
  const total = Object.values(miles).reduce((sum, value) => sum + value, 0);
  if (total <= 0) return [];

  return [...RISK_LEVELS, "Unknown"]
    .filter((level) => (miles[level] ?? 0) > 0)
    .map((level) => ({
      level,
      miles: miles[level],
      percent: (miles[level] / total) * 100,
      color: RISK_COLORS[level],
    }));
}

// Checkpoint and arrival timestamps represent absolute instants. Format in the
// user's *device* time zone, and label that choice explicitly in the UI.
// Location-local time zones must be supplied separately by the backend; they
// cannot be safely inferred from departure city names or browser settings.
export function deviceTimeZoneLabel() {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return zone ? `Device time zone: ${zone}` : "Device local time";
}

export function formatETA(value, { timeZone } = {}) {
  if (!value) return "Unavailable";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unavailable";

  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    ...(timeZone ? { timeZone } : {}),
    timeZoneName: "short",
  });
}
