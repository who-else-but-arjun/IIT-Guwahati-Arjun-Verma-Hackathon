# CRISIL Financial NLP

Live S&P 100 financial-news analysis and paper portfolio dashboard. The stack uses Django, MongoDB, Redis, and React. Portfolio trades are simulated; no broker is connected.

## Start the complete app

Requirements: Docker Desktop with Compose, and a Finnhub key for company-news polling. Alpaca news needs Alpaca credentials; Bluesky and yfinance need no key.

1. Copy `.env.example` to `.env` and add the provider keys you have. Full event analysis requires the published FLANG-RoBERTa and Laya model artifacts to be reachable through KaggleHub. `OPENCODE_API_KEY` enables Jev category/impact analysis; when Jev is unavailable, the local Laya model handles those outputs. If required model artifacts are unavailable, news is saved and the analysis worker retries it with backoff until the issue is resolved.
2. From this folder, run:

   ```powershell
   .\scripts\start.ps1
   ```

   Or on any platform: `docker compose up --build -d`. Open <http://localhost:5173>. The APIs are at <http://localhost:8000> and <http://localhost:8001/api/trading/>. MongoDB is at `mongodb://localhost:27018/financial_nlp`.

Compose starts the API, frontend, trading engine and event socket, MongoDB, Redis, Alpaca and Bluesky streams, Finnhub poller, and persistent news-analysis worker. The workers reconnect/restart with the stack. News providers and model analysis require their respective credentials, access, and network availability.

## Data, startup catch-up, and portability

`data/seed/financial_nlp.archive.gz` is the portable MongoDB snapshot, including ticker/news data, paper portfolios, rebalance and order history, and portfolio value history. Mongo restores it automatically the first time it creates an empty `mongo_data` volume. The snapshot includes two comparison portfolios and gives new devices the same starting dashboard. Existing Mongo volumes are preserved. MongoDB and Redis data persist across `docker compose down`; `docker compose down -v` deletes those local volumes.

When the trading service starts, it resumes each saved portfolio from its last completed market session, replays missing daily bars and saved analyzed news, records resulting trades/value points, executes due rebalances once market opens are available, and refreshes live marks. New analyzed news flows through the trading socket to the active news portfolio. Finnhub polls every 15 minutes; the two public news streams remain connected while the stack runs. Market history and open prices use Yahoo Finance and can be delayed or unavailable.

To carry a newer database state to another device, update the snapshot on the source device while the stack is running and include the resulting file when sharing the project:

```powershell
python .\scripts\backup_database.py
```

The destination restores that snapshot only if its Mongo volume is new. If it has already started, stop the stack, remove only its empty/replaceable Mongo volume with `docker compose down -v`, then start again. That command also removes Redis state.

## Check and stop

```powershell
docker compose ps
docker compose logs -f trading news-analysis-worker finnhub-poller alpaca-news bluesky-news
docker compose down
```

Health endpoints: <http://localhost:8000/api/health/> and <http://localhost:8001/api/trading/health/>. Do not run `down -v` if you need to keep the machine's MongoDB state.

## Production deployment

The production stack is in `docker-compose.production.yml`. It runs MongoDB, Redis, the two Gunicorn APIs, the trading engine, the Alpaca and Bluesky news listeners, the Finnhub poller, the persistent news-analysis worker, and Caddy. The React/Vite frontend is deployed separately to Cloudflare Pages.

The MongoDB seed archive at `data/seed/financial_nlp.archive.gz` is mounted into the Mongo container and restored automatically when MongoDB initializes a new empty data volume. This gives a new hosted instance its initial tickers, news events, portfolios, and paper-trading history. Existing Mongo volumes are preserved on restart and redeploy; never run `docker compose down -v` on a database you need to retain.

For an Oracle VM deployment:

1. Clone this repository on the VM and create a server-side `.env` from `.env.example`. Set `DJANGO_SECRET_KEY`, `API_HOSTNAME`, `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS`. Add `FINNHUB_API_KEY` and both Alpaca credentials to run those poller/listener services. Keep `.env` off GitHub.
2. Point the API hostname at the VM and allow only SSH (restricted to your address), HTTP, and HTTPS through the cloud and host firewalls. Do not publish MongoDB, Redis, or the Django ports.
3. Build and start the production stack from this folder:

   ```sh
   docker compose -f docker-compose.production.yml up -d --build
   ```

4. In Cloudflare Pages, connect this repository with root directory `src/frontend`, build command `npm run build`, and output directory `dist`. Set `VITE_API_URL` and `VITE_TRADING_API_URL` to `https://YOUR_API_HOSTNAME`, then redeploy the site.
5. Confirm the seed restore and service health:

   ```sh
   docker compose -f docker-compose.production.yml ps
   docker compose -f docker-compose.production.yml exec mongo mongosh financial_nlp --quiet --eval 'db.getCollectionNames()'
   docker compose -f docker-compose.production.yml logs --tail=100 trading news-analysis-worker finnhub-poller alpaca-news bluesky-news
   ```

The services restart automatically after process or VM restarts. Finnhub polling and Alpaca streaming require valid provider credentials; Bluesky does not. News analysis keeps retrying pending articles, but successful processing requires the model artifacts to download and load. An API health response confirms the API/database connection; inspect worker logs and pending-analysis status separately to confirm model processing.

The deployment repository intentionally excludes local `.kilo` worktrees and the large `data/benchmarks/` directory. The seed archive needed for hosted database initialization remains included.

## Project map

- `src/backend/services/`: news connectors, model loading, analysis workflow, and Mongo repositories.
- `src/backend/app/trading/`: paper-trading API, live engine, market-data and historical replay.
- `src/frontend/`: Vite + React dashboard.
- `data/`: MongoDB seed snapshot, connector examples, and benchmark documentation. Optional large benchmark CSVs are kept outside the deployment repository.
- `notebooks/`: model-training experiments.

For research and provider/schema details, see `data/README.md` and `notebooks/final/README.md`.
