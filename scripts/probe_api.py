"""Exercise the Kumo Cloud V3 API against a real account.

Everything the integration knows about this API was reverse engineered, so
the only way to be sure of a field or an endpoint is to call it and look.
This script does that, records what came back, and prints a summary.

It is **read only by default**. Every request it makes without `--writes` is
a GET. The write probes change your HVAC, so they are opt in, they say what
they are about to do, and they put the original setting back.

Setup:

    cp scripts/.env.probe.example scripts/.env.probe
    # fill in KUMO_USERNAME and KUMO_PASSWORD

Usage:

    python scripts/probe_api.py                  # read-only sweep
    python scripts/probe_api.py --app-version 3.5.0
    python scripts/probe_api.py --only devices   # one group
    python scripts/probe_api.py --writes         # include write probes

Output goes to `scripts/probe-output-<env>.json`, which is gitignored
because it contains serial numbers, an access token and your site layout.
The console summary prints response keys, not values.

Standard library only, on purpose: this has to run against a bare Python
without touching the Home Assistant environment.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

BASE = "https://app-prod.kumocloud.com"
VERSION = "v3"

# The integration sends 3.2.4. The shipping Android app is 3.5.0, and the
# bundle carries a "general.appVersionTooOld" error string, so the server
# does look at this header.
DEFAULT_APP_VERSION = "3.5.0"

HERE = pathlib.Path(__file__).parent
ENV_FILE = HERE / ".env.probe"
TOKEN_FILE = HERE / ".kumo.token.json"

TIMEOUT = 30


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class Probe:
    """One authenticated session, recording every request it makes."""

    def __init__(self, app_version: str) -> None:
        """Start an unauthenticated session."""
        self.app_version = app_version
        self.access: str | None = None
        self.refresh: str | None = None
        self.log: list[dict] = []

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        auth: bool = True,
        note: str = "",
    ) -> tuple[int, object]:
        """Make one request and record it. Never raises on an HTTP error."""
        url = f"{BASE}/{VERSION}{path}"
        headers = {
            "x-app-version": self.app_version,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if auth and self.access:
            headers["Authorization"] = f"Bearer {self.access}"

        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                status = response.status
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as err:
            status = err.code
            raw = err.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            self.log.append(
                {"method": method, "path": path, "status": None, "error": str(err), "note": note}
            )
            return 0, str(err)

        elapsed = round((time.monotonic() - started) * 1000)
        try:
            parsed: object = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw

        self.log.append(
            {
                "method": method,
                "path": path,
                "status": status,
                "ms": elapsed,
                "note": note,
                "response": parsed,
            }
        )
        return status, parsed

    # -- auth ---------------------------------------------------------------

    def login(self, username: str, password: str) -> bool:
        """Exchange credentials for a token pair."""
        status, body = self.request(
            "POST",
            "/login",
            {"username": username, "password": password, "appVersion": self.app_version},
            auth=False,
            note="authenticate",
        )
        if status != 200 or not isinstance(body, dict):
            return False
        token = body.get("token") or {}
        self.access = token.get("access")
        self.refresh = token.get("refresh")
        return bool(self.access)

    def use_cached_token(self) -> bool:
        """Reuse a token from a previous run if it still works."""
        if not TOKEN_FILE.exists():
            return False
        try:
            cached = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        self.access = cached.get("access")
        self.refresh = cached.get("refresh")
        if not self.access:
            return False
        status, _ = self.request("GET", "/accounts/me", note="validate cached token")
        return status == 200

    def save_token(self) -> None:
        """Cache the token pair so repeated runs do not log in every time."""
        TOKEN_FILE.write_text(
            json.dumps({"access": self.access, "refresh": self.refresh}, indent=2),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def shape(value: object, depth: int = 0) -> str:
    """Describe a response without printing its contents."""
    if isinstance(value, dict):
        keys = list(value)
        if depth == 0:
            return "{" + ", ".join(keys[:24]) + ("..." if len(keys) > 24 else "") + "}"
        return f"dict[{len(keys)}]"
    if isinstance(value, list):
        if not value:
            return "[]"
        return f"[{len(value)} x {shape(value[0], depth + 1)}]"
    if value is None:
        return "null"
    return type(value).__name__


def line(status: int, method: str, path: str, body: object) -> None:
    """Print one result row."""
    mark = {200: "ok ", 201: "ok ", 0: "ERR"}.get(status, str(status))
    detail = shape(body) if status in (200, 201) else ""
    if status not in (200, 201) and isinstance(body, dict):
        detail = str(body.get("message") or body.get("error") or "")[:80]
    print(f"  {mark:>4}  {method:<5} {path:<52} {detail}")


# ---------------------------------------------------------------------------
# Probe groups
# ---------------------------------------------------------------------------


def probe_account(probe: Probe) -> dict:
    """Account level endpoints."""
    print("\n[account]")
    results = {}
    for path in ["/accounts/me", "/accounts/preferences", "/accounts/pin-info"]:
        status, body = probe.request("GET", path)
        line(status, "GET", path, body)
        results[path] = body
    return results


def probe_sites(probe: Probe) -> list[dict]:
    """Site list, which everything else hangs off."""
    print("\n[sites]")
    status, body = probe.request("GET", "/sites/")
    line(status, "GET", "/sites/", body)
    return body if isinstance(body, list) else []


def probe_site_detail(probe: Probe, site_id: str) -> None:
    """Endpoints the app calls against a site."""
    print(f"\n[site {site_id}]")
    paths = [
        f"/sites/{site_id}/zones",
        f"/sites/{site_id}/hold",
        f"/sites/{site_id}/groups",
        f"/sites/{site_id}/schedule-seasons",
        f"/sites/{site_id}/dr-programs",
        f"/sites/{site_id}/kumo-station",
        f"/sites/{site_id}/weather",
        f"/sites/{site_id}/timezone",
    ]
    for path in paths:
        status, body = probe.request("GET", path)
        line(status, "GET", path, body)


def probe_zone(probe: Probe, site_id: str, zone_id: str) -> None:
    """Endpoints the app calls against a zone."""
    print(f"\n[zone {zone_id}]")
    paths = [
        f"/zones/{zone_id}/notification-preferences",
        f"/zones/{zone_id}/schedules",
        f"/zones/{zone_id}/comfort-settings/presets",
        f"/sites/{site_id}/zones/{zone_id}/connection-history",
    ]
    for path in paths:
        status, body = probe.request("GET", path)
        line(status, "GET", path, body)


def probe_device(probe: Probe, serial: str) -> None:
    """Endpoints the app calls against an adapter."""
    print(f"\n[device {serial[:4]}...]")
    paths = [
        f"/devices/{serial}",
        f"/devices/{serial}/profile",
        f"/devices/{serial}/status",
        f"/devices/{serial}/sensor",
        f"/devices/{serial}/kumo-properties",
        f"/devices/{serial}/prohibits",
        f"/devices/{serial}/acoil-settings",
        f"/devices/{serial}/auto-dry-active",
        f"/devices/{serial}/mhk2",
        f"/devices/{serial}/config-key",
        f"/devices/{serial}/recent-connected",
        f"/devices/{serial}/initial",
    ]
    for path in paths:
        status, body = probe.request("GET", path)
        line(status, "GET", path, body)


def probe_app_version(username: str, password: str) -> None:
    """Check whether the version the integration sends is still accepted.

    `const.py` sends 3.2.4. The shipping app sends 3.5.0. The bundle has a
    "general.appVersionTooOld" string, so this is worth knowing before it
    breaks in the field.
    """
    print("\n[app version]")
    for version in ["3.2.4", "3.5.0", "1.0.0", ""]:
        trial = Probe(version)
        ok = trial.login(username, password)
        status = trial.log[-1]["status"]
        label = version or "(empty)"
        print(f"  {'ok ' if ok else str(status):>4}  login with x-app-version {label}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def load_env() -> dict[str, str]:
    """Read scripts/.env.probe, falling back to the real environment."""
    values = {}
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            values[key.strip()] = value.strip().strip("\"'")
    for key in ("KUMO_USERNAME", "KUMO_PASSWORD"):
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def main() -> int:
    """Run the sweep."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-version", default=DEFAULT_APP_VERSION)
    parser.add_argument(
        "--only",
        choices=["account", "sites", "zones", "devices", "version"],
        action="append",
        help="restrict to one group; repeatable",
    )
    parser.add_argument("--writes", action="store_true", help="include write probes")
    parser.add_argument("--fresh-login", action="store_true", help="ignore the cached token")
    parser.add_argument("--out", type=pathlib.Path)
    args = parser.parse_args()

    if args.writes:
        print("Write probes are not implemented yet. Running read-only.", file=sys.stderr)

    env = load_env()
    username = env.get("KUMO_USERNAME") or input("Kumo Cloud username: ").strip()
    password = env.get("KUMO_PASSWORD") or getpass.getpass("Kumo Cloud password: ")

    probe = Probe(args.app_version)

    if args.fresh_login or not probe.use_cached_token():
        print(f"Logging in as {username} with x-app-version {probe.app_version}")
        if not probe.login(username, password):
            last = probe.log[-1]
            print(f"Login failed: {last['status']} {last.get('response')}", file=sys.stderr)
            return 1
        probe.save_token()
        print("Logged in, token cached")
    else:
        print("Reusing cached token")

    groups = set(args.only or ["account", "sites", "zones", "devices", "version"])

    if "account" in groups:
        probe_account(probe)

    sites = probe_sites(probe) if groups & {"sites", "zones", "devices"} else []

    for site in sites:
        site_id = str(site.get("id"))
        if "sites" in groups:
            probe_site_detail(probe, site_id)

        status, zones = probe.request("GET", f"/sites/{site_id}/zones", note="enumerate zones")
        if status != 200 or not isinstance(zones, list):
            continue

        for zone in zones:
            zone_id = str(zone.get("id"))
            adapter = zone.get("adapter") or {}
            serial = adapter.get("deviceSerial")

            if "zones" in groups:
                probe_zone(probe, site_id, zone_id)
            if "devices" in groups and serial:
                probe_device(probe, serial)

    if "version" in groups:
        probe_app_version(username, password)

    out = args.out or HERE / "probe-output-prod.json"
    out.write_text(json.dumps(probe.log, indent=2, default=str), encoding="utf-8")

    ok = sum(1 for entry in probe.log if entry.get("status") in (200, 201))
    print(f"\n{ok}/{len(probe.log)} requests returned a body. Full output: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
