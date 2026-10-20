/** Forecast context for an ETA checkpoint versus the heatmap slider hour.
 *
 * The backend recommends routes using weather at checkpoint ETA. The heatmap
 * uses a separate, fixed UTC timeline; never substitute slider data into the
 * arrival-time assessment.
 */
import { sampleKey } from "./corridorUtils.js";
import { RISK_LEVELS } from "./riskUtils.js";

export function isValidForecastReading(reading) {
  return Boolean(
    reading &&
    RISK_LEVELS.includes(reading.level) &&
    typeof reading.score === "number" &&
    Number.isFinite(reading.score),
  );
}

export function forecastAtCheckpoint(heatmap, lat, lon, hour) {
  const key = sampleKey(lat, lon);
  if (!key || !Number.isInteger(hour) || hour < 0 || hour > 48) {
    return { level: "Unknown", weather: null };
  }
  const sample = (heatmap?.samples ?? []).find(
    (entry) => sampleKey(entry?.lat, entry?.lon) === key,
  );
  const reading = sample?.hours?.[hour];
  if (!isValidForecastReading(reading)) {
    return { level: "Unknown", weather: null };
  }
  return { level: reading.level, weather: reading };
}

export function formatSliderForecastTime(heatmap, hour) {
  const start = Date.parse(heatmap?.start_time ?? "");
  if (
    !Number.isFinite(start) ||
    !Number.isInteger(hour) ||
    hour < 0 ||
    hour > 48
  ) {
    return "Time unavailable";
  }
  return new Date(start + hour * 3600000).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

export function checkpointForecastComparison(
  properties,
  coordinates,
  heatmap,
  hour,
) {
  const wind = properties.wind;
  const rain = properties.rain;
  const snow = properties.snow;
  const hasArrivalWeather =
    properties.weatherAvailable === true ||
    properties.weatherAvailable === "true";
  const arrival = {
    // Preserve a definite backend No Travel warning even if the rest of the
    // checkpoint forecast is incomplete. Never turn missing data into Low.
    level:
      RISK_LEVELS.includes(properties.riskLevel) &&
      (hasArrivalWeather || properties.riskLevel === "No Travel")
        ? properties.riskLevel
        : "Unknown",
    reason: properties.riskReason ?? "Unavailable",
    eta: properties.eta ?? "",
    weather: hasArrivalWeather
      ? { wind_mph: wind, rain_in_hr: rain, snow_in_hr: snow }
      : null,
  };
  const slider = forecastAtCheckpoint(
    heatmap,
    coordinates?.[1],
    coordinates?.[0],
    hour,
  );
  return {
    arrival,
    slider: {
      ...slider,
      hour,
      time: formatSliderForecastTime(heatmap, hour),
    },
  };
}
