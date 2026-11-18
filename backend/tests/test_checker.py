"""HTTP checker (app/worker/checker.py), with HTTP mocked by respx and DNS by fake_dns."""

import asyncio
import ssl

import httpx
import pytest
import respx

from app.models import ErrorType
from app.worker.checker import _classify_connect_error, build_http_client, perform_check

URL = "https://site.example/"


@pytest.fixture
async def client():
    async with build_http_client(timeout=5, max_connections=5) as c:
        yield c


async def check(client: httpx.AsyncClient, url: str = URL, timeout: float = 5, max_redirects: int = 5):
    return await perform_check(client, url, timeout=timeout, max_redirects=max_redirects)


async def test_200_is_up(client, fake_dns, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).respond(200)
    r = await check(client)
    assert r.is_up and r.status_code == 200
    assert r.error_type is None and r.error_message is None
    assert r.response_time_ms is not None and r.response_time_ms >= 0


async def test_sends_user_agent(client, fake_dns, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).respond(200)
    await check(client)
    assert route.calls.last.request.headers["user-agent"] == "UptimeMonitor/1.0"


async def test_follows_relative_redirect(client, fake_dns, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).respond(301, headers={"Location": "/home"})
    respx_mock.get("https://site.example/home").respond(200)
    r = await check(client)
    assert r.is_up and r.status_code == 200


async def test_redirect_to_private_address_is_blocked(client, fake_dns, respx_mock: respx.MockRouter) -> None:
    fake_dns["internal.example"] = ["10.0.0.7"]
    respx_mock.get(URL).respond(302, headers={"Location": "http://internal.example/admin"})
    internal = respx_mock.get("http://internal.example/admin").respond(200)
    r = await check(client)
    assert not r.is_up and r.error_type == ErrorType.BLOCKED_ADDRESS
    assert not internal.called  # the internal URL is never requested


async def test_redirect_to_other_scheme_is_blocked(client, fake_dns, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).respond(302, headers={"Location": "file:///etc/passwd"})
    r = await check(client)
    assert r.error_type == ErrorType.BLOCKED_ADDRESS


async def test_redirect_loop_is_too_many_redirects(client, fake_dns, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).respond(302, headers={"Location": URL})
    r = await check(client, max_redirects=3)
    assert r.error_type == ErrorType.TOO_MANY_REDIRECTS
    assert r.error_message == "More than 3 redirects"


@pytest.mark.parametrize(("code", "error"), [(404, ErrorType.HTTP_4XX), (403, ErrorType.HTTP_4XX),
                                            (500, ErrorType.HTTP_5XX), (503, ErrorType.HTTP_5XX)])
async def test_error_status_is_down(client, fake_dns, respx_mock, code, error) -> None:
    respx_mock.get(URL).respond(code)
    r = await check(client)
    assert not r.is_up and r.error_type == error
    assert r.status_code == code and r.error_message == f"HTTP {code}"
    assert r.response_time_ms is not None  # the server did answer


async def test_initial_private_target_is_blocked(client, fake_dns) -> None:
    # e.g. DNS changed since the monitor was saved (rebinding)
    fake_dns["site.example"] = ["127.0.0.1"]
    r = await check(client)
    assert r.error_type == ErrorType.BLOCKED_ADDRESS


async def test_dns_failure(client, fake_dns) -> None:
    fake_dns["site.example"] = []
    r = await check(client)
    assert r.error_type == ErrorType.DNS


async def test_httpx_timeout(client, fake_dns, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).mock(side_effect=httpx.ReadTimeout("read timed out"))
    r = await check(client)
    assert r.error_type == ErrorType.TIMEOUT
    assert r.status_code is None and r.response_time_ms is None


async def test_total_deadline_covers_slow_responses(client, fake_dns, respx_mock: respx.MockRouter) -> None:
    async def slow(request):
        await asyncio.sleep(2)
        return httpx.Response(200)

    respx_mock.get(URL).mock(side_effect=slow)
    r = await check(client, timeout=0.1)
    assert r.error_type == ErrorType.TIMEOUT
    assert r.error_message == "No response within 0.1s"


async def test_connection_refused(client, fake_dns, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).mock(side_effect=httpx.ConnectError("[Errno 111] Connection refused"))
    r = await check(client)
    assert r.error_type == ErrorType.CONNECTION
    assert "Connection refused" in r.error_message


def test_ssl_error_detected_through_exception_chain() -> None:
    # Tested on the classifier directly: respx replaces an exception's __cause__ with
    # its own SideEffectError, so the real httpx -> httpcore -> ssl chain can't be
    # reproduced through the mock. (Verified against expired.badssl.com, see DEVLOG.)
    cause = ssl.SSLCertVerificationError(1, "certificate verify failed")
    cause.verify_message = "certificate has expired"
    try:
        try:
            raise cause
        except ssl.SSLError as e:
            raise httpx.ConnectError("connect failed") from e
    except httpx.ConnectError as exc:
        assert _classify_connect_error(exc) == (ErrorType.SSL, "SSL error: certificate has expired")


def test_ssl_error_detected_from_message_when_cause_is_missing() -> None:
    exc = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    assert _classify_connect_error(exc)[0] == ErrorType.SSL


async def test_unexpected_exception_is_classified_not_raised(client, fake_dns, respx_mock) -> None:
    respx_mock.get(URL).mock(side_effect=RuntimeError("weird"))
    r = await check(client)
    assert r.error_type == ErrorType.UNKNOWN and "weird" in r.error_message


async def test_long_error_messages_are_truncated(client, fake_dns, respx_mock) -> None:
    respx_mock.get(URL).mock(side_effect=httpx.ConnectError("x" * 2000))
    r = await check(client)
    assert len(r.error_message) == 500
