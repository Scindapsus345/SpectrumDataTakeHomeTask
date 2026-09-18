from datetime import datetime

from asyncpg import Pool  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict

UPSERT_PAGE = """
INSERT INTO pages (url, title, html)
VALUES ($1, $2, $3)
ON CONFLICT (url) DO UPDATE
SET title = EXCLUDED.title, html = EXCLUDED.html, fetched_at = CURRENT_TIMESTAMP
"""
SEARCH_PAGES = """
SELECT url, title
FROM pages
WHERE ($1::text IS NULL OR url ILIKE '%' || $1 || '%' ESCAPE '\\')
  AND ($2::text IS NULL OR title ILIKE '%' || $2 || '%' ESCAPE '\\')
ORDER BY fetched_at DESC, url
LIMIT $3 OFFSET $4
"""
GET_CONTENT = "SELECT url, title, html, fetched_at FROM pages WHERE url = $1"


class PageSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    title: str | None


class StoredPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    title: str | None
    html: str
    fetched_at: datetime


def _literal_pattern(value: str | None) -> str | None:
    if value is None:
        return None
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class PageStorage:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def upsert(self, url: str, title: str | None, html: str) -> None:
        await self._pool.execute(UPSERT_PAGE, url, title, html)

    async def search(
        self,
        url_query: str | None,
        title_query: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[PageSummary], bool]:
        rows = await self._pool.fetch(
            SEARCH_PAGES,
            _literal_pattern(url_query),
            _literal_pattern(title_query),
            limit + 1,
            offset,
        )
        return (
            [PageSummary(url=str(row["url"]), title=row["title"]) for row in rows[:limit]],
            len(rows) > limit,
        )

    async def get_content(self, url: str) -> StoredPage | None:
        row = await self._pool.fetchrow(GET_CONTENT, url)
        if row is None:
            return None
        return StoredPage(
            url=str(row["url"]),
            title=row["title"],
            html=str(row["html"]),
            fetched_at=row["fetched_at"],
        )
