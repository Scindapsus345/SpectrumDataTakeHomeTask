# Page Crawler

Небольшой сервис на FastAPI: принимает URL, асинхронно обходит HTML-страницы в
ширину и сохраняет последнюю успешную версию каждой страницы в PostgreSQL.

## Запуск

Для запуска сервиса требуется только Docker с Compose:

```bash
docker compose up --build
```

Swagger: <http://localhost:8000/docs>. Конфигурация читается из переменных
`PAGE_CRAWLER_*`; полный локальный пример находится в `.env.example`.

Запуск приложения локально требует Python 3.12 и
[uv](https://docs.astral.sh/uv/). PostgreSQL по-прежнему можно поднять через
Compose:

```bash
docker compose up -d postgres
uv sync --frozen --group dev
uv run alembic upgrade head
uv run python -m page_crawler
```

Docker-контейнер выполняет `alembic upgrade head` перед запуском приложения.
При локальном запуске миграцию нужно применять отдельной командой, как показано
выше.

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
обход обновляет страницу по URL. Временные сетевые ошибки и ответы 408, 429,
500, 502, 503 и 504 повторяются до `max_attempts` раз с экспоненциальной
задержкой.

## Проверка

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy page_crawler
uv run pytest
```

Интеграционные тесты запускают PostgreSQL через Testcontainers и требуют Docker.

## Ограничения

Состояние заданий хранится в памяти одного процесса и теряется при перезапуске;
сохранённые страницы остаются в PostgreSQL. Статус доступен для активных и
последних 20 завершённых заданий.

Сервис не блокирует private и localhost URL, а origin перенаправления проверяет
только после соединения. Поэтому его следует запускать только в доверенном
окружении.

Нормализованные URL дедуплицируются до запроса, но разные URL, перенаправляющие
на одну страницу, могут скачать и учесть её повторно.

При отсутствии объявленной кодировки HTML читается как UTF-8, а недекодируемые
байты заменяются
