# Spotter Weather-Aware Truck Routing

A full-stack assessment app that compares truck routes by weather risk, load weight, and travel time. Weather is evaluated at each checkpoint's estimated arrival time.

**[Live application](https://spotter-weather-routing-sigma.vercel.app/)** · **[Backend health check](https://spotter-weather-routing-s9ez.onrender.com/api/health/)**

> **Demo only:** This is not a certified trucking navigation or safety system. Check official forecasts, road closures, and truck restrictions before driving.

## Reviewer quick start — waking the backend

The Django API uses **Render Free**, which can spin down after approximately 15 minutes without requests. The first request after inactivity can take **50 seconds or more**. The frontend may load before the backend is ready.

1. Open the **[backend health check](https://spotter-weather-routing-s9ez.onrender.com/api/health/)**.
2. Wait up to about **1–2 minutes** for a JSON response containing `"status": "ok"`.
3. Open the **[live application](https://spotter-weather-routing-sigma.vercel.app/)**.
4. If the app still says **Backend: Disconnected**, refresh it once; the current UI checks connection status on page load.
5. Generate a route. Avoid repeatedly submitting while the backend is still waking up.

**No Render login or manual redeploy is needed** to wake the service. If the health URL stays unavailable after two minutes, it may be a deployment or provider issue rather than a cold start. The health endpoint confirms Django is available, **not** that weather and routing APIs are healthy.

## Try a trip

| Input              | Suggested value                                   |
| ------------------ | ------------------------------------------------- |
| Origin             | Phoenix, AZ                                       |
| Destination        | Denver, CO                                        |
| Departure          | Tomorrow, 9:00 AM in the origin's local time zone |
| Load               | 35,000 lb                                         |
| Checkpoint spacing | 50 miles                                          |

Generate routes, compare their risk summaries, select an alternative on the map, inspect checkpoints and estimated arrival times, and move the **0–48-hour forecast slider**. Up to three real route alternatives are shown when TomTom supplies enough usable options.

## Features

- TomTom geocoding and routing candidates.
- Weather checkpoints spaced every 10, 25, or 50 miles.
- Hourly wind, rain, and snow forecasts evaluated at checkpoint arrival times.
- Wind-risk adjustments based on load weight.
- Route ranking by **fewest Severe miles → fewest High miles → lowest average risk → shortest travel time**.
- Interactive MapLibre map with route lines, checkpoints, ETAs, and a 0–48-hour weather corridor view.
- **Missing weather remains Unknown**, never Low; incomplete routes are not recommended.

## Architecture

```text
Browser
   |
React + Vite + MapLibre (Vercel)
   |
Django REST API (Render)
   |-- TomTom: geocoding and routing
   |
   +-- Cloudflare Worker: authenticated weather gateway
                 |
             Open-Meteo: hourly forecasts
```

The hosted demo uses a Cloudflare Worker for weather requests because calls from Render to the free Open-Meteo endpoint returned HTTP 429. The Worker validates supported request parameters and requires a backend-only bearer token. Provider rate limits can still occur. Django performs the route scoring and recommendations. **The separate Worker's source is not included in this repository.**

## Run locally

**Requirements:** Python compatible with the pinned Django version (Python 3.12+), Node.js compatible with Vite (Node.js 22+), a TomTom API key, and network access to third-party services.

### Django backend — Windows PowerShell

From the repository root:

```powershell
cd backend
py -m venv .venv
Copy-Item .env.example .env
# Edit .env and set your own TOMTOM_API_KEY and DJANGO_SECRET_KEY
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

The default `.env.example` configures local debug and localhost CORS. For macOS/Linux, activate the Python environment with `source .venv/bin/activate` and run the Django commands with `python`.

### React frontend — second terminal

```powershell
cd frontend
npm ci
Copy-Item .env.example .env
npm run dev
```

The local frontend `.env` contains:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api
```

Open http://127.0.0.1:5173/. Enter the departure time in the **origin's local time zone**; the displayed times are formatted in your device's time zone.

### Weather endpoint options

Without `WEATHER_PROXY_URL`, Django calls Open-Meteo directly. To use the hosted gateway, set these in **backend environment only**:

| Variable              | Purpose                                        |
| --------------------- | ---------------------------------------------- |
| `WEATHER_PROXY_URL`   | HTTPS Worker URL ending in `/forecast`         |
| `WEATHER_PROXY_TOKEN` | Bearer token matching the secret in Cloudflare |

Do not put the token or TomTom key in frontend `VITE_` variables or in Git.

## Deployment

### Render — backend

- **Root directory:** `backend`
- **Build command:** `pip install -r requirements.txt`
- **Start command:**

```bash
python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 1 --timeout 120
```

Environment variables:

| Name                            | Setting                                            |
| ------------------------------- | -------------------------------------------------- |
| `DJANGO_DEBUG`                  | `false`                                            |
| `DJANGO_SECRET_KEY`             | Private random key                                 |
| `DJANGO_ALLOWED_HOSTS`          | `spotter-weather-routing-s9ez.onrender.com`        |
| `CORS_ALLOWED_ORIGINS`          | `https://spotter-weather-routing-sigma.vercel.app` |
| `TOMTOM_API_KEY`                | Private TomTom key                                 |
| `WEATHER_PROXY_URL`             | Your Worker URL with `/forecast`                   |
| `WEATHER_PROXY_TOKEN`           | Private Worker bearer token                        |
| `DJANGO_TRUST_PROXY_SSL_HEADER` | `true` when the trusted Render proxy is configured |

**Important:** The CORS origin must have **no trailing slash**. `DJANGO_ALLOWED_HOSTS` must be the hostname **without `https://`**. Route throttling can be configured using `ROUTES_RATE_PER_MINUTE`, `ROUTES_RATE_PER_DAY`, and `DRF_NUM_PROXIES`.

### Vercel — frontend

- **Root directory:** `frontend`
- **Framework:** Vite
- **Install:** `npm ci`
- **Build:** `npm run build`
- **Output directory:** `dist`
- **Environment:**

```env
VITE_API_BASE_URL=https://spotter-weather-routing-s9ez.onrender.com/api
```

Only the public URL is exposed to the browser. Keep API keys and tokens server-side.

### Cloudflare Worker — weather gateway

Configure the Worker separately with a private `WEATHER_PROXY_TOKEN` secret. Set the same token and the Worker `/forecast` URL in Render. The gateway restricts requests to the forecast fields this app uses. The Worker implementation must be deployed separately; it is not part of this repository.

## API

| Method | Endpoint               | Purpose                                            |
| ------ | ---------------------- | -------------------------------------------------- |
| GET    | `/api/health/`         | Django availability                                |
| POST   | `/api/trips/validate/` | Validate trip input                                |
| POST   | `/api/routes/`         | Return routes, risk, forecasts, and recommendation |

Example route request (use a valid future departure date):

```json
{
  "origin": "Phoenix, AZ",
  "destination": "Denver, CO",
  "departure_time": "2026-10-21T09:00",
  "load_weight_lb": 35000,
  "checkpoint_miles": 50
}
```

### Weather and risk notes

Wind uses the higher of hourly wind readings around the checkpoint's arrival time. Rain and snow use hourly amounts ending at the following whole hour. The 0–48-hour slider is a separate forecast view; it does not alter the original arrival-time route ranking. Risk comparisons use full-precision values.

Wind rules include **No Travel at 55+ mph for any load**, **No Travel at 45–54 mph for loads above 30,000 lb**, and **Severe at 35–44 mph for loads above 40,000 lb**.

## Tests

From `backend/` after installing development dependencies:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests scripts/test_smoke_live.py
.\.venv\Scripts\python.exe manage.py check
```

From `frontend/`:

```bash
npm test
npm run lint
npm run build
```

Unit tests with synthetic responses do not prove live third-party services will be available.

## Known limitations

- Render Free may need roughly a minute or longer to wake after inactivity.
- Django's health check is not a TomTom or Open-Meteo availability check.
- External APIs can rate-limit or fail; missing forecasts remain Unknown.
- The app displays fewer than three routes when the routing provider has too few usable alternatives.
- Forecasts are hourly approximations and cannot guarantee safe roads.
- SQLite files on Render Free's ephemeral filesystem are not a persistent production datastore.
- Django processes route planning synchronously and enforces workload/request limits.
- The current React backend-status indicator checks at page load, so a refresh may be needed after waking Render.
- This is a demonstration, not a production dispatch system or a source of official road warnings.

## Code layout

| File                                  | Responsibility                        |
| ------------------------------------- | ------------------------------------- |
| `backend/routing/services.py`         | TomTom routing and route parsing      |
| `backend/routing/checkpoints.py`      | Checkpoint distances and ETAs         |
| `backend/routing/weather_readings.py` | Hourly forecasts at arrival times     |
| `backend/routing/weather.py`          | Forecast batching and slider data     |
| `backend/routing/risk.py`             | Risk classification and route ranking |
| `backend/routing/views.py`            | REST endpoints and input limits       |
| `frontend/src/RouteMap.jsx`           | Map, routes, checkpoints, slider      |
| `frontend/src/corridorUtils.js`       | Weather corridor geometry             |
| `frontend/src/tripRequest.js`         | Request and response validation       |

## Assessment deliverables

- **Code:** this GitHub repository
- **Hosted demo:** https://spotter-weather-routing-sigma.vercel.app/
- **Loom walkthrough:** pending recording

Only commit `.env.example` templates. Never commit `.env` files, secret keys, virtual environments, or `node_modules`.
