"""A single climate entity that drives every zone at the site.

The Comfort app has a "Control all zones" action on the site, and this is
the same idea. Home Assistant has no climate group helper, so anyone wanting
one setpoint for the house otherwise ends up writing a script that loops
over four entities.

**There is no server side group behind this.** The app's action is a client
side fan out, and `/devices/send-command` is per device, so this entity
sends one command per zone exactly as the app does. Zone groups do exist in
the API (`/sites/{id}/groups`) but they are a different feature, they were
empty on the account this was built against, and they do not cover "the
whole site".

Reporting state for a set of units that can disagree is the awkward part.
The rules here, chosen so nothing is ever silently wrong:

- Modes offered are the **intersection** of what every zone supports, so
  this entity never offers a mode some unit would reject. The app does the
  same check and warns "{{mode}} mode is not available for all zones".
- The reported mode is OFF only when every zone is off. Otherwise it is the
  most common mode among the zones that are on.
- The reported setpoint is the shared value when the zones agree and the
  mean when they do not.
- `zones_in_sync` and a per zone breakdown are always in the attributes, so
  a disagreement is visible rather than hidden behind an average.
"""

from __future__ import annotations

from collections import Counter
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from .coordinator import KumoCloudDataUpdateCoordinator
from .entity import KumoCloudSiteEntity

if TYPE_CHECKING:
    # `climate` imports this module to build the entity, so importing it back
    # at runtime is a cycle: Home Assistant loads the climate platform, which
    # imports whole_home, which imports a half-initialized climate. The name
    # is only ever used in annotations, and `from __future__ import
    # annotations` makes those strings, so the type checker still sees it.
    from .climate import KumoCloudClimate

_LOGGER = logging.getLogger(__name__)


class KumoCloudWholeHomeClimate(KumoCloudSiteEntity, ClimateEntity):
    """One thermostat for the whole site."""

    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_name = "All zones"
    _attr_target_temperature_step = 1.0
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        coordinator: KumoCloudDataUpdateCoordinator,
        members: list[KumoCloudClimate],
    ) -> None:
        """Initialize with the per zone climate entities it drives."""
        super().__init__(coordinator)
        self._members = members
        self._attr_unique_id = f"{coordinator.site_id}_all_zones"

    # ---- Membership ---------------------------------------------------

    @property
    def _live(self) -> list[KumoCloudClimate]:
        """Return the member entities that currently have data."""
        return [member for member in self._members if member.available]

    def add_members(self, members: list[KumoCloudClimate]) -> None:
        """Take on zones discovered after setup."""
        self._members.extend(members)

    # ---- State --------------------------------------------------------

    @property
    def available(self) -> bool:
        """Return True while at least one zone is usable."""
        return bool(self._live)

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return only modes every zone supports."""
        live = self._live
        if not live:
            return [HVACMode.OFF]
        shared = set(live[0].hvac_modes)
        for member in live[1:]:
            shared &= set(member.hvac_modes)
        shared.add(HVACMode.OFF)
        # Keep a stable, sensible order rather than set order.
        order = [
            HVACMode.OFF,
            HVACMode.HEAT,
            HVACMode.COOL,
            HVACMode.HEAT_COOL,
            HVACMode.DRY,
            HVACMode.FAN_ONLY,
        ]
        return [mode for mode in order if mode in shared]

    @property
    def hvac_mode(self) -> HVACMode:
        """Return OFF only if every zone is off, else the commonest mode."""
        modes = [member.hvac_mode for member in self._live]
        running = [mode for mode in modes if mode != HVACMode.OFF]
        if not running:
            return HVACMode.OFF
        return Counter(running).most_common(1)[0][0]

    @property
    def current_temperature(self) -> float | None:
        """Return the mean room temperature across the zones."""
        return _mean(
            member.current_temperature
            for member in self._live
            if member.current_temperature is not None
        )

    @property
    def current_humidity(self) -> float | None:
        """Return the mean humidity across the zones that report one."""
        mean = _mean(
            member.current_humidity
            for member in self._live
            if member.current_humidity is not None
        )
        return None if mean is None else round(mean)

    @property
    def target_temperature(self) -> float | None:
        """Return the shared setpoint, or the mean when zones disagree."""
        values = [
            member.target_temperature
            for member in self._live
            if member.target_temperature is not None
        ]
        if not values:
            return None
        if len(set(values)) == 1:
            return values[0]
        mean = _mean(values)
        return None if mean is None else round(mean)

    @property
    def min_temp(self) -> float:
        """Return the highest floor any zone imposes.

        The tightest bound wins, so a value accepted here is accepted
        everywhere.
        """
        live = self._live
        return max((member.min_temp for member in live), default=61.0)

    @property
    def max_temp(self) -> float:
        """Return the lowest ceiling any zone imposes."""
        live = self._live
        return min((member.max_temp for member in live), default=88.0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the per zone truth behind the summary."""
        live = self._live
        modes = [member.hvac_mode for member in live]
        setpoints = [
            member.target_temperature
            for member in live
            if member.target_temperature is not None
        ]
        return {
            "zone_count": len(live),
            "zones_in_sync": len(set(modes)) <= 1 and len(set(setpoints)) <= 1,
            "zones": {
                member.device.name: {
                    "hvac_mode": member.hvac_mode,
                    "current_temperature": member.current_temperature,
                    "target_temperature": member.target_temperature,
                }
                for member in live
            },
        }

    # ---- Commands -----------------------------------------------------

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the mode on every zone."""
        _LOGGER.debug("Whole home: setting %s across %d zones", hvac_mode, len(self._live))
        for member in self._live:
            await member.async_set_hvac_mode(hvac_mode)
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature on every zone.

        A zone whose mode has no setpoint raises, and that must not stop the
        rest, so failures are collected and reported once at the end.
        """
        if kwargs.get(ATTR_TEMPERATURE) is None:
            return

        failures: list[str] = []
        for member in self._live:
            try:
                await member.async_set_temperature(**kwargs)
            except Exception as err:
                failures.append(f"{member.device.name}: {err}")

        if failures:
            _LOGGER.warning(
                "Whole home setpoint did not apply everywhere: %s", "; ".join(failures)
            )
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn every zone on, each restoring its own last mode."""
        for member in self._live:
            await member.async_turn_on()
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Turn every zone off."""
        for member in self._live:
            await member.async_turn_off()
        self.async_write_ha_state()


def _mean(values: Any) -> float | None:
    """Return the mean of an iterable, or None when it is empty."""
    collected = [value for value in values if value is not None]
    if not collected:
        return None
    return sum(collected) / len(collected)
