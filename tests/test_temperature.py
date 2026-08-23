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
