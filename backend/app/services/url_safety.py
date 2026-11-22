"""URL validation and SSRF protection (SPEC §2, DECISIONS D5).

The server makes HTTP requests to URLs supplied by users. Without these checks,
someone could make it probe `localhost`, the Docker network, or a cloud metadata
endpoint (169.254.169.254).

Two layers:
  1. `validate_url_format()`: pure string checks (no I/O). Runs inside Pydantic.
  2. `assert_public_host()`: resolves DNS and rejects any non-public address.
     Async, so it's called from the endpoint (and, in Stage 3, by the worker
     before every check and every redirect hop).
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

MAX_URL_LENGTH = 2048
DNS_TIMEOUT_SECONDS = 5

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class UnsafeURLError(ValueError):
    """The URL is malformed or points at a non-public address."""


class HostResolutionError(Exception):
    """DNS lookup failed. Not a safety problem by itself (the host may come back later)."""


def validate_url_format(url: str) -> str:
    """Check the URL's shape and return a normalized form.

    Normalization: trim whitespace, lowercase scheme and host, drop the fragment
    (`#...` is never sent to the server).
    """
    url = url.strip()
    if len(url) > MAX_URL_LENGTH:
        raise UnsafeURLError(f"URL must be at most {MAX_URL_LENGTH} characters")

    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise UnsafeURLError("URL must start with http:// or https://")
    if not parts.hostname:
        raise UnsafeURLError("URL must include a host")
    if parts.username is not None or parts.password is not None:
        raise UnsafeURLError("Credentials in URLs are not allowed")
    try:
        port = parts.port
    except ValueError:
        raise UnsafeURLError("Invalid port") from None

    # A literal IP needs no DNS, so reject private ones right away.
    literal = _parse_ip(parts.hostname)
    if literal is not None and not is_public_ip(literal):
        raise UnsafeURLError("Private or local addresses are not allowed")

    host = parts.hostname  # urlsplit already lowercases it and strips IPv6 brackets
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    # "https://x.com/" and "https://x.com" request the same resource; store one form
    # so duplicate detection treats them as the same URL.
    path = "" if parts.path == "/" else parts.path
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def is_public_ip(ip: IPAddress) -> bool:
    """True only for globally routable unicast addresses.

    `is_global` excludes loopback, private (10/8, 172.16/12, 192.168/16, fc00::/7),
    link-local (169.254/16 incl. cloud metadata, fe80::/10), CGNAT (100.64/10),
    reserved and unspecified (0.0.0.0, ::). Multicast is excluded explicitly.
    IPv4-mapped IPv6 (`::ffff:127.0.0.1`) is unwrapped first, otherwise it would
    be a trivial bypass.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def resolve_host(host: str, port: int | None) -> list[IPAddress]:
    """Resolve a hostname to all its IP addresses (A + AAAA)."""
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=DNS_TIMEOUT_SECONDS,
        )
    except (socket.gaierror, TimeoutError) as exc:
        raise HostResolutionError(f"Could not resolve host {host!r}") from exc
    # sockaddr[0] is the IP string; strip a possible IPv6 zone id ("fe80::1%eth0").
    return list({ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos})


async def assert_public_host(host: str, port: int | None = None) -> list[IPAddress]:
    """Raise UnsafeURLError unless *every* address of `host` is public.

    "Every", not "any": a hostname with one public and one private record must be
    rejected, because the HTTP client might connect to either.
    Raises HostResolutionError if DNS fails.
    """
    literal = _parse_ip(host)
    addresses = [literal] if literal is not None else await resolve_host(host, port)
    if not addresses or any(not is_public_ip(a) for a in addresses):
        raise UnsafeURLError("Private or local addresses are not allowed")
    return addresses


async def validate_monitor_url(url: str) -> str:
    """Full validation used when a monitor is created or its URL is changed.

    An unresolvable host is *accepted*: the site may be temporarily down or not
    yet live, and the worker will record `dns` failures, which is useful information.
    """
    normalized = validate_url_format(url)
    parts = urlsplit(normalized)
    try:
        await assert_public_host(parts.hostname or "", parts.port)
    except HostResolutionError:
        pass
    return normalized


def _parse_ip(host: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None
