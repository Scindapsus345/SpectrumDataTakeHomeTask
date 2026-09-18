from contextlib import suppress
from dataclasses import dataclass

from selectolax.parser import HTMLParser

from page_crawler.urls import resolve, same_origin


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    title: str | None
    links: tuple[str, ...]


def extract(
    html: str,
    page_url: str,
    scope_url: str | None = None,
    *,
    excluded_links: set[str] | None = None,
    link_limit: int | None = None,
) -> ExtractedPage:
    document = HTMLParser(html)
    title_node = document.css_first("title")
    title = title_node.text(strip=True) if title_node is not None else None
    title = title or None

    if link_limit == 0:
        return ExtractedPage(title, ())

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
        if same_origin(scope, url) and (excluded_links is None or url not in excluded_links):
            links[url] = None
            if link_limit is not None and len(links) >= link_limit:
                break
    return ExtractedPage(title, tuple(links))
