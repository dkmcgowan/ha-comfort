"""Mitsubishi-specific Fahrenheit/Celsius conversion.

Mitsubishi systems use 0.5 °C steps internally, but their F-to-C mapping
diverges from standard arithmetic at several setpoints (64–66 °F and
69–72 °F). These lookup tables match the Comfort app and the physical
remote exactly; values outside the tables fall back to standard rounding.
"""

from __future__ import annotations

# Fahrenheit -> Celsius setpoint mapping (61–80 °F).
F_TO_C: dict[int, float] = {
    61: 16.0, 62: 16.5, 63: 17.0, 64: 17.5, 65: 18.0, 66: 18.5,
    67: 19.5, 68: 20.0, 69: 21.0, 70: 21.5, 71: 22.0, 72: 22.5,
    73: 23.0, 74: 23.5, 75: 24.0, 76: 24.5, 77: 25.0, 78: 25.5,
    79: 26.0, 80: 26.5,
}

# Celsius -> Fahrenheit display mapping. NOT a simple inverse of F_TO_C:
# Mitsubishi's C->F mapping for room-temperature display diverges from the
# setpoint mapping at certain values (e.g. 19.0 °C = 67 °F display, but
# 67 °F = 19.5 °C setpoint).
C_TO_F: dict[float, int] = {
    16.0: 61, 16.5: 62, 17.0: 63, 17.5: 64, 18.0: 65, 18.5: 66,
    19.0: 67, 19.5: 67, 20.0: 68, 20.5: 69,
    21.0: 69, 21.5: 70, 22.0: 71, 22.5: 72,
    23.0: 73, 23.5: 74, 24.0: 75, 24.5: 76, 25.0: 77, 25.5: 78,
    26.0: 79, 26.5: 80,
}


def c_to_f(celsius: float | None) -> float | None:
    """Convert Celsius to Fahrenheit using Mitsubishi's lookup table.

    Falls back to standard rounding for values outside the table
    (e.g. current room-temperature readings that are not exact setpoints).
    """
    if celsius is None:
        return None
    if celsius in C_TO_F:
        return C_TO_F[celsius]
    return round(celsius * 9.0 / 5.0 + 32.0)


def f_to_c(fahrenheit: float | None) -> float | None:
    """Convert Fahrenheit to Celsius using Mitsubishi's lookup table.

    Falls back to standard rounding for values outside the table.
    """
    if fahrenheit is None:
        return None
    f_int = int(round(fahrenheit))
    if f_int in F_TO_C:
        return F_TO_C[f_int]
    celsius = (fahrenheit - 32.0) * 5.0 / 9.0
    return round(celsius * 2.0) / 2.0
