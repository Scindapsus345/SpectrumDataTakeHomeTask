from page_crawler.page_storage import PageStorage


async def test_storage_upsert_search_and_content(pg_pool: object) -> None:
    storage = PageStorage(pg_pool)  # type: ignore[arg-type]
    await storage.upsert("https://example.org/a%25_", "Old", "<p>old</p>")
    await storage.upsert("https://example.org/a%25_", "New title", "<p>new</p>")
    await storage.upsert("https://example.org/other", "Other", "<p>other</p>")

    pages, has_more = await storage.search("%", "new", 1, 0)
    assert [(page.url, page.title) for page in pages] == [
        ("https://example.org/a%25_", "New title")
    ]
    assert not has_more

    page = await storage.get_content("https://example.org/a%25_")
    assert page is not None
    assert (page.title, page.html) == ("New title", "<p>new</p>")
