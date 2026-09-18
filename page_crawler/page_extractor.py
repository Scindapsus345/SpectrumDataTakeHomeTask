from contextlib import suppress

from pydantic import BaseModel, ConfigDict
from selectolax.parser import HTMLParser

from page_crawler.urls import resolve, same_origin


class ExtractedPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str | None
    links: tuple[str, ...]


def extract(
    html: str,
    page_url: str,
    scope_url: str | None = None,
    *,
    include_links: bool = True,
) -> ExtractedPage:
    document = HTMLParser(html)
    title_node = document.css_first("title")
    title = title_node.text(strip=True) if title_node is not None else None
    title = title or None

    if not include_links:
        return ExtractedPage(title=title, links=())

    base_url = page_url
    base_node = document.css_first("base[href]")
    base_href = base_node.attributes.get("href") if base_node is not None else None
    if base_href:
        with suppress(ValueError):
            base_url = resolve(page_url, base_href)

    scope = scope_url or page_url
    links: dict[str, None] = {}
    for node in document.css("a[href]"):
        href = node.attributes.get("href")
        if not href:
            continue
        try:
            url = resolve(base_url, href)
        except ValueError:
            continue
        if url == page_url:
            continue
        if same_origin(scope, url):
            links[url] = None
    return ExtractedPage(title=title, links=tuple(links))
