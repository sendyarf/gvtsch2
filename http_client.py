"""
Shared resilient HTTP client for all gvtsch2 scrapers.

Why this exists (audit fix): each scraper previously did a bare `requests.get()`
with a minimal User-Agent, a fresh connection, and no retries. A single transient
failure (429 / 5xx / DNS / connection reset) silently produced 0 matches for that
source for the whole cycle.

This module centralises:
- TLS/HTTP2 **impersonation** via curl_cffi (already a dependency) which is much
  harder for anti-bot systems to fingerprint, with automatic fallback to plain
  `requests` if curl_cffi is missing or the target rejects it.
- **Connection reuse** (sessions) instead of opening a new connection per request.
- **Automatic retry** with exponential backoff + jitter on transient failures:
  connection errors, timeouts, and HTTP 408/425/429/5xx.
- Sensible default browser headers (per-scraper headers still override).

Designed to be used single-threaded from within one scraper process. The session
singletons are module-level, which is safe because each scraper runs in its own
subprocess (see run_all.py).
"""
import random
import time

# __all__ available for explicit imports. curl_cffi is optional.
try:
    from curl_cffi import requests as _cffi
    _HAS_CFFI = True
except Exception:  # pragma: no cover - handled gracefully
    _cffi = None
    _HAS_CFFI = False

try:
    import requests as _plain
except Exception:  # pragma: no cover
    _plain = None

# Realistic Chrome ~120 header bundle. The Accept-Language is broad so it works
# across the mix of sites (some are Vietnamese/Indonesian stream hosts).
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9,vi,vi-VN;q=0.8,id;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# HTTP status codes that are worth retrying because they are usually transient.
TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}

# module-level sessions: False -> plain requests session, True -> curl_cffi session
_sessions = {}


class FetchError(Exception):
    """Raised when a URL could not be fetched after exhausting all retries/backends."""


def _get_session(is_cffi):
    """Lazily create and cache one session per backend."""
    if is_cffi not in _sessions:
        if is_cffi:
            _sessions[is_cffi] = _cffi.Session() if _HAS_CFFI else None
        else:
            _sessions[is_cffi] = _plain.Session() if _plain else None
    return _sessions[is_cffi]


def _sleep_with_backoff(attempt, base):
    """Exponential backoff (`base * 2^attempt`) plus random jitter."""
    wait = base * (2 ** attempt) + random.uniform(0, base)
    time.sleep(wait)


def http_get(url, *, params=None, headers=None, timeout=30, retries=3,
             backoff=0.5, verify=True, impersonate="chrome"):
    """
    Fetch ``url`` with impersonation, connection reuse and retries.

    Returns a response-like object exposing the same interface both backends
    provide (``status_code``, ``headers``, ``text``, ``json()``,
    ``raise_for_status()``).

    Args:
        retries:  number of retries per backend (total attempts = retries + 1).
        backoff:  base seconds for exponential backoff between retries.
        verify:   certificate verification (set False for endpoints with broken certs).
        impersonate: curl_cffi impersonation profile (only used with cffi backend).

    Raises:
        FetchError: if every attempt across both backends fails.
    """
    if not _HAS_CFFI and _plain is None:
        raise FetchError("Neither curl_cffi nor requests is installed.")

    merged_headers = dict(DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)

    # Backend order of preference: impersonated cffi first, plain requests second.
    backends = []
    if _HAS_CFFI:
        backends.append(("cffi", True))
    if _plain is not None:
        backends.append(("plain", False))

    last_err = None
    for backend_name, is_cffi in backends:
        sess = _get_session(is_cffi)
        if sess is None:
            continue
        attempt = 0
        while attempt <= retries:
            try:
                if is_cffi:
                    resp = sess.get(url, params=params, headers=merged_headers,
                                    timeout=timeout, impersonate=impersonate,
                                    verify=verify)
                else:
                    resp = sess.get(url, params=params, headers=merged_headers,
                                    timeout=timeout, verify=verify)

                if resp.status_code in TRANSIENT_STATUS:
                    # Server-side transient error -> retry this backend.
                    last_err = FetchError(f"transient status {resp.status_code}")
                else:
                    return resp

            except FetchError:
                pass  # handled above by re-checking next loop iteration
            except Exception as e:  # connection error, timeout, TLS rejection, ...
                last_err = e
                if backend_name == "cffi":
                    # curl_cffi may be rejected by some setups/endpoints; the
                    # saved last_err lets the plain backend produce a clean raise.
                    break

            attempt += 1
            if attempt <= retries:
                _sleep_with_backoff(attempt, backoff)

    raise FetchError(f"failed to fetch {url}: {last_err}")