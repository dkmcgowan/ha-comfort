"""Ask an adapter to report a block of itself, over the push channel.

Some settings have no REST route that returns them. Auto Dry is the clear
case: `GET /devices/{serial}/auto-dry` answers null for every zone whatever
the real setting is. The Comfort app does not read it over REST either. It
asks the adapter directly:

    socket.emit('force_adapter_request', deviceSerial, 'autodry')

and the adapter answers on `autodry_update` with the block. The request
types and their answering events come from the app's own
`ForceAdapterRequestType` and `SocketIOEvent` enums.

Read only unless `--set-auto-dry` is passed, which writes through
`relay-command` and then asks for the block again so the result is visible.

Usage:

    python scripts/probe_force_adapter.py
    python scripts/probe_force_adapter.py --block prohibits
    python scripts/probe_force_adapter.py --set-auto-dry on --serial SERIAL1
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

# ForceAdapterRequestType, and the event each answer arrives on.
BLOCK_EVENTS = {
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


async def probe_block(
    block: str, seconds: int, app_version: str, set_auto_dry: str | None, only: str | None
) -> int:
    """Ask every adapter for one block and print the answers."""
    env = load_env()
    probe = Probe(app_version)
    if not probe.login(env["KUMO_USERNAME"], env["KUMO_PASSWORD"]):
        print("login failed", file=sys.stderr)
        return 1

    status, sites = probe.request("GET", "/sites/")
    if status != 200 or not sites:
        print("could not list sites", file=sys.stderr)
        return 1

    names: dict[str, str] = {}
    for site in sites:
        status, zones = probe.request("GET", f"/sites/{site['id']}/zones")
        if status != 200:
            continue
        for zone in zones:
            if zone.get("adapter"):
                names[zone["adapter"]["deviceSerial"]] = zone.get("name", "?")

    serials = [s for s in names if only is None or s == only]
    if not serials:
        print(f"no such device: {only}", file=sys.stderr)
        return 1

    answer_event = BLOCK_EVENTS[block]
    answers: dict[str, dict] = {}

    # The answers do not say which device they are about, so they are matched
    # to requests in the order those went out. Verified against `prohibits`,
    # where four requests came back as four answers in the order asked.
    awaiting: list[str] = []

    sio = socketio.AsyncClient()

    @sio.event
    async def connect() -> None:
        print(f"connected, transport {sio.transport()}")

    @sio.event
    async def connect_error(data: object) -> None:
        print(f"connect error: {data}", file=sys.stderr)

    async def on_answer(*args: object) -> None:
        stamp = time.strftime("%H:%M:%S")
        for arg in args:
            items = arg if isinstance(arg, list) else [arg]
            for payload in items:
                if not isinstance(payload, dict):
                    continue
                serial = payload.get("deviceSerial")
                if not serial and awaiting:
                    serial = awaiting.pop(0)
                if not serial:
                    print(f"[{stamp}] {answer_event} unattributable: "
                          f"{json.dumps(payload, default=str)}")
                    continue
                answers[serial] = payload
                print(f"[{stamp}] {answer_event} {names.get(serial, serial)}: "
                      f"{json.dumps(payload, default=str)}")

    sio.on(answer_event, on_answer)

    await sio.connect(
        SOCKET_URL,
        headers={"Authorization": f"Bearer {probe.access}"},
        transports=["websocket"],
    )
    for serial in serials:
        await sio.emit("subscribe", serial)
    await asyncio.sleep(2)

    if set_auto_dry is not None:
        enable = set_auto_dry == "on"
        for serial in serials:
            body = {"serial": serial, "adapter": {"autodry": {"enable": enable}}}
            status, _ = probe.request(
                "POST", f"/devices/{serial}/relay-command", body
            )
            print(f"write {names.get(serial, serial)} enable={enable}: HTTP {status}")
        await asyncio.sleep(3)

    print(f"\nasking {len(serials)} device(s) for '{block}', "
          f"waiting {seconds}s on '{answer_event}'")
    for serial in serials:
        awaiting.append(serial)
        await sio.emit("force_adapter_request", (serial, block))

    await asyncio.sleep(seconds)
    await sio.disconnect()

    print("\nresult:")
    for serial in serials:
        label = names.get(serial, serial)
        if serial in answers:
            print(f"  {label}: {json.dumps(answers[serial], default=str)}")
        else:
            print(f"  {label}: no answer")
    return 0


def main() -> int:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block", default="autodry", choices=sorted(BLOCK_EVENTS))
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--app-version", default="3.5.0")
    parser.add_argument("--set-auto-dry", choices=["on", "off"])
    parser.add_argument("--serial", help="limit to one device")
    args = parser.parse_args()
    return asyncio.run(
        probe_block(
            args.block, args.seconds, args.app_version, args.set_auto_dry, args.serial
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
