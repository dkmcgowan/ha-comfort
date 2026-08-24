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

The channel is also how settings that no REST route returns are read. The
app asks an adapter to report a block of itself:

    socket.emit('force_adapter_request', deviceSerial, 'prohibits')

and the server answers on a matching `<block>_update` event. Verified live:
asking for `prohibits` returns the full `local` / `global` / `effective`
state within about a second.

The app throttles each serial and block pair to one request a minute, with
an override flag for a user initiated refresh. That is copied here, since
the throttle is almost certainly there to protect the adapters.

Auto Dry is what sent us looking for this, and it is the one block that
comes back empty. See `ADAPTER_BLOCKS` in `coordinator.py`.

`device_status_v2` is not copied. The app emits it on a 30 s timer while a
device screen is open, to nudge an adapter into reporting, which is a
foreground UI concern that polling already covers.

Polling stays on as a heartbeat. Push is event driven and can go quiet for
long stretches with nothing wrong, so silence cannot be distinguished from a
dead socket without one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import time
from typing import Any

import socketio

_LOGGER = logging.getLogger(__name__)

SOCKET_URL = "https://socket-prod.kumocloud.com/"

# The app's RECONNECT_DELAY_INTERVAL.
RECONNECT_DELAY = 5

# Event names come from the app's SocketIOEvent enum.
EVENT_DEVICE_UPDATE = "device_update"
EVENT_FORCE_ADAPTER_REQUEST = "force_adapter_request"

# The app's ForceAdapterRequestType. The name on the left is the block to ask
# for; the adapter answers on the event named on the right.
FORCE_REQUEST_EVENTS = {
    "autodry": "autodry_update",
    "prohibits": "prohibits_update",
    "adapterStatus": "adapter_update",
    "profile": "profile_update",
    "sensor": "sensor_update",
    "acoil": "acoil_update",
    "systemChangeOver": "system_change_over_update",
    "iuStatus": "device_update",
    "mhk2": "device_update",
}

# The app's own limit, one request a minute per serial and block.
FORCE_REQUEST_INTERVAL = 60.0

# How long to wait for one block answer before moving on, and how often to
# check. Answers were observed arriving in under a second.
ANSWER_TIMEOUT = 5.0
ANSWER_POLL = 0.1

# Answers we parse, mapped back to the block that produces them.
BLOCK_UPDATE_EVENTS = {
    "prohibits_update": "prohibits",
}

# Known but not consumed. Logged so a change at the far end shows up rather
# than passing unnoticed.
OBSERVED_EVENTS = (
    "device_status_v2",
    "adapter_update",
    "profile_update",
    "sensor_update",
    "acoil_update",
    "hold_update",
    "autodry_update",
    "system_change_over_update",
    "notification_channel",
    "app_update_channel",
    "eqc_update",
    "eqc_properties_update",
)


