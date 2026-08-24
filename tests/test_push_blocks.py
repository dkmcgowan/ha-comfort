"""Tests for asking an adapter to report a block, and reading the answer.

The answers do not identify the device they are about, so attribution rests
entirely on only ever having one request outstanding. Matching answers to
requests in order was tried first and is wrong: asking four units at once,
with a lockout set on the second, brought the lockout back in the third
answer. Most of these tests exist to keep that from coming back.

`push.py` is loaded straight off disk for the same reason
`test_push_merge.py` does it: the package's `__init__.py` pulls in Home
Assistant, which cannot be imported on Windows.
"""

import asyncio
import importlib.util
import pathlib
import sys

_PATH = pathlib.Path(__file__).parent.parent / "custom_components" / "kumo_cloud" / "push.py"
_SPEC = importlib.util.spec_from_file_location("kumo_push_blocks", _PATH)
push = importlib.util.module_from_spec(_SPEC)
sys.modules["kumo_push_blocks"] = push
_SPEC.loader.exec_module(push)

# Several of these deliberately never answer, and the real wait is five
# seconds each. Shortened so the suite stays fast; the behavior under test is
# what happens after the wait, not how long it is.
push.ANSWER_TIMEOUT = 0.2


class FakeClient:
    """Records emits instead of sending them.

    `answer_with` makes it reply to a force request the way the server does,
    so a test can drive a full ask and answer cycle.
    """

    def __init__(self, channel=None, answer_with=None):
        """Start with nothing sent."""
        self.emitted = []
        self.channel = channel
        self.answer_with = answer_with

    async def emit(self, event, data=None):
        self.emitted.append((event, data))
        if self.answer_with is None or event != "force_adapter_request":
            return
        serial, block = data
        payload = self.answer_with(serial, block)
        if payload is None:
            return
        handler = self.channel._make_block_handler(
            push.FORCE_REQUEST_EVENTS[block], block
        )
        await handler([payload])


def make_push():
    """Build a client that believes it is connected, with a fake socket."""
    blocks = []
    channel = push.KumoCloudPush(
        access_token_provider=lambda: "token",
        token_refresher=lambda: None,
        on_device_update=lambda serial, payload: None,
        on_block_update=lambda serial, block, payload: blocks.append(
            (serial, block, payload)
        ),
    )
    channel._client = FakeClient()
    channel._connected = True
    return channel, blocks


# A prohibits answer as the server actually sends it: no device serial.
PROHIBITS = {
    "local": {"power": False, "mode": False, "setpoint": False},
    "global": {"power": False, "mode": False, "setpoint": False},
    "effective": {"power": False, "mode": False, "setpoint": False},
    "date": "2026-08-24T22:54:44.691Z",
}


