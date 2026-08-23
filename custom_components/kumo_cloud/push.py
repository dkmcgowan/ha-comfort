"""Live updates over the Kumo Cloud push channel.

The cloud runs a Socket.IO endpoint that pushes device state as it changes.
It takes the same bearer token the REST API does, passed as an ordinary
Authorization header, so no extra credential or handshake is involved.

    socket = io(SOCKET_URL, {extraHeaders: {Authorization: 'Bearer ' + token}})
    socket.emit('subscribe', deviceSerial)

Shaped after what the Comfort app does, read out of its own bundle:

- On an unauthorized socket it refreshes the token, waits
  `RECONNECT_DELAY_INTERVAL` (5 s in the app), then reconnects.
- Subscriptions are re-sent on every connect, because a reconnect starts a
  new session and the server does not remember them.

Two things this deliberately does not copy. The app emits `device_status_v2`
on a 30 s timer while a device screen is open, to nudge an adapter into
reporting; that is a foreground UI concern and Home Assistant polls anyway.
And it has a `force_adapter_request` emit whose throttling we have not
worked out, so it is left alone.

Polling stays on as a heartbeat. Push is event driven and can go quiet for
long stretches with nothing wrong, so silence cannot be distinguished from a
dead socket without one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
from typing import Any

import socketio

_LOGGER = logging.getLogger(__name__)

SOCKET_URL = "https://socket-prod.kumocloud.com/"

# The app's RECONNECT_DELAY_INTERVAL.
RECONNECT_DELAY = 5

# Event names come from the app's SocketIOEvent enum. `device_update` is the
# only one carrying state we consume today; the others are logged so a change
# at the far end shows up rather than passing unnoticed.
EVENT_DEVICE_UPDATE = "device_update"
OBSERVED_EVENTS = (
    "device_status_v2",
    "adapter_update",
    "profile_update",
    "notification_channel",
    "app_update_channel",
    "eqc_update",
    "acoil_update",
)


class KumoCloudPush:
    """Keeps a Socket.IO subscription open and reports device updates."""

    def __init__(
        self,
        access_token_provider: Callable[[], str | None],
        token_refresher: Callable[[], Any],
        on_device_update: Callable[[str, dict[str, Any]], None],
    ) -> None:
        """Initialize.

        `access_token_provider` is read at connect time rather than taking a
        token once, because a reconnect after a refresh needs the new one.
        """
        self._access_token = access_token_provider
        self._refresh_token = token_refresher
        self._on_device_update = on_device_update

        self._client: socketio.AsyncClient | None = None
        self._serials: list[str] = []
        self._connected = False
        self._refreshing = False

    @property
    def connected(self) -> bool:
        """Return whether the socket is currently up."""
        return self._connected

    async def async_start(self, serials: list[str]) -> bool:
        """Connect and subscribe. Returns False if the socket is unavailable.

        A failure here is not fatal: the caller keeps polling, which is what
        the integration did before this existed.
        """
        self._serials = list(serials)

        client = socketio.AsyncClient(
            reconnection=True,
            reconnection_delay=RECONNECT_DELAY,
            logger=False,
            engineio_logger=False,
        )
        self._client = client

        client.on("connect", self._handle_connect)
        client.on("disconnect", self._handle_disconnect)
        client.on("connect_error", self._handle_connect_error)
        client.on(EVENT_DEVICE_UPDATE, self._handle_device_update)
        for event in OBSERVED_EVENTS:
            client.on(event, self._make_observer(event))

        try:
            await client.connect(
                SOCKET_URL,
                headers=self._headers(),
                transports=["websocket"],
            )
        except (TimeoutError, socketio.exceptions.ConnectionError, OSError) as err:
            _LOGGER.info(
                "Push channel unavailable, falling back to polling only: %s", err
            )
            self._client = None
            return False

        return True

    async def async_stop(self) -> None:
        """Disconnect and forget the client."""
        client, self._client = self._client, None
        self._connected = False
        if client is None:
            return
        try:
            await client.disconnect()
        except (socketio.exceptions.SocketIOError, OSError) as err:
            _LOGGER.debug("Error closing push channel: %s", err)

    async def async_set_serials(self, serials: list[str]) -> None:
        """Subscribe to any device we are not already following."""
        added = [serial for serial in serials if serial not in self._serials]
        self._serials = list(serials)
        if not (added and self._client and self._connected):
            return
        for serial in added:
            await self._client.emit("subscribe", serial)
            _LOGGER.debug("Subscribed to %s over push", serial)

    def _headers(self) -> dict[str, str]:
        """Build the auth header from whatever token is current."""
        return {"Authorization": f"Bearer {self._access_token()}"}

    async def _handle_connect(self) -> None:
        """Re-send every subscription.

        A reconnect is a new session, so the server has forgotten what this
        client was following.
        """
        self._connected = True
        _LOGGER.debug("Push channel connected, subscribing to %d devices", len(self._serials))
        for serial in self._serials:
            await self._client.emit("subscribe", serial)

    async def _handle_disconnect(self, *args: Any) -> None:
        """Note the drop. The client's own backoff handles reconnecting."""
        self._connected = False
        _LOGGER.debug("Push channel disconnected")

    async def _handle_connect_error(self, data: Any = None) -> None:
        """Refresh the token once and let the client retry.

        This is what the app does: an unauthorized socket means the access
        token aged out, so the fix is a new token rather than a retry with
        the same one. The guard stops a burst of errors from starting a
        stampede of refreshes.
        """
        self._connected = False
        _LOGGER.debug("Push channel connect error: %s", data)

        if self._refreshing:
            return
        self._refreshing = True
        try:
            await self._refresh_token()
            await asyncio.sleep(RECONNECT_DELAY)
            if self._client is not None:
                self._client.connection_headers = self._headers()
        except Exception as err:
            _LOGGER.debug("Could not refresh token for push channel: %s", err)
        finally:
            self._refreshing = False

    def _make_observer(self, event: str) -> Callable[..., Any]:
        """Log an event we know about but do not act on yet."""

        async def observer(*args: Any) -> None:
            _LOGGER.debug("Push event %s: %s", event, args)

        return observer

    async def _handle_device_update(self, *args: Any) -> None:
        """Apply a device_update payload.

        Two shapes arrive on this event: a full snapshot matching
        `GET /devices/{serial}`, and a narrower delta. Both are handled the
        same way because the delta is a subset.
        """
        for payload in _iter_payloads(args):
            serial = payload.get("deviceSerial")
            if not serial:
                continue
            self._on_device_update(serial, payload)


def _iter_payloads(args: tuple[Any, ...]) -> list[dict[str, Any]]:
    """Flatten the argument list into device dicts.

    The server sends a list of one, but an event argument is whatever the
    far end put there, so accept a bare dict too.
    """
    payloads: list[dict[str, Any]] = []
    for arg in args:
        if isinstance(arg, dict):
            payloads.append(arg)
        elif isinstance(arg, list):
            payloads.extend(item for item in arg if isinstance(item, dict))
    return payloads


def merge_device_update(current: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Merge a push payload over cached device state.

    **Nulls in a push payload mean "not included", not "cleared".** Observed
    live: two of four adapters reported `spHeat: null` in a delta one second
    after a full snapshot had given them real setpoints, while the other two
    reported their actual values. Applying those nulls would blank the user's
    heat setpoint until the next poll.

    The cost of skipping them is that a field which genuinely becomes null,
    `unusualFigures` clearing when a fault resolves, stays stale until the
    next poll replaces the record wholesale. That is the safer direction to
    be wrong in, and the poll is still running.
    """
    merged = dict(current)
    for key, value in update.items():
        if value is None:
            continue
        merged[key] = value
    return merged
