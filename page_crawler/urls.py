from urllib.parse import urljoin, urlsplit, urlunsplit

DEFAULT_PORT_BY_SCHEME = {"http": 80, "https": 443}


def normalize(value: str) -> str:
    parts = urlsplit(value.strip())
    if not parts.scheme or parts.hostname is None:
        raise ValueError("URL must be absolute")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("Invalid URL port") from exc

    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORT_BY_SCHEME:
        raise ValueError("URL scheme must be http or https")
    host = parts.hostname.encode("idna").decode("ascii").lower()
    if ":" in host:
        host = f"[{host}]"
    userinfo = f"{parts.netloc.rsplit('@', 1)[0]}@" if "@" in parts.netloc else ""
    default_port = DEFAULT_PORT_BY_SCHEME[scheme] == port
    netloc = f"{userinfo}{host}" + (f":{port}" if port is not None and not default_port else "")
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def resolve(base_url: str, reference: str) -> str:
    return normalize(urljoin(base_url, reference.strip()))


def same_origin(left: str, right: str) -> bool:
    def origin(value: str) -> tuple[str, str | None, int | None]:
        parts = urlsplit(normalize(value))
        port = parts.port or DEFAULT_PORT_BY_SCHEME.get(parts.scheme)
        return parts.scheme, parts.hostname, port

    return origin(left) == origin(right)
