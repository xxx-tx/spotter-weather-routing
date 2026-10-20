// Presentation only: Django's full-precision ranking is authoritative.
// Public route summaries contain rounded values, which can hide very small
// differences in earlier criteria. Never recompute or override the backend pick.

export const RECOMMENDATION_PRIORITIES = [
  {
    key: "severe_miles",
    label: "Severe miles",
    detail: "Fewest miles with Severe conditions",
  },
  {
    key: "high_miles",
    label: "High miles",
    detail: "Fewest miles with High conditions",
  },
  {
    key: "average_risk_score",
    label: "Average risk",
    detail: "Lowest distance-weighted weather risk",
  },
  {
    key: "duration_seconds",
    label: "Travel time",
    detail: "Shortest travel time",
  },
];

const validNumber = (value) =>
  typeof value === "number" && Number.isFinite(value);

const rawValue = (route, key) =>
  key === "duration_seconds"
    ? route?.duration_seconds
    : route?.risk_summary?.[key];

function formatValue(key, value) {
  if (!validNumber(value)) return "unavailable";
  if (key === "duration_seconds") {
    const minutes = value / 60;
    return `${minutes.toFixed(2).replace(/\.?0+$/, "")} min`;
  }
  if (key === "average_risk_score") return value.toFixed(2);
  return `${value.toFixed(1)} mi`;
}

// Match the presentation precision in RiskSummary (not the backend rank key).
function displayedValue(key, value) {
  if (!validNumber(value)) return null;
  if (key === "duration_seconds") return value;
  return Number(value.toFixed(key === "average_risk_score" ? 2 : 1));
}

/** First difference visible in the public route summary, not necessarily the
 *  backend's true first difference (which may be below rounding precision). */
export function firstVisibleDifference(winner, other) {
  for (const criterion of RECOMMENDATION_PRIORITIES) {
    const a = rawValue(winner, criterion.key);
    const b = rawValue(other, criterion.key);
    if (!validNumber(a) || !validNumber(b)) return null;
    const visibleA = displayedValue(criterion.key, a);
    const visibleB = displayedValue(criterion.key, b);
    if (visibleA !== visibleB) {
      return {
        key: criterion.key,
        criterion: criterion.label,
        direction: visibleA < visibleB ? "better" : "worse",
        winnerValue: formatValue(criterion.key, visibleA),
        otherValue: formatValue(criterion.key, visibleB),
      };
    }
  }
  return null;
}

function hasAllRankingValues(route) {
  return RECOMMENDATION_PRIORITIES.every((item) =>
    validNumber(rawValue(route, item.key)),
  );
}

// Use driver-friendly units; never round a real 20-second advantage to "0 min".
export function describeTimeSaved(seconds) {
  if (!validNumber(seconds) || seconds <= 0) return null;
  if (seconds < 1) return "less than a second";
  if (seconds < 60) {
    const rounded = Math.max(1, Math.round(seconds));
    return `about ${rounded} second${rounded === 1 ? "" : "s"}`;
  }
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `about ${minutes} minute${minutes === 1 ? "" : "s"}`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  const hoursText = `${hours} hour${hours === 1 ? "" : "s"}`;
  if (remainder === 0) return `about ${hoursText}`;
  return `about ${hoursText} ${remainder} minute${remainder === 1 ? "" : "s"}`;
}

function distanceDifference(a, b) {
  // The UI shows weather-risk mileage to one decimal place.
  const delta =
    Math.round(
      (displayedValue("severe_miles", b) - displayedValue("severe_miles", a)) *
        10,
    ) / 10;
  return delta.toLocaleString("en-US", { maximumFractionDigits: 1 });
}

function displayedComparison(winner, other) {
  const diff = firstVisibleDifference(winner, other);
  if (!diff) {
    if (!hasAllRankingValues(winner) || !hasAllRankingValues(other)) {
      return `The available figures cannot show why ${winner.name} ranks ahead of ${other.name}.`;
    }
    return `${winner.name} and ${other.name} appear tied in the displayed figures. The backend may distinguish them using more precise risk data.`;
  }
  if (diff.direction === "worse") {
    return `The rounded figures cannot explain why ${winner.name} ranks ahead of ${other.name}; the backend uses more precise risk values.`;
  }

  if (diff.key === "duration_seconds") {
    const saved = describeTimeSaved(
      rawValue(other, "duration_seconds") -
        rawValue(winner, "duration_seconds"),
    );
    return `Displayed weather-risk figures match. ${winner.name} is ${saved} faster than ${other.name}.`;
  }

  if (diff.key === "average_risk_score") {
    return `In the displayed figures, ${winner.name} has a lower average weather-risk score than ${other.name} (${diff.winnerValue} vs ${diff.otherValue}).`;
  }

  const label = diff.key === "severe_miles" ? "Severe-risk" : "High-risk";
  const a = rawValue(winner, diff.key);
  const b = rawValue(other, diff.key);
  const delta = distanceDifference(a, b);
  return `In the displayed figures, ${winner.name} has ${delta} fewer ${label} miles than ${other.name}.`;
}

function countConfirmedNoTravel(route) {
  return (route.checkpoints ?? []).filter(
    (cp) => cp.risk?.level === "No Travel",
  ).length;
}

const eligible = (route) => route?.risk_summary?.status === "eligible";

export function explainRecommendation(selected, routes = []) {
  if (!selected?.risk_summary) return null;

  const status = selected.risk_summary.status;
  const recommended = routes.find(
    (route) => route.is_recommended && eligible(route),
  );
  const eligibleAlternatives = routes.filter(
    (route) => route.id !== selected.id && eligible(route),
  );
  const noEligible = !routes.some(eligible);

  if (status === "no_travel") {
    const count = countConfirmedNoTravel(selected);
    return {
      title: "Not eligible — No Travel conditions",
      tone: "bad",
      lines: [
        count > 0
          ? `The forecast indicates No Travel conditions at ${count} checkpoint${count === 1 ? "" : "s"} for this load.`
          : "The forecast indicates a No Travel condition for this load.",
        noEligible
          ? "No displayed route is eligible for a recommendation."
          : "Routes with confirmed No Travel conditions are excluded from the recommendation.",
      ],
    };
  }

  if (status === "incomplete") {
    const coverage = selected.risk_summary.coverage_percent;
    const coverageText = validNumber(coverage)
      ? ` (${coverage}% distance coverage)`
      : "";
    return {
      title: "Not eligible — Forecast incomplete",
      tone: "warn",
      lines: [
        `Weather could not be verified for the entire route${coverageText}. Missing or incomplete conditions are not assumed safe.`,
        noEligible
          ? "No displayed route is eligible for a recommendation."
          : "Only routes with complete weather coverage and no No Travel conditions can be recommended.",
      ],
    };
  }

  if (status !== "eligible") return null;

  if (selected.is_recommended) {
    return {
      title: "Recommended route",
      tone: "good",
      lines: eligibleAlternatives.length
        ? eligibleAlternatives.map((other) =>
            displayedComparison(selected, other),
          )
        : [
            "This is the only displayed route with complete forecasts and no No Travel conditions.",
          ],
    };
  }

  if (recommended) {
    return {
      title: "Not the recommended route",
      tone: "neutral",
      lines: [displayedComparison(recommended, selected)],
    };
  }

  return {
    title: "No recommendation available",
    tone: "warn",
    lines: [
      "The API did not identify a recommended route; these figures are for comparison only.",
    ],
  };
}
