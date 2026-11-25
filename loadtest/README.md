# Load test: 1 000 000 comments

The Middle+ requirement: a million messages and 100 000 visitors a day. 100k visitors a day is about
1–2 new visitors a second on average; with ~10 requests per visit that is ~15 RPS on average and a few tens of
RPS at a peak. Almost everything is reading.

## Running it

Against the local compose stack (`docker compose up`, the site on http://localhost:8080):

```bash
# 1. Per-IP rate limits off: every simulated visitor comes from one machine. DEBUG-only, refused in production
echo DJANGO_THROTTLING=false >> .env && docker compose up -d app worker

# 2. A million comments: ~200k threads with replies up to 6 levels deep, spread over the past year (~1.5 min)
docker compose exec app python manage.py seed
docker compose exec app python manage.py reindex   # search over them (~1.5 min)

# 3. The test (Locust web UI on http://localhost:8089, or --headless as below)
uv run --group loadtest locust -f loadtest/locustfile.py --host http://127.0.0.1:8080 \
    --headless -u 100 -r 20 -t 3m

# Afterwards: remove the seeded rows and the posts of the test, then delete DJANGO_THROTTLING from .env
docker compose exec app python manage.py seed --clear
```

Use `127.0.0.1`, not `localhost`, on Windows: `localhost` tries IPv6 first and adds ~0.2 s to every request.

The visitors do what the SPA does, with its GraphQL queries: the first page of the feed most often, other
sorts and nearby pages, sometimes a random deep page, threads, the stats cards, search; one action in ~30 is
posting a comment or a reply. Posting solves the CAPTCHA by reading the answer from the local Redis — there is
no CAPTCHA bypass in the application.

## Results

A 16-CPU development machine, Docker Desktop, the compose stack as it is (2 uvicorn workers, MySQL 8.4 with
default settings), 1 000 000 comments, 3 minutes per run.

**100 concurrent visitors** — 39 RPS, no errors:

| Request | Share | p50, ms | p95, ms | p99, ms |
|---|---|---|---|---|
| feed: first page | 38% | 100 | 390 | 730 |
| feed: other sort / nearby page | 15% | 130 | 520 | 830 |
| feed: random deep page (up to page 8000) | 4% | 170 | 430 | 830 |
| thread | 18% | 67 | 280 | 520 |
| stats | 11% | 46 | 230 | 360 |
| search (Elasticsearch, 1M documents) | 7% | 97 | 300 | 380 |
| post comment / reply | 4% | 46–53 | 240–270 | 550–580 |
| **all** | | **95** | **370** | **740** |

MySQL used ~26% of one CPU, the application ~143% (two processes).

**200 concurrent visitors** — 43 RPS: the same throughput, latency grows (p50 2 s, p95 4.5 s), 2 of 7621
requests answered 502. The ceiling is the application's CPU — Python building GraphQL responses in two
processes — not the database (~36% of one CPU).

## What the million rows found

The first run with a million rows answered the first page of the feed in **20 s**. Fixed here:

| Problem | Before | After | Fix |
|---|---|---|---|
| Page count of the feed: `COUNT(*)` of visible threads on every request | 18 s | 0 | Counters in Redis, incremented in place by new comments (`comments/stats.py`) |
| Stats cards recounting after every new comment | 1.3–4 s | 9 ms | The same counters; per-viewer parts are small indexed counts |
| Deep pages (`OFFSET 199950`) | 2.4 s (by date) – 38 s (by e-mail) | 0.1–0.3 s | Deferred join: page ids from a covering index, then 25 rows (`comment_page`) |
| Visibility filter `is_shadowed = 0 OR guest_key = …` read every row | | | Own hidden comments by id; the sort indexes carry `is_shadowed` |
| Counters expiring under load: every request recounting a million rows at once (MySQL at ~900% CPU) | | | No expiry; the recount itself is two index-only grouped counts (~270 ms) |
| Concurrent replies to one comment: MySQL deadlock (HTTP 500) | 1 in ~150 replies | 0 | Update the parent's counter before inserting the reply |
| Shadow-banning a guest without a cookie matched **every** comment without one | | | Match by e-mail only when there is no cookie |
| Guest shadow ban by e-mail: full scan | | | Index on `email` |
| `reindex` of a million documents | ~1 h | 1.5 min | Bulk load without a refresh per batch |

## Conclusions

- One local machine with the stack as shipped serves ~40 RPS with p95 under 0.4 s on a million comments —
  more than the estimated peak of 100k visitors a day.
- The production server is smaller (1 CPU), so its ceiling is lower: there the application's CPU is the limit
  as well. The application is stateless (sessions are JWT, WebSocket groups and caches in Redis), so the next
  steps are more uvicorn workers or containers behind Caddy, then caching the first page of the feed (most
  of the traffic) in Redis.
- MySQL is far from its limit with these indexes; a read replica is not needed at this volume.
