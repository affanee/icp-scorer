"""Fetch and cache the public text of a company's website.

Deliberately boring. It hits a handful of pages that carry the signals the
rubric asks about, strips the HTML to readable text, and caches the result on
disk so that re-running the scorer costs nothing and hammers nobody's server.

Pages chosen because each one answers a rubric dimension:
  /            -> what they sell, who to  (segment)
  /about       -> size, story, market     (size_signal, geography)
  /careers     -> open roles              (gtm_motion, buying_trigger)
  /pricing     -> sales motion vs self-serve (gtm_motion)
"""

from __future__ import annotations

import re
from pathlib import Path

import requests

CANDIDATE_PATHS = ["", "/about", "/about-us", "/company", "/careers", "/jobs", "/pricing"]
MAX_PATHS_TO_KEEP = 4
DEFAULT_MAX_CHARS = 14_000
USER_AGENT = "icp-scorer/0.1 (+https://github.com/YOUR_USERNAME/icp-scorer)"

try:  # optional, much better extraction when present
    import trafilatura  # type: ignore

    _HAS_TRAFILATURA = True
except ImportError:  # pragma: no cover
    _HAS_TRAFILATURA = False


def clean_domain(raw: str) -> str:
    """Normalise whatever the CSV gave us into a bare domain.

    'https://www.Acme.com/pricing?utm=x' -> 'acme.com'
    Doing this in one place is why the cache actually hits.
    """
    d = (raw or "").strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0].split("?")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    return re.sub(r"\s+", " ", text).strip()


def _extract(html: str) -> str:
    if _HAS_TRAFILATURA:
        extracted = trafilatura.extract(html, include_comments=False, include_tables=False)
        if extracted:
            return re.sub(r"\s+", " ", extracted).strip()
    return _strip_html(html)


def _get(url: str, timeout: int) -> str | None:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    except requests.RequestException:
        return None
    if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
        return None
    return r.text


def fetch_company_text(
    domain: str,
    cache_dir: str | Path = ".cache/pages",
    max_chars: int = DEFAULT_MAX_CHARS,
    timeout: int = 12,
    refresh: bool = False,
    fixtures_dir: str | Path | None = None,
) -> str:
    """Return concatenated, labelled page text for one company. Cached on disk.

    If fixtures_dir is given and contains <domain>.txt, that file is used instead
    of the network. This is how `make demo` and CI run the full pipeline with no
    internet and no API key.
    """
    domain = clean_domain(domain)

    if fixtures_dir:
        fixture = Path(fixtures_dir) / f"{domain}.txt"
        if fixture.exists():
            return fixture.read_text(encoding="utf-8")[:max_chars]

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{domain}.txt"

    if cache_file.exists() and not refresh:
        return cache_file.read_text(encoding="utf-8")

    chunks: list[str] = []
    for path in CANDIDATE_PATHS:
        if len(chunks) >= MAX_PATHS_TO_KEEP:
            break
        html = _get(f"https://{domain}{path}", timeout) or _get(
            f"https://www.{domain}{path}", timeout
        )
        if not html:
            continue
        body = _extract(html)
        if len(body) < 200:  # a shell page, a redirect stub, a cookie wall
            continue
        chunks.append(f"--- PAGE: {path or '/'} ---\n{body}")

    text = "\n\n".join(chunks)[:max_chars]
    cache_file.write_text(text, encoding="utf-8")
    return text