def run(coro):
    """Run one coroutine without disturbing the session's event loop.

    Not `asyncio.run`. That sets the current event loop to None on the way
    out, and under Home Assistant's loop policy the next
    `asyncio.get_event_loop()` then raises instead of making a new one. The
    autouse fixtures in `pytest_homeassistant_custom_component` call exactly
    that, so every test after this file errored in CI. It goes unnoticed
    locally because that package cannot be installed on Windows.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---- Asking ------------------------------------------------------------


def test_request_emits_serial_and_block_positionally():
    """The app sends two positional arguments, not an object."""
    channel, _ = make_push()

    assert run(channel.async_force_request("SERIAL0001", "prohibits")) is True
    assert channel._client.emitted == [
        ("force_adapter_request", ("SERIAL0001", "prohibits"))
    ]


def test_repeat_request_is_throttled():
    """One a minute per serial and block, matching the app."""
    channel, _ = make_push()

    assert run(channel.async_force_request("SERIAL0001", "prohibits")) is True
    assert run(channel.async_force_request("SERIAL0001", "prohibits")) is False
    assert len(channel._client.emitted) == 1


def test_throttle_is_per_serial_and_per_block():
    """A different unit, or a different block, is not the same request."""
    channel, _ = make_push()

    run(channel.async_force_request("SERIAL0001", "prohibits"))
    run(channel.async_force_request("SERIAL0002", "prohibits"))
    run(channel.async_force_request("SERIAL0001", "autodry"))

    assert len(channel._client.emitted) == 3


def test_force_skips_the_throttle():
    """A write needs its confirmation now, not in a minute."""
    channel, _ = make_push()

    run(channel.async_force_request("SERIAL0001", "prohibits"))
    assert (
        run(channel.async_force_request("SERIAL0001", "prohibits", force=True)) is True
    )
    assert len(channel._client.emitted) == 2


def test_no_request_while_disconnected():
    """Nothing is sent, and nothing raises."""
    channel, _ = make_push()
    channel._connected = False

    assert run(channel.async_force_request("SERIAL0001", "prohibits")) is False
    assert channel._client.emitted == []


def test_throttle_does_not_record_a_request_that_never_went_out():
    """A drop must not block the next attempt once the socket is back."""
    channel, _ = make_push()
    channel._connected = False
    run(channel.async_force_request("SERIAL0001", "prohibits"))

    channel._connected = True
    assert run(channel.async_force_request("SERIAL0001", "prohibits")) is True


# ---- Reading the answer ------------------------------------------------


def test_answer_is_attributed_to_what_was_asked():
    """The payload has no serial, so it comes from the pending request."""
    channel, blocks = make_push()
    channel._client = FakeClient(channel, lambda serial, block: PROHIBITS)

    run(channel.async_force_request("SERIAL0001", "prohibits"))

    assert len(blocks) == 1
    serial, block, payload = blocks[0]
    assert serial == "SERIAL0001"
    assert block == "prohibits"
    assert payload["effective"] == {"power": False, "mode": False, "setpoint": False}
    # The timestamp is envelope, not state.
    assert "date" not in payload


def test_each_unit_gets_its_own_answer():
    """The live failure, in miniature.

    Three units, each answering with a value of its own. Every one has to
    land on the unit it came from.
    """
    channel, blocks = make_push()
    serials = ["SERIAL0001", "SERIAL0002", "SERIAL0003"]

    def answer(serial, block):
        return dict(PROHIBITS, effective={"power": serial == "SERIAL0002"})

    channel._client = FakeClient(channel, answer)

    async def ask_all():
        for serial in serials:
            await channel.async_force_request(serial, "prohibits")

    run(ask_all())

    assert [serial for serial, _, _ in blocks] == serials
    locked = {
        serial: payload["effective"]["power"] for serial, _, payload in blocks
    }
    assert locked == {
        "SERIAL0001": False,
        "SERIAL0002": True,
        "SERIAL0003": False,
    }


def test_only_one_request_is_outstanding_at_a_time():
    """The next request must not go out before the last is answered.

    This is the whole basis of attribution, so it is asserted directly
    rather than inferred from the results.
    """
    channel, _ = make_push()
    overlap = []

    def answer(serial, block):
        overlap.append(len([s for s in channel._awaiting.values() if s]))
        return PROHIBITS

    channel._client = FakeClient(channel, answer)

    async def ask_all():
        await asyncio.gather(
            *(
                channel.async_force_request(serial, "prohibits")
                for serial in ("SERIAL0001", "SERIAL0002", "SERIAL0003")
            )
        )

    run(ask_all())

    assert overlap == [1, 1, 1]


def test_an_unanswered_request_does_not_wedge_the_next_one():
    """A lost answer costs a poll interval, not the whole mechanism."""
    channel, blocks = make_push()
    seen = []

    def answer(serial, block):
        seen.append(serial)
        # The first unit never replies.
        return None if serial == "SERIAL0001" else PROHIBITS

    channel._client = FakeClient(channel, answer)

    async def ask_all():
        for serial in ("SERIAL0001", "SERIAL0002"):
            await channel.async_force_request(serial, "prohibits")

    run(ask_all())

    assert seen == ["SERIAL0001", "SERIAL0002"]
    # The stale request must not have claimed the second unit's answer.
    assert [serial for serial, _, _ in blocks] == ["SERIAL0002"]


def test_a_serial_in_the_payload_wins():
    """If the far end starts identifying answers, believe it."""
    channel, blocks = make_push()
    run(channel.async_force_request("SERIAL0001", "prohibits"))

    handler = channel._make_block_handler("prohibits_update", "prohibits")
    run(handler([dict(PROHIBITS, deviceSerial="SERIAL0009")]))

    assert blocks[0][0] == "SERIAL0009"


def test_unexpected_answer_is_dropped():
    """Nothing was asked for, so there is nothing to attribute it to."""
    channel, blocks = make_push()
    handler = channel._make_block_handler("prohibits_update", "prohibits")

    run(handler([PROHIBITS]))

    assert blocks == []


def test_empty_block_is_dropped():
    """This is what Auto Dry answers with, and it is not a value.

    Passing it on would blank whatever is already known about the device.
    """
    channel, blocks = make_push()
    run(channel.async_force_request("SERIAL0001", "prohibits"))

    handler = channel._make_block_handler("prohibits_update", "prohibits")
    run(handler([{"date": "2026-08-24T22:55:58.596Z"}]))

    assert blocks == []


def test_disconnect_forgets_outstanding_requests():
    """A stale entry would misattribute the first answer after reconnect."""
    channel, blocks = make_push()
    run(channel.async_force_request("SERIAL0001", "prohibits"))
    run(channel._handle_disconnect())

    handler = channel._make_block_handler("prohibits_update", "prohibits")
    run(handler([PROHIBITS]))

    assert blocks == []


def test_every_block_event_has_a_request_type_that_produces_it():
    """A handler for an event nothing asks for would never fire."""
    produced = set(push.FORCE_REQUEST_EVENTS.values())
    assert set(push.BLOCK_UPDATE_EVENTS) <= produced


def test_parsed_blocks_are_not_also_treated_as_unhandled():
    """An event cannot be both parsed and merely logged."""
    assert not set(push.BLOCK_UPDATE_EVENTS) & set(push.OBSERVED_EVENTS)
