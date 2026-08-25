"""Tests for the Mitsubishi Fahrenheit/Celsius lookup tables.

`temperature.py` is loaded straight off disk rather than imported as
`custom_components.kumo_cloud.temperature`, because that package's
`__init__.py` pulls in aiohttp and Home Assistant. The module itself has no
dependencies, so loading it this way lets these tests run on a bare
`pip install pytest`, including on Windows where importing Home Assistant
fails on `fcntl`.
"""

import importlib.util
import pathlib

import pytest

_PATH = (
    pathlib.Path(__file__).parent.parent
    / "custom_components"
    / "kumo_cloud"
    / "temperature.py"
)
_SPEC = importlib.util.spec_from_file_location("kumo_temperature", _PATH)
temperature = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(temperature)

C_TO_F = temperature.C_TO_F
F_TO_C = temperature.F_TO_C
c_to_f = temperature.c_to_f
f_to_c = temperature.f_to_c


def test_none_passes_through():
    assert c_to_f(None) is None
    assert f_to_c(None) is None


@pytest.mark.parametrize(("fahrenheit", "celsius"), sorted(F_TO_C.items()))
def test_f_to_c_matches_the_table(fahrenheit, celsius):
    assert f_to_c(fahrenheit) == celsius


@pytest.mark.parametrize(("celsius", "fahrenheit"), sorted(C_TO_F.items()))
def test_c_to_f_matches_the_table(celsius, fahrenheit):
    assert c_to_f(celsius) == fahrenheit


def test_tables_are_monotonic():
    """A higher input must never map to a lower output."""
    f_values = [F_TO_C[f] for f in sorted(F_TO_C)]
    assert f_values == sorted(f_values)

    c_values = [C_TO_F[c] for c in sorted(C_TO_F)]
    assert c_values == sorted(c_values)


def test_setpoint_round_trip_is_stable():
    """Every table setpoint survives F -> C -> F unchanged.

    This is the property that matters in practice: a Fahrenheit user moves a
    slider, the value is stored in Celsius, and the slider must not drift when
    that value is read back.
    """
    for fahrenheit in F_TO_C:
        assert c_to_f(f_to_c(fahrenheit)) == fahrenheit


def test_display_mapping_is_deliberately_not_the_inverse():
    """19.0 C reads as 67 F, but 67 F sets 19.5 C.

    The two tables are not inverses of each other, which is intentional:
    Mitsubishi displays room temperature on a different mapping than it uses
    for setpoints. Pinned here so a future "simplification" that collapses
    the tables into one gets caught.
    """
    assert c_to_f(19.0) == 67
    assert f_to_c(67) == 19.5
    assert c_to_f(19.5) == 67


def test_values_outside_the_table_fall_back_to_arithmetic():
    assert c_to_f(0.0) == 32
    assert c_to_f(100.0) == 212
    assert f_to_c(32.0) == 0.0
    assert f_to_c(100.0) == 38.0


def test_fallback_celsius_snaps_to_half_degrees():
    """The units accept 0.5 C steps, so the fallback must not emit finer."""
    for fahrenheit in range(-40, 121):
        celsius = f_to_c(float(fahrenheit))
        assert (celsius * 2) == int(celsius * 2)


class TestCelsiusDeltaToFahrenheit:
    """A temperature difference follows Mitsubishi's step rule, not math.

    One Fahrenheit step is half a Celsius degree throughout their UI, which
    is what `F_TO_C` above encodes for setpoints. `roomTempDisplayOffset`
    obeys the same rule.

    Pinned against a live account on 2026-08-25: an offset set to 5 in the
    Comfort app read back as 2.5, and two zones reading 1 show as 2 there.
    """

    def test_no_offset_stays_no_offset(self):
        """Zero is the case the old code got most visibly wrong."""
        assert temperature.c_delta_to_f(0) == 0.0

    def test_the_value_set_in_the_app_comes_back(self):
        """5 F in the app is stored as 2.5 C, so 2.5 C displays as 5 F."""
        assert temperature.c_delta_to_f(2.5) == 5.0

    def test_a_whole_degree_doubles(self):
        """The two zones reading 1 show as 2 in the app."""
        assert temperature.c_delta_to_f(1) == 2.0

    def test_a_half_step_is_one_degree(self):
        """The smallest step the field holds."""
        assert temperature.c_delta_to_f(0.5) == 1.0

    def test_a_negative_offset_keeps_its_sign(self):
        """A difference has a direction; nothing here should shift it."""
        assert temperature.c_delta_to_f(-1.5) == -3.0

    def test_none_passes_through(self):
        """Matches the other converters, for a field the API left out."""
        assert temperature.c_delta_to_f(None) is None

    def test_it_is_not_the_reading_conversion(self):
        """The old bug: an offset converted as though it were a reading."""
        assert temperature.c_delta_to_f(0) != temperature.c_to_f(0)


class TestRoomTemperatureMatchesTheApp:
    """The room-temperature table beats arithmetic, zone by zone.

    Checked against the Comfort app on 2026-08-25 with every display offset
    cleared. The app shows whole Fahrenheit degrees. Den read 71 and the
    other three read 70, against stored values of 22.0 and 21.5.

    These four are the cases that separate the table from arithmetic, which
    is why they are worth pinning: converting by 9/5 and rounding gives 72
    and 71, so a sensor left as a Celsius native value disagrees with the
    app on every one of them.
    """

    def test_den_reads_seventy_one(self):
        assert c_to_f(22.0) == 71

    def test_the_other_three_read_seventy(self):
        assert c_to_f(21.5) == 70

    def test_arithmetic_would_have_disagreed_on_both(self):
        """Rounded arithmetic gives 72 and 71, which is what we saw wrong."""
        for celsius, seen_in_app in ((22.0, 71), (21.5, 70)):
            assert round(celsius * 9.0 / 5.0 + 32.0) != seen_in_app
            assert c_to_f(celsius) == seen_in_app

    def test_every_stored_step_lands_on_a_whole_degree(self):
        """`roomTemp` moves in half degrees; each must display as an integer.

        Home Assistant converting a Celsius native value produced 71.6 for
        Den, a tenth that exists only as an artifact of the conversion.
        """
        for celsius in C_TO_F:
            assert c_to_f(celsius) == int(c_to_f(celsius))
