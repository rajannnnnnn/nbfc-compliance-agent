"""asyncpg has no `sslmode` connect kwarg (it wants `ssl=`), while the sync psycopg
boot-check uses the same CC_DATABASE_URL with `sslmode=require`. This splits a single
URL into the pieces each driver actually accepts, so one env var serves both."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def split_async_url(url: str) -> tuple[str, dict[str, bool]]:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    require_ssl = query.pop("sslmode", None) == "require"
    stripped = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    connect_args = {"ssl": True} if require_ssl else {}
    return stripped, connect_args
