# dzen-test-back

Бэкенд тестового задания «SPA-комментарии»: древовидные комментарии с CAPTCHA, вложения, обновления
в реальном времени по WebSocket, модерация, поиск.

Стек: Python 3.14, Django 6, DRF, Strawberry GraphQL, Channels (WebSocket), MySQL 8.4, Redis,
Celery + RabbitMQ, Elasticsearch, JWT, Caddy, Docker.
Фронтенд: [dzen-test-front](https://github.com/sni10/dzen-test-front) (Vue 3).

> В работе.

## Ссылки

| Что | Где |
|---|---|
| Рабочий сайт | https://comments.185-233-44-60.sslip.io |
| REST API: Swagger UI | https://comments.185-233-44-60.sslip.io/api/docs/ |
| REST API: схема OpenAPI | https://comments.185-233-44-60.sslip.io/api/schema/ |
| GraphQL (в браузере — GraphiQL) | https://comments.185-233-44-60.sslip.io/graphql |
| GraphQL-схема | [schema.graphql](schema.graphql) |
| Схема БД (MySQL) | [db/schema.sql](db/schema.sql), модель MySQL Workbench — [db/schema.mwb](db/schema.mwb) |
| Состояние сервиса | https://comments.185-233-44-60.sslip.io/api/health/ |
| Нагрузочный тест | [loadtest/README.md](loadtest/README.md) |

### Примеры запросов

Первая страница ленты (25 заглавных комментариев, новые сверху) с первыми ответами:

```bash
curl -s https://comments.185-233-44-60.sslip.io/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query": "{ comments(page: 1, sort: CREATED_AT_DESC) { totalCount pageCount items { id userName text createdAt repliesCount replies(first: 3) { items { id userName text } } } } }"}'
```

Поиск по словоформам с подсветкой:

```bash
curl -s https://comments.185-233-44-60.sslip.io/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query": "{ search(query: \"комментарий\") { totalCount items { highlight comment { id userName } } } }"}'
```

Статистика и проверка сервиса:

```bash
curl -s https://comments.185-233-44-60.sslip.io/graphql \
  -H 'Content-Type: application/json' -d '{"query": "{ stats { comments ufo shadowed } }"}'
curl -s https://comments.185-233-44-60.sslip.io/api/health/   # {"status":"ok","db":true,"cache":true}
```

Публикация комментария (REST): получить CAPTCHA, затем отправить форму с её ключом и текстом с картинки.
Cookie нужна: по ней гость узнаётся как автор.

```bash
curl -s -c jar -b jar https://comments.185-233-44-60.sslip.io/api/captcha/
# {"key": "...", "image": "data:image/png;base64,..."} — текст с картинки вводится в captcha_answer
curl -s -c jar -b jar https://comments.185-233-44-60.sslip.io/api/comments/ \
  -H 'Content-Type: application/json' \
  -d '{"user_name": "Anonym", "email": "anonym@example.com", "text": "Hello, <strong>world</strong>",
       "captcha_key": "<key>", "captcha_answer": "<текст с картинки>"}'
```

## Схема БД

MySQL 8.4, InnoDB, utf8mb4. Полная схема со всеми индексами — [db/schema.sql](db/schema.sql), модель
MySQL Workbench — [db/schema.mwb](db/schema.mwb).

EER-диаграмма из MySQL Workbench (все таблицы, включая служебные таблицы Django):

![Схема БД из MySQL Workbench](db/schema.png)

Таблицы приложения со смыслом полей (без служебных таблиц Django — прав, сессий, журнала админки):

```mermaid
erDiagram
    accounts_user ||--o{ comments_comment : "пишет"
    comments_comment ||--o{ comments_comment : "parent: ответы"
    comments_comment ||--o{ comments_comment : "root: вся ветка"
    comments_comment ||--o{ comments_attachment : "вложения"
    comments_comment ||--o{ comments_commentvote : "голоса"
    accounts_user ||--o{ comments_commentvote : "голосует"
    comments_comment ||--o{ comments_bookmark : "в закладках"
    accounts_user ||--o{ comments_bookmark : "хранит"
    accounts_user ||--o{ moderation_shadowban : "забанен (user)"
    accounts_user ||--o{ moderation_shadowban : "забанил (created_by)"
    moderation_shadowban ||--o{ moderation_moderationaction : "журнал бана"
    comments_comment ||--o{ moderation_moderationaction : "журнал НЛО"
    accounts_user ||--o{ moderation_moderationaction : "модератор"
    accounts_user ||--o{ token_blacklist_outstandingtoken : "refresh-токены"
    token_blacklist_outstandingtoken ||--o| token_blacklist_blacklistedtoken : "отозван"

    accounts_user {
        bigint id PK
        varchar username UK "50, латиница и цифры"
        varchar email UK
        varchar home_page
        varchar password "хеш"
        varchar role "user | admin"
        bool is_shadowbanned "зеркало активного бана"
        bool is_active
        bool is_superuser
        datetime date_joined
    }
    comments_comment {
        bigint id PK
        bigint parent_id FK "NULL — заглавный"
        bigint root_id FK "корень ветки, NULL у заглавного"
        smallint depth
        bigint user_id FK "NULL — гость"
        char guest_key "cookie гостя"
        varchar user_name "снимок на момент записи"
        varchar email
        varchar home_page
        longtext text "очищенный HTML"
        bool is_ufo "текст скрыт модератором"
        bool is_shadowed "теневой бан автора"
        bool by_moderator "сообщение администрации"
        int replies_count "денормализовано"
        int score "денормализовано"
        char ip
        varchar user_agent
        datetime created_at
    }
    comments_attachment {
        bigint id PK
        bigint comment_id FK
        varchar kind "image | text"
        varchar file
        varchar original_name
        int size
        smallint width
        smallint height
        varchar status "processing | ready | failed"
        datetime created_at
    }
    comments_commentvote {
        bigint id PK
        bigint comment_id FK "UK вместе с user_id"
        bigint user_id FK
        smallint value "+1 | -1"
        datetime created_at
        datetime updated_at
    }
    comments_bookmark {
        bigint id PK
        bigint user_id FK "UK вместе с comment_id"
        bigint comment_id FK
        datetime created_at
    }
    moderation_shadowban {
        bigint id PK
        bigint user_id FK "зарегистрированный"
        char guest_key "или гость: cookie"
        varchar email "и e-mail"
        varchar user_name
        varchar reason
        bigint created_by_id FK
        datetime created_at
        datetime lifted_at "NULL — активен"
    }
    moderation_moderationaction {
        bigint id PK
        varchar kind "ufo | restore | shadowban | unban"
        bigint comment_id FK
        bigint shadow_ban_id FK
        bigint moderator_id FK
        longtext original_text
        varchar reason
        datetime created_at
    }
    token_blacklist_outstandingtoken {
        bigint id PK
        bigint user_id FK
        varchar jti UK
        longtext token
        datetime created_at
        datetime expires_at
    }
    token_blacklist_blacklistedtoken {
        bigint id PK
        bigint token_id FK, UK
        datetime blacklisted_at
    }
```

Индексы ленты — под каждую сортировку: `(parent_id, created_at | user_name | email, id, is_shadowed)`; ветка
читается по `(root_id, created_at, id)`. Почему так — в [отчёте нагрузочного теста](loadtest/README.md).

## Локальный запуск (Docker)

Compose поднимает всё приложение вместе с SPA, поэтому оба репозитория клонируются рядом:

```bash
git clone https://github.com/sni10/dzen-test-back.git
git clone https://github.com/sni10/dzen-test-front.git
cd dzen-test-back
cp .env.example .env
docker compose up --build
```

Откройте **http://localhost:8080**. Caddy отдаёт SPA и API с одного адреса, как в продакшене:

| Путь | Куда |
|---|---|
| `/graphql` | GraphQL (чтение комментариев, голоса, закладки, модерация, поиск; в браузере — GraphiQL) |
| `/api/...` | REST: CAPTCHA, публикация комментариев, предпросмотр, health; Swagger на `/api/docs/` |
| `/api/auth/...` | JWT: `register/`, `login/` (по имени или e-mail), `refresh/`, `logout/`. Access-токен (15 мин) передаётся в `Authorization: Bearer`, для WebSocket — в `?token=`; refresh-токен (7 дней, меняется при каждом обновлении) хранится в httpOnly-cookie |
| `/ws/comments/` | WebSocket: события `comment.created`, `comment.updated`, `comment.score`, `attachment.updated` приходят на все открытые страницы |
| `/media/...`, `/admin/`, `/static/...` | Django |
| всё остальное | SPA (nginx из dzen-test-front) |

Django также доступен на http://localhost:8000 (для прокси `npm run dev` во фронтенде).

Фоновая работа идёт в контейнере `worker` (Celery через RabbitMQ): прикреплённое изображение сначала
сохраняется (`status: processing`), затем вписывается в 320×240 и пересохраняется (`ready`). Интерфейс
RabbitMQ: http://localhost:15673 (`dzen` / `dzen`).

Администратор: `docker compose exec app python manage.py createsuperuser`.

**Поиск** (GraphQL `search(query)`, словоформы русского и английского, подсветка совпадений) работает на
Elasticsearch. Новые и отмодерированные комментарии индексирует воркер; полностью (пере)построить индекс —
на новом сервере или после изменения маппинга: `docker compose exec app python manage.py reindex`.

**Нагрузочный тест** на миллионе комментариев (`manage.py seed`, Locust) — как запустить и результаты:
[loadtest/README.md](loadtest/README.md).

## Разработка без контейнера приложения

MySQL, Redis, RabbitMQ и Elasticsearch в Docker, Django на хосте ([uv](https://docs.astral.sh/uv/)):

```bash
cp .env.example .env
docker compose up -d db redis rabbitmq elasticsearch
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
uv run celery -A config worker --pool solo --loglevel info   # фоновые задачи (в другом терминале)
uv run python manage.py test
```

MySQL доступен на `127.0.0.1:3307` (пользователь и пароль из `.env`) — туда подключается MySQL Workbench.

## Git и релизы

- `main` — релизы, `dev` — интеграция, `feature/*` / `fix/*` — рабочие ветки, сливаются в `dev` через pull request.
- Сообщения коммитов — по [Conventional Commits](https://www.conventionalcommits.org/) (проверяется в CI).
- CI (`.github/workflows/ci.yml`): проверка коммитов и тесты на MySQL для каждого push и pull request в
  `main`/`dev`; при push в `main` — автоматический семантический тег `vX.Y.Z`, GitHub Release и Docker-образ
  `ghcr.io/sni10/dzen-test-back:<sha>` / `:vX.Y.Z`.
- На сервере интерфейс RabbitMQ слушает только `127.0.0.1:15672` самого сервера. Открывать через SSH-туннель:
  `ssh -L 15672:127.0.0.1:15672 deploy@<server>`, затем http://localhost:15672 с `RABBITMQ_USER` /
  `RABBITMQ_PASSWORD` из `.env` на сервере.
