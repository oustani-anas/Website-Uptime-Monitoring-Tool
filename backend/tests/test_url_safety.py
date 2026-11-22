import ipaddress

import pytest

from app.services.url_safety import (
    HostResolutionError,
    UnsafeURLError,
    assert_public_host,
    is_public_ip,
    validate_monitor_url,
    validate_url_format,
)

# ---------- format (no I/O) ----------


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("ftp://example.com", "http:// or https://"),
        ("example.com", "http:// or https://"),  # missing scheme
        ("javascript:alert(1)", "http:// or https://"),
        ("http://", "must include a host"),
        ("http://user:pass@example.com", "Credentials"),
        ("http://user@example.com", "Credentials"),
        ("http://example.com:99999", "Invalid port"),
        ("https://example.com/" + "a" * 2048, "at most 2048"),
        ("http://127.0.0.1", "Private or local"),  # literal IPs are rejected without DNS
        ("http://[::1]:8080", "Private or local"),
        ("http://169.254.169.254/latest/meta-data", "Private or local"),
    ],
)
def test_format_rejects(url: str, message: str) -> None:
    with pytest.raises(UnsafeURLError, match=message):
        validate_url_format(url)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com", "https://example.com"),
        ("  HTTPS://Example.COM/Path?q=1#frag ", "https://example.com/Path?q=1"),  # path case kept
        ("http://example.com:8080/x", "http://example.com:8080/x"),
        ("http://[2606:4700::1111]/", "http://[2606:4700::1111]"),
        ("https://example.com/", "https://example.com"),  # root "/" == no path
        ("https://example.com/?q=1", "https://example.com?q=1"),
        ("https://example.com/docs/", "https://example.com/docs/"),  # non-root trailing slash is kept
    ],
)
def test_format_normalizes(url: str, expected: str) -> None:
    assert validate_url_format(url) == expected


# ---------- IP classification ----------


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.1",  # private
        "172.16.0.1",  # private
        "192.168.1.1",  # private
        "169.254.169.254",  # link-local / cloud metadata
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",  # unspecified
        "224.0.0.1",  # multicast
        "255.255.255.255",  # broadcast
        "::1",  # IPv6 loopback
        "fe80::1",  # IPv6 link-local
        "fc00::1",  # IPv6 unique-local
        "::ffff:127.0.0.1",  # IPv4-mapped IPv6 -> loopback
        "::ffff:10.0.0.1",  # IPv4-mapped IPv6 -> private
    ],
)
def test_non_public_ips_are_blocked(ip: str) -> None:
    assert not is_public_ip(ipaddress.ip_address(ip))


@pytest.mark.parametrize("ip", ["8.8.8.8", "93.184.216.34", "2606:4700:4700::1111"])
def test_public_ips_are_allowed(ip: str) -> None:
    assert is_public_ip(ipaddress.ip_address(ip))


# ---------- DNS-based checks ----------


async def test_host_resolving_to_private_ip_is_blocked(fake_dns) -> None:
    fake_dns["internal.example"] = ["10.1.2.3"]
    with pytest.raises(UnsafeURLError):
        await assert_public_host("internal.example")


async def test_host_with_any_private_record_is_blocked(fake_dns) -> None:
    # One public + one private record: the client could connect to either.
    fake_dns["mixed.example"] = ["93.184.216.34", "127.0.0.1"]
    with pytest.raises(UnsafeURLError):
        await assert_public_host("mixed.example")


async def test_public_host_passes(fake_dns) -> None:
    fake_dns["good.example"] = ["93.184.216.34", "2606:2800:220:1::1"]
    assert len(await assert_public_host("good.example")) == 2


async def test_unresolvable_host_raises_resolution_error(fake_dns) -> None:
    fake_dns["nope.invalid"] = []
    with pytest.raises(HostResolutionError):
        await assert_public_host("nope.invalid")


async def test_monitor_url_allows_unresolvable_host(fake_dns) -> None:
    # Accepted on save; the worker will record `dns` failures instead.
    fake_dns["not-live-yet.example"] = []
    assert await validate_monitor_url("https://not-live-yet.example") == "https://not-live-yet.example"


async def test_monitor_url_blocks_localhost_name(fake_dns) -> None:
    fake_dns["localhost"] = ["127.0.0.1", "::1"]
    with pytest.raises(UnsafeURLError):
        await validate_monitor_url("http://localhost:8000/api/health")


async def test_numeric_ip_encodings_are_blocked_via_real_resolver() -> None:
    # "2130706433" is 127.0.0.1 written as a decimal integer. It isn't a literal IP
    # to Python's ipaddress module, but the OS resolver turns it into 127.0.0.1.
    # The DNS layer catches it. (Numeric lookup only, no network needed.)
    with pytest.raises(UnsafeURLError):
        await validate_monitor_url("http://2130706433/")
