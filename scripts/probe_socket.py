"""Listen to the Kumo Cloud push channel.

The cloud runs a Socket.IO endpoint that pushes device state as it changes,
which is what the Comfort app uses instead of polling. It takes the same
bearer token the REST API does, passed as an ordinary Authorization header,
so no separate handshake or credential is involved.

    socket = io(SOCKET_IO_URL, {extraHeaders: {Authorization: `Bearer ${token}`}})
    socket.emit('subscribe', deviceSerial)

Read only. The only thing this emits is `subscribe`.

Usage:

    pip install "python-socketio[asyncio_client]"
    python scripts/probe_socket.py --seconds 120

Event names come from the app's own SocketIOEvent enum. `device_update` is
the one that carries state; the rest are listed so an unexpected arrival is
visible rather than silently dropped.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

try:
    import socketio
except ImportError:  # pragma: no cover - developer tooling only
    sys.exit('This script needs: pip install "python-socketio[asyncio_client]"')

from probe_api import Probe, load_env

SOCKET_URL = "https://socket-prod.kumocloud.com/"

EVENTS = (
    "subscribed",
    "unsubscribed",
    "device_update",
    "device_status_v2",
    "adapter_update",
    "profile_update",
    "notification_channel",
    "app_update_channel",
    "eqc_update",
    "acoil_update",
    "force_adapter_request",
)


async def listen(seconds: int, app_version: str) -> int:
    """Connect, subscribe to every device on the account, and report."""
    env = load_env()
    probe = Probe(app_version)
    if not probe.login(env["KUMO_USERNAME"], env["KUMO_PASSWORD"]):
        print("login failed", file=sys.stderr)
        return 1

    status, sites = probe.request("GET", "/sites/")
    if status != 200 or not sites:
        print("could not list sites", file=sys.stderr)
        return 1

    serials: list[str] = []
    for site in sites:
        status, zones = probe.request("GET", f"/sites/{site['id']}/zones")
        if status == 200:
            serials += [
                zone["adapter"]["deviceSerial"] for zone in zones if zone.get("adapter")
            ]

    sio = socketio.AsyncClient()
    counts: dict[str, int] = {}

    @sio.event
    async def connect() -> None:
        print(f"connected, transport {sio.transport()}")

    @sio.event
    async def connect_error(data: object) -> None:
        print(f"connect error: {data}", file=sys.stderr)

    def handler_for(name: str):
        async def handler(*args: object) -> None:
            counts[name] = counts.get(name, 0) + 1
            print(f"[{time.strftime('%H:%M:%S')}] {name} {json.dumps(args, default=str)}")

        return handler

    for event in EVENTS:
        sio.on(event, handler_for(event))

    await sio.connect(
        SOCKET_URL,
        headers={"Authorization": f"Bearer {probe.access}"},
        transports=["websocket"],
    )

    for serial in serials:
        await sio.emit("subscribe", serial)
    print(f"subscribed to {len(serials)} devices, listening {seconds}s")

    await asyncio.sleep(seconds)
    await sio.disconnect()

    print("\nevent counts:")
    for name, count in sorted(counts.items()):
        print(f"  {name}: {count}")
    if not counts:
        print("  nothing arrived")
    return 0


def main() -> int:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--app-version", default="3.5.0")
    args = parser.parse_args()
    return asyncio.run(listen(args.seconds, args.app_version))


if __name__ == "__main__":
    raise SystemExit(main())
