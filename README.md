# dzen-test-back

Backend for the "Comments" SPA test assignment: tree comments with CAPTCHA, file attachments,
live updates over WebSocket, moderation, search.

Stack: Python 3.14, Django 6, DRF, Strawberry GraphQL, MySQL 8.4, Redis, Caddy, Docker. Coming with the next
features: Channels (WebSocket), Celery + RabbitMQ, Elasticsearch, JWT.
Frontend: [dzen-test-front](https://github.com/sni10/dzen-test-front) (Vue 3).

> Work in progress.

## Run locally (Docker)

The compose file starts the whole application, the SPA included, so clone both repositories side by side:

```bash
git clone https://github.com/sni10/dzen-test-back.git
git clone https://github.com/sni10/dzen-test-front.git
cd dzen-test-back
cp .env.example .env
docker compose up --build
```

Open **http://localhost:8080**. Caddy serves the SPA and the API on one origin, exactly as in production:

| Path | Goes to |
|---|---|
| `/graphql` | GraphQL (reading comments; GraphiQL in a browser) |
| `/api/...` | REST: CAPTCHA, posting comments, preview, health; Swagger at `/api/docs/` |
| `/ws/...`, `/media/...`, `/admin/`, `/static/...` | Django |
| everything else | the SPA (nginx from dzen-test-front) |

Django is also published on http://localhost:8000 (for the front's `npm run dev` proxy).

Administrator: `docker compose exec app python manage.py createsuperuser`.

## Development without the app container

MySQL and Redis in Docker, Django on the host ([uv](https://docs.astral.sh/uv/)):

```bash
cp .env.example .env
docker compose up -d db redis
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
uv run python manage.py test
```

MySQL is published on `127.0.0.1:3307` (user/password from `.env`) — MySQL Workbench connects there.

## Git and releases

- `main` — releases, `dev` — integration, `feature/*` / `fix/*` — work branches merged into `dev` by pull request.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (checked in CI).
- CI (`.github/workflows/ci.yml`): commit lint + tests on MySQL for every push and pull request to `main`/`dev`;
  on push to `main` — automatic semantic version tag `vX.Y.Z`, GitHub Release and the Docker image
  `ghcr.io/sni10/dzen-test-back:<sha>` / `:vX.Y.Z`.