class KumoCloudPush:
    """Keeps a Socket.IO subscription open and reports device updates."""

    def __init__(
        self,
        access_token_provider: Callable[[], str | None],
        token_refresher: Callable[[], Any],
        on_device_update: Callable[[str, dict[str, Any]], None],
        on_block_update: Callable[[str, str, dict[str, Any]], None] | None = None,
    ) -> None:
        """Initialize.

        `access_token_provider` is read at connect time rather than taking a
        token once, because a reconnect after a refresh needs the new one.
        """
        self._access_token = access_token_provider
        self._refresh_token = token_refresher
        self._on_device_update = on_device_update
        self._on_block_update = on_block_update

        self._client: socketio.AsyncClient | None = None
        self._serials: list[str] = []
        self._connected = False
        self._refreshing = False
        self._last_force_request: dict[tuple[str, str], float] = {}
        # The device a block request is currently outstanding for, per
        # answering event. See `_make_block_handler` for why only one can be
        # in flight at a time.
        self._awaiting: dict[str, str] = {}
        self._request_lock = asyncio.Lock()

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
        for event, block in BLOCK_UPDATE_EVENTS.items():
            client.on(event, self._make_block_handler(event, block))
        for event in OBSERVED_EVENTS:
            if event not in BLOCK_UPDATE_EVENTS:
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

    async def async_force_request(
        self, serial: str, block: str, force: bool = False
    ) -> bool:
        """Ask an adapter to report one block of itself.

        Returns whether the request went out. The answer arrives later on
        the block's own event, so a caller that needs the value reads it
        back from the coordinator afterwards.

        **Requests are serialized.** The answers carry no device serial, so
        the only thing tying one to a device is knowing which request is
        outstanding, and answers do not come back in the order asked. See
        `_make_block_handler`. So this waits for each answer before letting
        the next request through, bounded by `ANSWER_TIMEOUT` so a lost
        answer costs one wait rather than wedging the queue. It is slow
        enough that callers should not run it inside a refresh.

        `force` skips the throttle, matching the app's own override for a
        refresh the user asked for.
        """
        if self._client is None or not self._connected:
            return False

        key = (serial, block)
        now = time.monotonic()
        last = self._last_force_request.get(key)
        if last is not None and not force and now - last < FORCE_REQUEST_INTERVAL:
            _LOGGER.debug(
                "Skipping force adapter request for %s %s, last run was %.0fs ago",
                serial,
                block,
                now - last,
            )
            return False

        answer = FORCE_REQUEST_EVENTS.get(block)
        tracked = answer in BLOCK_UPDATE_EVENTS

        async with self._request_lock:
            if self._client is None or not self._connected:
                return False
            if tracked:
                self._awaiting[answer] = serial
            await self._client.emit(EVENT_FORCE_ADAPTER_REQUEST, (serial, block))
            self._last_force_request[key] = now
            _LOGGER.debug("Asked %s to report %s", serial, block)
            if tracked:
                await self._wait_for_answer(answer)

        return True

    async def _wait_for_answer(self, event: str) -> None:
        """Give the server a moment to answer before the next request.

        Answers land in about a second. Waiting past that would only add
        latency, and the request is repeated on the next refresh anyway, so
        a missed one costs nothing but a poll interval.
        """
        for _ in range(int(ANSWER_TIMEOUT / ANSWER_POLL)):
            if self._awaiting.get(event) is None:
                return
            await asyncio.sleep(ANSWER_POLL)
        _LOGGER.debug("No %s came back in time", event)
        self._awaiting.pop(event, None)

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
        """Note the drop. The client's own backoff handles reconnecting.

        Any outstanding request is forgotten, so an answer arriving after a
        reconnect cannot be attributed to whatever was asked before it.
        """
        self._connected = False
        self._awaiting.clear()
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

    def _make_block_handler(self, event: str, block: str) -> Callable[..., Any]:
        """Hand an adapter's answer about one block to the coordinator.

        **The answer does not say which device it is about.** Observed live:
        a `prohibits_update` carries `local`, `global`, `effective` and a
        timestamp and nothing else, even though the app's own handler reads
        a `deviceSerial` off it. So the serial has to come from remembering
        what was asked.

        Matching answers to requests in the order they went out does not
        work. Asking four units at once, with a lockout set on the second,
        brought the lockout back in the third answer. That would have put
        one unit's state on another, which is worse than not reading it at
        all, so requests are serialized instead and only one can be
        outstanding. A serial is still read off the payload when one is
        present, in case the far end starts sending it.
        """

        async def handler(*args: Any) -> None:
            _LOGGER.debug("Push event %s: %s", event, args)
            for payload in _iter_payloads(args):
                serial = payload.get("deviceSerial") or self._awaiting.pop(event, None)
                if not serial:
                    _LOGGER.debug("Unattributable %s, nothing was awaiting it", event)
                    continue

                body = {
                    key: value
                    for key, value in payload.items()
                    if key not in ("deviceSerial", "date")
                }
                if not body:
                    # An empty block is the server saying it holds nothing
                    # for this device, which is not the same as a value.
                    _LOGGER.debug("Empty %s for %s", event, serial)
                    continue
                if self._on_block_update is not None:
                    self._on_block_update(serial, block, body)

        return handler

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
