import pytest

from page_crawler.page_extractor import extract
from page_crawler.urls import normalize, resolve, same_origin


def test_url_operations() -> None:
    assert normalize(" HTTPS://Exämple.org:443#part ") == "https://xn--exmple-cua.org/"
    assert normalize("http://example.org:8080/path") == "http://example.org:8080/path"
    assert resolve("https://example.org/a/", "../b?q=1#part") == "https://example.org/b?q=1"
    assert same_origin("https://example.org", "https://EXAMPLE.org:443/a")
    assert not same_origin("https://example.org", "http://example.org/a")
    with pytest.raises(ValueError):
        normalize("/relative")
    with pytest.raises(ValueError, match="http or https"):
        normalize("ftp://example.org/file")


def test_extracts_title_base_and_unique_same_origin_links() -> None:
    page = extract(
        """
        <html><head><title>  Example &amp; docs </title><base href="/docs/"></head>
        <body>
          <a href="one#first">one</a><a href="one#second">duplicate</a>
          <a href="../two">two</a><a href="https://other.test/">external</a>
        </body></html>
        """,
        "https://example.org/root",
    )
    assert page.title == "Example & docs"
    assert page.links == (
        "https://example.org/docs/one",
        "https://example.org/two",
    )

    limited = extract(
        '<title>x</title><a href="/seen">seen</a><a href="/one">1</a>'
        '<a href="/two">2</a><a href="/three">3</a>',
        "https://example.org/root",
        excluded_links={"https://example.org/seen"},
        link_limit=2,
    )
    assert limited.links == ("https://example.org/one", "https://example.org/two")
