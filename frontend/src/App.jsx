import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { CheckpointList, RiskSummary, RouteCard } from "./RouteComponents";
import { deviceTimeZoneLabel } from "./riskUtils";
import {
  apiEndpoint,
  fetchTripRoutes,
  makeTripPayload,
  recommendedOrFirstId,
  validateTrip,
} from "./tripRequest";
import "./App.css";

// Load the map only when React needs it.
const RouteMap = lazy(() => import("./RouteMap.jsx"));

const API_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api";

// Start with tomorrow morning; the driver should use the origin's time zone.
function defaultDepartureTime() {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  date.setHours(9, 0, 0, 0);
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T09:00`;
}

export default function App() {
  const [backendStatus, setBackendStatus] = useState("Checking...");

  const [form, setForm] = useState({
    origin: "Phoenix, AZ",
    destination: "Denver, CO",
    departure_time: defaultDepartureTime(),
    load_weight_lb: 35000,
    checkpoint_miles: 50,
  });

  const [tripResult, setTripResult] = useState(null);
  const [routes, setRoutes] = useState([]);
  const [selectedRouteId, setSelectedRouteId] = useState(0);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const activeRequest = useRef(null);
  const requestVersion = useRef(0);

  // Cancel any request when leaving the page.
  useEffect(
    () => () => {
      requestVersion.current += 1;
      activeRequest.current?.abort();
    },
    [],
  );

  useEffect(() => {
    const controller = new AbortController();

    async function checkBackend() {
      try {
        const response = await fetch(apiEndpoint(API_URL, "health/"), {
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error("Backend unavailable");
        }

        setBackendStatus("Connected");
      } catch (err) {
        if (err.name !== "AbortError") {
          setBackendStatus("Disconnected");
        }
      }
    }

    checkBackend();

    return () => controller.abort();
  }, []);

  function handleChange(event) {
    const { name, value } = event.target;

    setForm((previous) => ({
      ...previous,
      [name]: value,
    }));
  }

  function cancelSearch() {
    requestVersion.current += 1;
    activeRequest.current?.abort();
    activeRequest.current = null;
    setLoading(false);
    setError("");
  }

  // Ignore responses from old or cancelled requests.
  async function handleSubmit(event) {
    event.preventDefault();
    if (loading) return;

    const validationError = validateTrip(form);
    if (validationError) {
      setError(validationError);
      return;
    }

    const version = ++requestVersion.current;
    const controller = new AbortController();
    activeRequest.current = controller;
    setLoading(true);
    setError("");
    setRoutes([]);
    setTripResult(null);

    try {
      const data = await fetchTripRoutes(API_URL, makeTripPayload(form), {
        signal: controller.signal,
      });
      if (version !== requestVersion.current || controller.signal.aborted)
        return;
      setRoutes(data.routes);
      setTripResult(data);
      setSelectedRouteId(
        recommendedOrFirstId(data.routes, data.recommended_route_id),
      );
    } catch (err) {
      if (version !== requestVersion.current || controller.signal.aborted)
        return;
      setError(err instanceof Error ? err.message : "Unable to find routes.");
    } finally {
      if (version === requestVersion.current) {
        activeRequest.current = null;
        setLoading(false);
      }
    }
  }

  const selectedRoute = routes.find((route) => route.id === selectedRouteId);
  const fastestRouteId = routes.reduce(
    (fastest, route) =>
      fastest == null || route.duration_seconds < fastest.duration_seconds
        ? route
        : fastest,
    null,
  )?.id;

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-content">
          <div className="logo">
            <span className="logo-icon">🚛</span>

            <div>
              <h1>Spotter Route Planner</h1>
              <p>Weather-Aware Truck Routing</p>
            </div>
          </div>

          <div
            className={`backend-status ${
              backendStatus === "Connected" ? "connected" : ""
            }`}
          >
            <span className="status-dot" />
            Backend: {backendStatus}
          </div>
        </div>
      </header>

      <main className="app-container">
        <aside className="sidebar">
          <section className="form-card">
            <h2>Plan Your Trip</h2>

            <p className="form-description">
              Compare routes using hourly weather forecasts. Check official road
              alerts before you drive; forecasts are not a safety guarantee.
            </p>

            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label htmlFor="origin">Origin</label>

                <input
                  id="origin"
                  name="origin"
                  type="text"
                  placeholder="Phoenix, AZ"
                  value={form.origin}
                  onChange={handleChange}
                  disabled={loading}
                  required
                />
              </div>

              <div className="form-group">
                <label htmlFor="destination">Destination</label>

                <input
                  id="destination"
                  name="destination"
                  type="text"
                  placeholder="Denver, CO"
                  value={form.destination}
                  onChange={handleChange}
                  disabled={loading}
                  required
                />
              </div>

              <div className="form-group">
                <label htmlFor="departure_time">Departure Date & Time</label>

                <input
                  id="departure_time"
                  name="departure_time"
                  type="datetime-local"
                  value={form.departure_time}
                  onChange={handleChange}
                  disabled={loading}
                  required
                />

                <small>
                  Enter the date and time in the origin's local time zone, not
                  your computer's time zone.
                </small>
              </div>

              <div className="form-group">
                <label htmlFor="load_weight_lb">Load Weight (lb)</label>

                <input
                  id="load_weight_lb"
                  name="load_weight_lb"
                  type="number"
                  placeholder="35000"
                  min="1"
                  step="1"
                  value={form.load_weight_lb}
                  onChange={handleChange}
                  disabled={loading}
                  required
                />
              </div>

              <div className="form-group">
                <label htmlFor="checkpoint_miles">
                  Weather Checkpoint Spacing
                </label>

                <select
                  id="checkpoint_miles"
                  name="checkpoint_miles"
                  value={form.checkpoint_miles}
                  onChange={handleChange}
                  disabled={loading}
                >
                  <option value="10">Every 10 miles</option>
                  <option value="25">Every 25 miles</option>
                  <option value="50">Every 50 miles</option>
                </select>

                <small>
                  Shorter spacing provides more weather checkpoints.
                </small>
              </div>

              <button
                className="submit-button"
                type="submit"
                disabled={loading}
              >
                {loading ? "Finding Routes..." : "Find Truck Routes"}
              </button>
              {loading && (
                <button
                  type="button"
                  className="cancel-button"
                  onClick={cancelSearch}
                >
                  Cancel search
                </button>
              )}
            </form>

            {error && (
              <div className="error-message" role="alert">
                <strong>Unable to calculate routes</strong>
                <p>{error}</p>
              </div>
            )}

            {/* TomTom may return fewer than three routes. */}
            {tripResult?.route_warning && (
              <p className="route-warning" role="status">
                {tripResult.route_warning}
              </p>
            )}

            {tripResult && (
              <div className="trip-summary">
                <h3>Trip Details</h3>

                <div className="summary-row">
                  <span>Origin</span>
                  <strong>{tripResult.origin.name}</strong>
                </div>

                <div className="summary-row">
                  <span>Destination</span>
                  <strong>{tripResult.destination.name}</strong>
                </div>

                <div className="summary-row">
                  <span>Load Weight</span>
                  <strong>
                    {Number(tripResult.trip.load_weight_lb).toLocaleString()} lb
                  </strong>
                </div>

                <div className="summary-row">
                  <span>Routes Found</span>
                  <strong>{routes.length}</strong>
                </div>
              </div>
            )}
          </section>
        </aside>

        <section className="main-content">
          <div className="map-card">
            <div className="section-header">
              <div>
                <h2>Truck Route Map</h2>
                <p>Explore available routes for your trip</p>
              </div>

              {routes.length > 0 && (
                <span className="route-count">
                  {routes.length} Route{routes.length !== 1 ? "s" : ""}
                </span>
              )}
            </div>

            <div className="map-wrapper">
              <Suspense
                fallback={
                  <div
                    className="map-module-loading"
                    role="status"
                    aria-live="polite"
                  >
                    <span className="spinner" aria-hidden="true" />
                    <span>Loading interactive map…</span>
                  </div>
                }
              >
                <RouteMap
                  routes={routes}
                  selectedRouteId={selectedRouteId}
                  heatmap={tripResult?.heatmap}
                />
              </Suspense>

              {loading && (
                <div className="map-loading" role="status" aria-live="polite">
                  <div className="map-loading-content">
                    <span className="spinner" aria-hidden="true" />
                    <strong>Comparing truck routes</strong>
                    <span>
                      Checking weather at the estimated arrival time of each
                      checkpoint. This can take a few moments.
                    </span>
                    <button
                      type="button"
                      className="map-cancel-button"
                      onClick={cancelSearch}
                    >
                      Cancel search
                    </button>
                  </div>
                </div>
              )}
            </div>

            {routes.length === 0 && !loading && (
              <p className="map-hint">
                Enter your trip information and click "Find Truck Routes" to
                display routes.
              </p>
            )}
          </div>

          {routes.length > 0 && (
            <section className="routes-section">
              <div className="section-header">
                <div>
                  <h2>Available Routes</h2>
                  <p>Select a route to highlight it on the map.</p>
                  <p className="time-zone-notice">
                    {deviceTimeZoneLabel()}. Arrival and checkpoint times use
                    your device's time zone; the departure you entered is in the
                    origin's local time.
                  </p>
                </div>
              </div>

              <div className="route-list">
                {routes.map((route, index) => (
                  <RouteCard
                    key={route.id}
                    route={route}
                    index={index}
                    isSelected={selectedRouteId === route.id}
                    isFastest={route.id === fastestRouteId}
                    onSelect={() => setSelectedRouteId(route.id)}
                  />
                ))}
              </div>

              {selectedRoute && (
                <div className="route-details">
                  <RiskSummary
                    route={selectedRoute}
                    routes={routes}
                    weatherWarning={tripResult?.weather_warning}
                  />
                  <CheckpointList route={selectedRoute} />
                </div>
              )}
            </section>
          )}
        </section>
      </main>
    </div>
  );
}
