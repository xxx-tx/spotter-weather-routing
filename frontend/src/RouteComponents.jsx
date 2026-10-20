import { useState } from "react";
import { checkpointView } from "./checkpointView";
import {
  explainRecommendation,
  RECOMMENDATION_PRIORITIES,
} from "./recommendationUtils";
import {
  RISK_COLORS,
  RISK_LEVELS,
  ROUTE_COLORS,
  STATUS_LABELS,
  formatDuration,
  formatETA,
  formatMiles,
  riskSegments,
  routeRisk,
} from "./riskUtils";

export function RiskChip({ label, color }) {
  return (
    <span className="risk-chip" style={{ "--chip-color": color }}>
      <span className="risk-chip-dot" aria-hidden="true" />
      {label}
    </span>
  );
}

// Show the miles at each risk level.
export function RiskBar({ route }) {
  const segments = riskSegments(route);
  if (segments.length === 0) return null;

  const description = segments
    .map((segment) => `${segment.level}: ${formatMiles(segment.miles)}`)
    .join(", ");

  return (
    <div
      className="risk-bar"
      role="img"
      aria-label={`Miles by risk level. ${description}`}
      title={description}
    >
      {segments.map((segment) => (
        <span
          key={segment.level}
          className="risk-bar-segment"
          style={{
            width: `${segment.percent}%`,
            backgroundColor: segment.color,
          }}
        />
      ))}
    </div>
  );
}

export function RouteCard({ route, index, isSelected, isFastest, onSelect }) {
  const risk = routeRisk(route);
  const summary = route.risk_summary;

  return (
    <button
      type="button"
      className={`route-card ${isSelected ? "selected" : ""}`}
      onClick={onSelect}
      aria-pressed={isSelected}
    >
      <div className="route-card-header">
        <div className="route-name">
          <span
            className="route-color"
            style={{
              backgroundColor: ROUTE_COLORS[index % ROUTE_COLORS.length],
            }}
          />
          <strong>{route.name}</strong>
        </div>

        <div className="route-badges">
          {route.is_recommended && (
            <span className="recommended-badge">Recommended</span>
          )}
          {isFastest && <span className="fastest-badge">Fastest</span>}
        </div>
      </div>

      <div className="route-card-stats">
        <div className="route-stat">
          <span className="stat-label">Distance</span>
          <strong>{formatMiles(route.distance_miles)}</strong>
        </div>
        <div className="route-stat">
          <span className="stat-label">Travel time</span>
          <strong>{formatDuration(route.duration_seconds)}</strong>
        </div>
      </div>

      <div className="route-card-risk">
        <div className="route-card-risk-top">
          <span className="stat-label">Weather risk</span>
          <RiskChip label={risk.label} color={risk.color} />
        </div>
        <RiskBar route={route} />
        {summary && (
          <div className="route-card-risk-miles">
            <span>Severe {formatMiles(summary.severe_miles)}</span>
            <span>High {formatMiles(summary.high_miles)}</span>
          </div>
        )}
      </div>

      <div className="route-card-footer">
        <span>Arrives {formatETA(route.arrival_time)}</span>
      </div>
    </button>
  );
}

