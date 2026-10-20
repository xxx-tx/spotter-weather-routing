# Weather-Aware Truck Routing

React + Django demo for comparing truck routes using forecasts at each checkpoint's arrival time.

The server gets routes from TomTom and hourly weather from Open-Meteo. The UI shows up to three route options, risks, checkpoint ETAs, and a 0–48 hour map forecast slider.

> **Important:** This is an assessment demo, not a navigation or dispatch safety system. Always check official weather warnings and road closures. Load weight affects the assessment's wind-risk rules; it does not tell TomTom the vehicle's dimensions or legal gross vehicle weight.

## Requirements

- Python 3.12 or later (Django 6.1 requires a supported Python version).
- Node.js 22 or later.
- A TomTom API key with routing and geocoding permissions.
- Internet access for TomTom, Open-Meteo, and map tiles.

## Run locally

**Backend** (in a terminal, from `backend/`):

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env  # Windows: Copy-Item .env.example .env
# Put your real TOMTOM_API_KEY and a local DJANGO_SECRET_KEY in .env
python manage.py migrate
python manage.py runserver
```

**Frontend** (in another terminal, from `frontend/`):

```bash
npm ci
cp .env.example .env  # Windows: Copy-Item .env.example .env
npm run dev
```

Open `http://127.0.0.1:5173`.

Use a departure time **in the origin's local time zone**. The date/time input intentionally has no time-zone offset; TomTom resolves the origin's offset. Times shown after routing are formatted in your device's time zone.

## Tests

```bash
# From project root, with backend dependencies installed:
PYTHONPATH=backend python -m pytest -q backend/tests backend/scripts/test_smoke_live.py

# From frontend/:
npm test
npm run lint
npm run build
```

For Windows PowerShell, set `$env:PYTHONPATH='backend'` before running pytest.

The Python unit tests use synthetic provider data and do not spend API quota. `smoke_live.py` is separate and contacts services only when run explicitly with the appropriate server URL.

## API

- `GET /api/health/`: backend availability only (not a check of external providers).
- `POST /api/validate/`: validate trip form inputs.
- `POST /api/routes/`: calculate routes, forecasts, risks, and a recommendation.

Example JSON:

```json
{
  "origin": "Phoenix, AZ",
  "destination": "Denver, CO",
  "departure_time": "2026-10-21T09:00",
  "load_weight_lb": 35000,
  "checkpoint_miles": 50
}
```

The backend checks 6 possible routing candidates and displays at most 3. If TomTom has fewer usable routes, the app shows fewer rather than inventing roads. Forecasts outside the available window stay Unknown. A route with any unknown checkpoint cannot be recommended.

### Weather sampling

- Wind: use the higher of the hourly readings either side of ETA. This is deliberately cautious for an assessment app.
- Rain and snow: use the hourly accumulation ending at the next whole hour.
- If a needed sample is missing, leave the checkpoint's weather unknown.
- Risk checks use full-precision readings; the UI rounds numbers only for display.
- The slider starts at the next whole UTC hour, independently of route arrival-time risk.

### Limits

The synchronous endpoint accepts a maximum of 400 checkpoints across candidate routes. For a long trip, try 25- or 50-mile spacing. It also uses per-IP request throttling (6/minute and 80/day by default). Throttling alone cannot prevent every kind of abuse or API spending. The default IP identification ignores untrusted `X-Forwarded-For` headers (`DRF_NUM_PROXIES=0`); if you deploy behind proxies, configure your trusted proxy chain carefully.

## Deploying

1. Set `DJANGO_DEBUG=false`, a strong `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `TOMTOM_API_KEY`, and `CORS_ALLOWED_ORIGINS` on the **server**. Never put the TomTom key in `VITE_` variables.
2. Configure TLS and trusted proxy headers for your hosting setup. Run `python manage.py check --deploy` and `python manage.py migrate`.
3. Start Django with `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT` from `backend/` (Linux hosts). Collect and serve Django static assets separately if using admin.
4. Run `npm ci && npm run build` in `frontend/`, host `dist/` as static assets, and set `VITE_API_BASE_URL` to your HTTPS backend `/api` URL before building.
5. **Production throttle warning:** Django's local-memory cache is per process. Use a shared cache (such as Redis) for rate limits on multiple workers/instances, and enforce provider quotas and billing alerts. A full job queue and shared caching are outside this assessment.
6. Test one short and one long trip on the deployed URL and review the browser console and Django logs.

Only use `.env.example` files in source control or a submitted ZIP. Store actual secrets in your host's secret manager. If an API key was included in a previously shared archive, rotate it.

## Project layout

- `backend/routing/services.py` — TomTom requests and route parsing.
- `backend/routing/checkpoints.py` — route positions and checkpoint ETAs.
- `backend/routing/weather_readings.py` — hourly weather and ETA time matching.
- `backend/routing/weather.py` — forecast batches and the map timeline.
- `backend/routing/risk.py` — risk rules and route selection.
- `backend/routing/views.py` — API response and workload limits.
- `frontend/src/RouteMap.jsx` — MapLibre routes, checkpoints, and slider.
- `frontend/src/corridorUtils.js` — map corridor segments.
- `frontend/src/tripRequest.js` — form and response validation.
