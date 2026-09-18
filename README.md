# Page Crawler

Небольшой сервис на FastAPI: принимает URL, асинхронно обходит HTML-страницы в
ширину и сохраняет последнюю успешную версию каждой страницы в PostgreSQL.

## Запуск

Требуются Python 3.12, [uv](https://docs.astral.sh/uv/) и Docker.

```bash
uv sync --frozen --group dev
docker compose up --build
```

Swagger: <http://localhost:8000/docs>. Конфигурация читается из переменных
`PAGE_CRAWLER_*`; полный локальный пример находится в `.env.example`.

Запуск приложения без Docker:

```bash
docker compose up -d postgres
uv run python -m page_crawler
```

При старте приложение идемпотентно применяет `schema.sql`.

## API

```bash
curl -X POST http://localhost:8000/api/v1/crawls \
  -H 'Content-Type: application/json' \
  -d '{"root_url":"https://example.org","max_depth":1,"max_concurrency":5}'

curl http://localhost:8000/api/v1/crawls/<crawl-id>
curl 'http://localhost:8000/api/v1/pages?title_query=example&limit=20&offset=0'
curl --get http://localhost:8000/api/v1/pages/content \
  --data-urlencode 'url=https://example.org/'
```

Корневая страница имеет глубину 0. Следующий уровень начинается только после
завершения текущего. Общий пул ограничивает суммарную параллельность всех
обходов серверным `max_concurrency`; лимит запроса дополнительно ограничивает
конкретный crawl. При заполнении `max_active_crawls` новая задача получает 503.
Ссылки ограничиваются origin финального URL корня. Повторный
обход обновляет страницу по URL.

## Проверка

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy page_crawler
uv run pytest
```

Интеграционные тесты запускают PostgreSQL через Testcontainers и требуют Docker.

## Ограничения

Задания живут в памяти одного процесса и теряются при перезапуске; сохранённые
страницы остаются в PostgreSQL. Доступны активные и последние 20 завершённых
заданий. Сервис не поддерживает несколько реплик,
восстановление заданий, JavaScript, robots.txt, retries, cookies и conditional
requests. Он не блокирует private/localhost URL и не проверяет redirect target до
соединения, поэтому предназначен только для доверенного окружения.

Дедуплицируются нормализованные URL до отправки запроса. Разные URL одного
уровня, которые редиректят на одну страницу, могут скачать и учесть её повторно.
При отсутствии объявленной кодировки HTML читается как UTF-8, а недекодируемые
байты заменяются; автоматического определения legacy-кодировок нет.

Старая многотабличная схема автоматически не мигрируется. Compose использует
новый volume; для внешней БД нужна пустая схема `public`.

Причины и границы упрощения зафиксированы в `SPEC_SIMPLIFY.md`.