export function RiskSummary({ route, routes, weatherWarning }) {
  const summary = route?.risk_summary;

  if (!summary) {
    return (
      <p className="weather-notice">
        Weather risk data is unavailable for this route.
      </p>
    );
  }

  const verdict = explainRecommendation(route, routes);
  const average = summary.average_risk_score;
  const levelRows = [...RISK_LEVELS, "Unknown"].filter(
    (level) =>
      level !== "Unknown" || (summary.miles_by_level?.Unknown ?? 0) > 0,
  );

  return (
    <section
      className="risk-summary"
      aria-label={`Weather risk for ${route.name}`}
    >
      <div className="risk-summary-head">
        <h3>Weather risk - {route.name}</h3>
        <RiskChip
          label={routeRisk(route).label}
          color={routeRisk(route).color}
        />
      </div>

      {verdict && (
        <div className={`verdict verdict-${verdict.tone}`}>
          <strong>{verdict.title}</strong>
          {verdict.lines.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </div>
      )}

      <details
        className="ranking-explainer"
        aria-label="Route recommendation decision order"
      >
        <summary>
          <strong>How routes are ranked</strong>
          <span>Severe miles → High miles → Average risk → Travel time</span>
        </summary>
        <p>
          Only routes with complete forecasts and no No Travel conditions are
          eligible. Compare in this order; ties move to the next rule.
        </p>
        <ol className="ranking-priorities">
          {RECOMMENDATION_PRIORITIES.map((criterion) => (
            <li key={criterion.key}>
              <strong>{criterion.label}</strong>
              <span>{criterion.detail}</span>
            </li>
          ))}
        </ol>
        <p className="ranking-footnote">
          Weather miles and scores shown here are rounded. The backend uses
          unrounded risk values to choose the route, so very close decisions may
          not be fully explained by the display.
        </p>
      </details>

      {weatherWarning && <p className="weather-warning">{weatherWarning}</p>}

      <dl className="risk-metrics">
        <div>
          <dt>Severe miles</dt>
          <dd>{formatMiles(summary.severe_miles)}</dd>
        </div>
        <div>
          <dt>High miles</dt>
          <dd>{formatMiles(summary.high_miles)}</dd>
        </div>
        <div>
          <dt>Average risk</dt>
          <dd>
            {average == null ? "Unavailable" : `${average.toFixed(2)} of 4`}
          </dd>
        </div>
        <div>
          <dt>Route-mile coverage</dt>
          <dd>{summary.coverage_percent}%</dd>
        </div>
        <div>
          <dt>Checkpoints forecasted</dt>
          <dd>
            {summary.forecasted_checkpoints} / {summary.checkpoint_count}
          </dd>
        </div>
      </dl>

      <p className="risk-status">
        {STATUS_LABELS[summary.status] ?? summary.status}
      </p>

      <ul className="risk-breakdown">
        {levelRows.map((level) => (
          <li key={level}>
            <span className="risk-breakdown-label">
              <span
                className="risk-chip-dot"
                style={{ "--chip-color": RISK_COLORS[level] }}
              />
              {level}
            </span>
            <span>{formatMiles(summary.miles_by_level?.[level] ?? 0)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function CheckpointList({ route }) {
  const checkpoints = route?.checkpoints ?? [];
  // Collapse the list when another route is selected.
  const [expandedRoute, setExpandedRoute] = useState(null);
  const expanded = expandedRoute === route;
  const { items, total, hidden } = checkpointView(checkpoints, expanded);

  return (
    <section
      className="checkpoints-panel"
      aria-label={`Weather checkpoints for ${route?.name}`}
    >
      <h3>Weather checkpoints - {route?.name}</h3>
      <p className="checkpoints-description">
        {total} checkpoints. Weather is forecast for the hour the truck is
        expected to reach each one. Click a dot on the map for details.
      </p>

      {total > items.length && (
        <p className="checkpoint-preview-count">
          Showing the first {items.length} of {total} checkpoints ({hidden}{" "}
          more).
        </p>
      )}
      <ol
        className={`checkpoint-list ${expanded ? "checkpoint-list-expanded" : ""}`}
      >
        {items.map((checkpoint) => {
          const level = checkpoint.risk?.level ?? "Unknown";
          const weather = checkpoint.weather;

          return (
            <li className="checkpoint-item" key={checkpoint.id}>
              <div className="checkpoint-top">
                <strong>Mile {checkpoint.mile}</strong>
                <RiskChip
                  label={level}
                  color={RISK_COLORS[level] ?? RISK_COLORS.Unknown}
                />
              </div>
              <span className="checkpoint-eta">
                {formatETA(checkpoint.eta)}
              </span>

              {weather ? (
                <div className="checkpoint-weather">
                  <span>Wind {weather.wind_mph.toFixed(1)} mph</span>
                  <span>Rain {weather.rain_in_hr.toFixed(2)} in/hr</span>
                  <span>Snow {weather.snow_in_hr.toFixed(2)} in/hr</span>
                </div>
              ) : (
                <div className="checkpoint-unavailable">
                  Forecast unavailable
                </div>
              )}

              {checkpoint.risk?.reason &&
                level !== "Low" &&
                level !== "Unknown" && (
                  <span className="checkpoint-reason">
                    Driven by {checkpoint.risk.reason.toLowerCase()}
                  </span>
                )}
            </li>
          );
        })}
      </ol>
      {total > 5 && (
        <button
          type="button"
          className="checkpoint-expand-button"
          aria-expanded={expanded}
          onClick={() => setExpandedRoute(expanded ? null : route)}
        >
          {expanded
            ? "Show fewer checkpoints"
            : `Show all ${total} checkpoints`}
        </button>
      )}
    </section>
  );
}
