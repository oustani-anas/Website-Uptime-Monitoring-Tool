"""Performs one HTTP check of one URL (SPEC §6, "A single check").

No database access here: input is a URL, output is a `CheckResult`. That keeps
the networking logic small and testable with mocked HTTP (respx).
"""

import asyncio
import socket
import ssl
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.models import ErrorType
from app.services.url_safety import HostResolutionError, UnsafeURLError, assert_public_host

USER_AGENT = "UptimeMonitor/1.0"
MAX_ERROR_MESSAGE = 500  # matches the DB column


@dataclass(frozen=True)
class CheckResult:
    checked_at: datetime
    is_up: bool
    status_code: int | None = None
    response_time_ms: int | None = None
    error_type: ErrorType | None = None
    error_message: str | None = None


class TooManyRedirectsError(Exception):
    pass


def build_http_client(*, timeout: float, max_connections: int) -> httpx.AsyncClient:
    """One shared client for the worker process.

    - follow_redirects=False: we follow them ourselves to SSRF-check every hop.
    - No keep-alive: every check opens a fresh connection, so response times are
      comparable between checks and connection-level failures are always detected.
    - trust_env=False: ignore proxy env vars; we want to measure the site itself.
    """
    return httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(timeout),
        headers={"User-Agent": USER_AGENT},
        limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=0),
        trust_env=False,
    )


async def perform_check(
    client: httpx.AsyncClient, url: str, *, timeout: float, max_redirects: int
) -> CheckResult:
    """Check `url` once. Never raises: every failure becomes a classified result."""
    checked_at = datetime.now(UTC)
    try:
        # One total deadline for everything: DNS checks + all redirect hops.
        async with asyncio.timeout(timeout):
            status_code, elapsed = await _fetch(client, url, max_redirects)
    except (TimeoutError, httpx.TimeoutException):
        return _failure(checked_at, ErrorType.TIMEOUT, f"No response within {timeout:g}s")
    except UnsafeURLError as exc:
        return _failure(checked_at, ErrorType.BLOCKED_ADDRESS, str(exc))
    except HostResolutionError as exc:
        return _failure(checked_at, ErrorType.DNS, str(exc))
    except TooManyRedirectsError:
        return _failure(checked_at, ErrorType.TOO_MANY_REDIRECTS, f"More than {max_redirects} redirects")
    except httpx.ConnectError as exc:
        return _failure(checked_at, *_classify_connect_error(exc))
    except httpx.TransportError as exc:  # protocol errors, resets mid-response, ...
        return _failure(checked_at, ErrorType.CONNECTION, f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001 - a check must never crash the worker
        return _failure(checked_at, ErrorType.UNKNOWN, f"{type(exc).__name__}: {exc}")

    response_time_ms = round(elapsed * 1000)
    if status_code >= 500:
        return _failure(checked_at, ErrorType.HTTP_5XX, f"HTTP {status_code}", status_code, response_time_ms)
    if status_code >= 400:
        return _failure(checked_at, ErrorType.HTTP_4XX, f"HTTP {status_code}", status_code, response_time_ms)
    # 2xx, or a 3xx without a Location header (nothing to follow) -> up (DECISIONS D3)
    return CheckResult(checked_at, is_up=True, status_code=status_code, response_time_ms=response_time_ms)


async def _fetch(client: httpx.AsyncClient, url: str, max_redirects: int) -> tuple[int, float]:
    """Follow redirects manually. Returns (final status code, seconds spent in HTTP).

    Response time = time until response headers, summed over all hops. The body is
    never read: `client.stream()` lets us close the connection after the headers.
    """
    elapsed = 0.0
    current = httpx.URL(url)
    for _ in range(max_redirects + 1):
        if current.scheme not in ("http", "https"):
            raise UnsafeURLError(f"Redirect to unsupported scheme {current.scheme!r}")
        # Re-validated on *every* hop: a public site may redirect to an internal one.
        await assert_public_host(current.host, current.port)

        started = time.perf_counter()
        async with client.stream("GET", current) as response:
            elapsed += time.perf_counter() - started
            if not response.is_redirect:
                return response.status_code, elapsed
            # Location may be relative ("/login"); resolve it against the current URL.
            current = response.url.join(response.headers["location"])
    raise TooManyRedirectsError


def _classify_connect_error(exc: httpx.ConnectError) -> tuple[ErrorType, str]:
    """httpx wraps the low-level cause; walk the exception chain to find it."""
    for cause in _exception_chain(exc):
        if isinstance(cause, ssl.SSLError):
            detail = getattr(cause, "verify_message", None) or getattr(cause, "reason", None) or str(cause)
            return ErrorType.SSL, f"SSL error: {detail}"
        if isinstance(cause, socket.gaierror):
            return ErrorType.DNS, f"DNS lookup failed: {cause}"
    message = str(exc) or type(exc).__name__
    if "SSL" in message or "CERTIFICATE" in message:
        return ErrorType.SSL, f"SSL error: {message}"
    return ErrorType.CONNECTION, f"Connection failed: {message}"


def _exception_chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _failure(
    checked_at: datetime,
    error_type: ErrorType,
    message: str,
    status_code: int | None = None,
    response_time_ms: int | None = None,
) -> CheckResult:
    return CheckResult(
        checked_at,
        is_up=False,
        status_code=status_code,
        response_time_ms=response_time_ms,
        error_type=error_type,
        error_message=message[:MAX_ERROR_MESSAGE],
    )
