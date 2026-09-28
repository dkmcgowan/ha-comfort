"""Tests for which HTTP verbs the request helper will send.

`reset_filter` is a PATCH, the only one in the integration, and the helper
used to refuse it with `Unsupported method: PATCH` before anything left Home
Assistant. The Reset filter button failed every time. These pin that every
verb the client uses actually goes out.

Needs Home Assistant, which `api.py` imports and which will not install on
Windows, so this runs in CI and skips locally.
"""

import asyncio

import pytest

pytest.importorskip("homeassistant")

# Below the guard on purpose: api.py imports Home Assistant.
from custom_components.kumo_cloud.api import KumoCloudAPI


class FakeResponse:
    """A 200 with a JSON body."""

    content_type = "application/json"

    def __init__(self, body):
        """Remember the body to hand back."""
        self._body = body

    def raise_for_status(self):
        """Raise nothing, as a 200 does."""

    async def json(self):
        """Return the body."""
        return self._body

    async def __aenter__(self):
        """Act as its own context manager, like aiohttp's."""
        return self

    async def __aexit__(self, *exc):
        """Nothing to release."""
        return False


class FakeSession:
    """Stands in for aiohttp's session, recording what was sent."""

    def __init__(self):
        """Start with nothing sent."""
        self.sent = []

    def request(self, method, url, headers=None, json=None):
        """Record a non-GET request."""
        self.sent.append((method, url, json))
        return FakeResponse({"ok": True})

    def get(self, url, headers=None):
        """Record a GET."""
        self.sent.append(("GET", url, None))
        return FakeResponse({"ok": True})


def make_api():
    """Build a client with a token and a fake session, without Home Assistant."""
    api = KumoCloudAPI.__new__(KumoCloudAPI)
    api.session = FakeSession()
    api.base_url = "https://example.invalid"
    api.access_token = "token"
    api.refresh_token = None
    api.token_expires_at = None
    api.username = None
    return api


def run(coro):
    """Run one coroutine on its own loop."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.mark.parametrize("verb", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_every_verb_the_client_uses_is_sent(verb):
    """No verb the client uses is refused before it goes out."""
    api = make_api()
    assert run(api._request(verb, "/zones/Z1/anything", {})) == {"ok": True}
    assert api.session.sent[0][0] == verb


def test_reset_filter_sends_a_patch_to_its_route():
    """The Reset filter button's call reaches the cloud as a PATCH."""
    api = make_api()
    run(api.reset_filter("Z1"))
    method, url, _ = api.session.sent[0]
    assert method == "PATCH"
    assert url.endswith("/zones/Z1/reset-filter")


def test_an_unknown_verb_is_still_refused():
    """The guard still stops a typo."""
    api = make_api()
    with pytest.raises(ValueError, match="Unsupported method"):
        run(api._request("PATH", "/zones/Z1/reset-filter", {}))
