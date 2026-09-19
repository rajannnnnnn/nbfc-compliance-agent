"""HTTP fetch, hash, raw persist to data/raw/. Also supports a local-file scheme (ADR-002):
`source_url` may be a bare path or `file://` URL, in which case fetch() reads and hashes the
file without opening a socket — the default mode until real RBI documents are supplied."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from app.config import Settings


class CorpusFetchError(Exception):
    pass


class FetchResult(BaseModel):
    url: str
    content_type: str
    sha256: str
    retrieved_at: datetime
    raw_path: str
    size_bytes: int


_ANTIBOT_MARKERS = (
    "captcha",
    "are you human",
    "checking your browser",
    "access denied",
    "cloudflare",
)

_MIN_BODY_BYTES = 2048


def _is_local(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("", "file")


def _local_path(url: str) -> Path:
    parsed = urlparse(url)
    return Path(parsed.path) if parsed.scheme == "file" else Path(url)


def _looks_like_interstitial(body: bytes) -> bool:
    if len(body) >= _MIN_BODY_BYTES:
        return False
    text_lower = body.decode("utf-8", errors="ignore").lower()
    return any(marker in text_lower for marker in _ANTIBOT_MARKERS)


async def fetch(url: str, *, settings: Settings) -> FetchResult:
    """Reads from a local file when `url` has no scheme or is `file://`; otherwise performs a
    same-host-redirect-only GET with the configured user agent and a 30s timeout. Raises
    CorpusFetchError on non-200, a detected anti-bot interstitial, or a body under 2 KiB —
    a body that small is never a real regulatory instrument."""
    if _is_local(url):
        path = _local_path(url)
        if not path.exists():
            raise CorpusFetchError(f"local source not found: {path}")
        body = path.read_bytes()
        if len(body) < _MIN_BODY_BYTES:
            raise CorpusFetchError(f"local source under {_MIN_BODY_BYTES} bytes: {path}")
        sha256 = hashlib.sha256(body).hexdigest()
        raw_path = Path(settings.corpus_raw_dir) / f"{sha256}{path.suffix or '.txt'}"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(body)
        return FetchResult(
            url=url,
            content_type="text/plain",
            sha256=sha256,
            retrieved_at=datetime.now(UTC),
            raw_path=str(raw_path),
            size_bytes=len(body),
        )

    async with httpx.AsyncClient(
        headers={"User-Agent": settings.corpus_user_agent},
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            raise CorpusFetchError(f"fetch failed for {url}: {exc}") from exc

        original_host = urlparse(url).hostname
        final_host = urlparse(str(resp.url)).hostname
        if final_host != original_host:
            raise CorpusFetchError(f"cross-host redirect refused: {url} -> {resp.url}")

        if resp.status_code != 200:
            raise CorpusFetchError(f"non-200 status {resp.status_code} for {url}")

        body = resp.content
        if _looks_like_interstitial(body):
            raise CorpusFetchError(f"anti-bot interstitial detected for {url}; no file written")
        if len(body) < _MIN_BODY_BYTES:
            raise CorpusFetchError(f"body under {_MIN_BODY_BYTES} bytes for {url}")

        sha256 = hashlib.sha256(body).hexdigest()
        ext = ".html" if "html" in resp.headers.get("content-type", "") else ".bin"
        raw_path = Path(settings.corpus_raw_dir) / f"{sha256}{ext}"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(body)

        return FetchResult(
            url=url,
            content_type=resp.headers.get("content-type", ""),
            sha256=sha256,
            retrieved_at=datetime.now(UTC),
            raw_path=str(raw_path),
            size_bytes=len(body),
        )
