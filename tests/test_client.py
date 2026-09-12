import httpx
import pytest

from bganalyzer.nightscout.client import NightscoutClient, NightscoutError, validate_origin


class Credentials:
    def get_token(self):
        return "synthetic-private-secret"


def client(config, handler):
    result = NightscoutClient(config.nightscout, config.sync, Credentials())
    result._client = httpx.Client(
        base_url=result.origin + "/", transport=httpx.MockTransport(handler)
    )
    return result


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test",
        "https://user:pass@example.test",
        "https://example.test?token=x",
        "https://example.test#fragment",
        "https://example.test:bad",
    ],
)
def test_rejects_unsafe_origin(url):
    with pytest.raises(ValueError):
        validate_origin(url)


def test_no_write_and_no_arbitrary_origin(config):
    c = client(config, lambda request: pytest.fail("must not send"))
    for method, path in [("POST", "api/v1/entries"), ("GET", "https://other.test/api/v1/entries")]:
        with pytest.raises(NightscoutError):
            c._request(method, path)
    c.close()


def test_subpath_and_utc_dates(config):
    def handler(request):
        assert request.url.path == "/nightscout/api/v1/treatments.json"
        assert request.url.params["find[created_at][$gte]"] == "1970-01-01T00:00:00Z"
        assert "api-secret" not in request.headers
        return httpx.Response(200, json=[])

    with client(config, handler) as c:
        assert c.fetch_treatments(0, 1000) == []


def test_redirect_refused(config):
    with client(
        config, lambda r: httpx.Response(302, headers={"Location": "https://other.test"})
    ) as c:
        with pytest.raises(NightscoutError):
            c.get_status()


def test_size_limit(config):
    config.nightscout.max_body_size = 4
    with client(config, lambda r: httpx.Response(200, json={"large": "response"})) as c:
        with pytest.raises(NightscoutError, match="size"):
            c.get_status()


def test_secret_hashed_header_only(config):
    config.nightscout.auth_mode = "api_secret"

    def handler(request):
        assert request.headers["api-secret"] == NightscoutClient._sha1_digest(
            "synthetic-private-secret"
        )
        assert "secret" not in str(request.url)
        return httpx.Response(200, json={})

    with client(config, handler) as c:
        c.get_status()


def test_compressed_json_is_not_decompressed_twice(config):
    import gzip

    with client(
        config,
        lambda r: httpx.Response(
            200,
            content=gzip.compress(b'{"version":"test"}'),
            headers={"content-type": "application/json", "content-encoding": "gzip"},
        ),
    ) as c:
        assert c.get_status() == {"version": "test"}


def test_oversized_query_rejected_before_network(config):
    with client(config, lambda r: pytest.fail("oversized request must not be sent")) as c:
        with pytest.raises(NightscoutError) as exc:
            c.fetch_entries(0, 1000, excluded_ids=[f"{i:024x}" for i in range(500)])
        assert exc.value.error_code == "REQUEST_TOO_LONG"


def test_retry_wait_is_cancellable(config):
    from bganalyzer.nightscout.client import interruptible_wait
    import time

    start = time.monotonic()
    with pytest.raises(NightscoutError) as exc:
        interruptible_wait(300, lambda: True)
    assert exc.value.error_code == "CANCELLED"
    assert time.monotonic() - start < 0.5
