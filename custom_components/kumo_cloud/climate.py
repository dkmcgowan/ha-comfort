"""Climate platform for Kumo Cloud HVAC units."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate.const import (
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DOMAIN,
    OPERATION_MODE_AUTO,
    OPERATION_MODE_AUTO_COOL,
    OPERATION_MODE_AUTO_HEAT,
    OPERATION_MODE_COOL,
    OPERATION_MODE_DRY,
    OPERATION_MODE_HEAT,
    OPERATION_MODE_OFF,
    OPERATION_MODE_VENT,
)
from .coordinator import KumoCloudConfigEntry, KumoCloudDevice
from .entity import KumoCloudEntity
from .last_hvac_mode import recall as recall_last_hvac_mode, remember as remember_last_hvac_mode
from .temperature import c_to_f, f_to_c
from .whole_home import KumoCloudWholeHomeClimate

_LOGGER = logging.getLogger(__name__)


# =============================================================================
# Fan speed mapping: Kumo Cloud API values <-> Comfort app UI labels
# =============================================================================
# The V3 API uses internal speed names that don't match what the Comfort app
# or physical remote displays. This mapping translates between the two.

API_TO_UI_FAN = {
    "auto": "auto",
    "superQuiet": "quiet",       # vendor "superQuiet"    -> UI "quiet"
    "quiet": "low",              # vendor "quiet"         -> UI "low"
    "low": "medium",             # vendor "low"           -> UI "medium"
    "powerful": "high",          # vendor "powerful"      -> UI "high"
    "superPowerful": "powerful", # vendor "superPowerful" -> UI "powerful"
}
UI_TO_API_FAN = {
    "auto": "auto",
    "quiet": "superQuiet",
    "low": "quiet",
    "medium": "low",
    "high": "powerful",
    "powerful": "superPowerful",
}
# Order matters for HomeKit bucketing; keep low->high progression
UI_FAN_ORDER = ["auto", "quiet", "low", "medium", "high", "powerful"]


# =============================================================================
# Vane (air direction) mapping: Kumo Cloud API values <-> Comfort app UI labels
# =============================================================================

API_TO_UI_VANE = {
    "auto": "auto",
    "swing": "swing",
    "vertical": "lowest",
    "midvertical": "low",
    "midpoint": "middle",
    "midhorizontal": "high",
    "horizontal": "highest",
}
UI_TO_API_VANE = {
    "auto": "auto",
    "swing": "swing",
    "lowest": "vertical",
    "low": "midvertical",
    "middle": "midpoint",
    "high": "midhorizontal",
    "highest": "horizontal",
}
UI_VANE_ORDER = ["auto", "swing", "lowest", "low", "middle", "high", "highest"]


# =============================================================================
# HVAC mode mappings
# =============================================================================

KUMO_TO_HVAC_MODE = {
    OPERATION_MODE_OFF: HVACMode.OFF,
    OPERATION_MODE_COOL: HVACMode.COOL,
    OPERATION_MODE_HEAT: HVACMode.HEAT,
    OPERATION_MODE_DRY: HVACMode.DRY,
    OPERATION_MODE_VENT: HVACMode.FAN_ONLY,
    OPERATION_MODE_AUTO: HVACMode.HEAT_COOL,
    OPERATION_MODE_AUTO_COOL: HVACMode.HEAT_COOL,
    OPERATION_MODE_AUTO_HEAT: HVACMode.HEAT_COOL,
}

HVAC_TO_KUMO_MODE = {
    HVACMode.OFF: OPERATION_MODE_OFF,
    HVACMode.COOL: OPERATION_MODE_COOL,
    HVACMode.HEAT: OPERATION_MODE_HEAT,
    HVACMode.DRY: OPERATION_MODE_DRY,
    HVACMode.FAN_ONLY: OPERATION_MODE_VENT,
    HVACMode.HEAT_COOL: OPERATION_MODE_AUTO,
}

# =============================================================================
# HVAC action inference
# =============================================================================
# The Kumo Cloud REST API does not expose a "compressor running" signal.
# IDLE is inferred from the current-vs-target temperature delta using
# a 1.0 °F deadband.

HVAC_ACTION_DEADBAND_F = 1.0

# Modes that map directly to an action with no delta-based IDLE.
_DIRECT_MODE_ACTIONS: dict[str, HVACAction] = {
    OPERATION_MODE_DRY: HVACAction.DRYING,
    OPERATION_MODE_VENT: HVACAction.FAN,
}

# Modes with temperature-based IDLE inference. The tuple is
# (action-when-active, setpoint-property-name, sign) where
# sign = +1 -> HEATING (IDLE when current >= target + deadband)
# sign = -1 -> COOLING (IDLE when current <= target - deadband)
_DELTA_MODE_ACTIONS: dict[str, tuple[HVACAction, str, int]] = {
    OPERATION_MODE_HEAT:      (HVACAction.HEATING, "target_temperature",      +1),
    OPERATION_MODE_AUTO_HEAT: (HVACAction.HEATING, "target_temperature_low",  +1),
    OPERATION_MODE_COOL:      (HVACAction.COOLING, "target_temperature",      -1),
    OPERATION_MODE_AUTO_COOL: (HVACAction.COOLING, "target_temperature_high", -1),
}

# Throttle service calls so a Lovelace card mashing set_temperature does
# not pile up concurrent requests against the cloud API.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KumoCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Kumo Cloud climate devices.

    Adding on every refresh rather than only at setup, so a zone created in
    the Comfort app after Home Assistant started still appears without a
    manual reload of the config entry.
    """
    coordinator = entry.runtime_data
    known: set[str] = set()
    whole_home: list[KumoCloudWholeHomeClimate] = []

    @callback
    def _async_add_new_entities() -> None:
        """Create climate entities for zones we have not seen before."""
        new: list[KumoCloudClimate] = []

        for zone in coordinator.zones:
            adapter = zone.get("adapter")
            if not adapter:
                continue

            device = KumoCloudDevice(coordinator, zone["id"], adapter["deviceSerial"])
            if device.unique_id in known:
                continue
            known.add(device.unique_id)
            new.append(KumoCloudClimate(device))

        if not new:
            return

        _LOGGER.debug("Adding %d new climate entities", len(new))

        if whole_home:
            # Zones discovered later join the existing whole home entity
            # rather than producing a second one.
            whole_home[0].add_members(new)
            async_add_entities(new)
            return

        entity = KumoCloudWholeHomeClimate(coordinator, list(new))
        whole_home.append(entity)
        async_add_entities([*new, entity])

    _async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


class KumoCloudClimate(KumoCloudEntity, ClimateEntity):
    """Representation of a Kumo Cloud climate device."""

    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_name = None
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, device: KumoCloudDevice) -> None:
        """Initialize the climate device."""
        super().__init__(device)
        self._attr_unique_id = device.unique_id

        # Set up supported features based on device profile
        self._setup_supported_features()

    def _setup_supported_features(self) -> None:
        """Set up supported features based on device capabilities."""
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )

        profile_data = self._profile
        if profile_data:
            # Check for fan speed support
            if profile_data.get("numberOfFanSpeeds", 0) > 0:
                features |= ClimateEntityFeature.FAN_MODE

            # Check for vane/swing support
            if profile_data.get("hasVaneSwing", False):
                features |= ClimateEntityFeature.SWING_MODE
            if profile_data.get("hasVaneDir", False):
                features |= ClimateEntityFeature.SWING_MODE

            # Check if device supports both heat and cool (for dual setpoint support)
            if profile_data.get("hasModeHeat", False):
                features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE

        self._attr_supported_features = features

    # ---- Device capabilities -------------------------------------------------

    @property
    def _profile(self) -> dict[str, Any]:
        """Return the unit's capability profile, or an empty dict."""
        profile = self.device.profile_data
        if not profile:
            return {}
        return profile[0] if isinstance(profile, list) else profile

    @property
    def _uses_setpoint_in_dry(self) -> bool:
        """Return True if this unit accepts a setpoint while in dry mode.

        Not every Mitsubishi unit does. The ones that do reuse `spCool`,
        which is the value the Comfort app shows and edits in dry mode;
        there is no separate dry setpoint field anywhere in the API.
        """
        return bool(self._profile.get("usesSetPointInDryMode", False))

    def _setpoint(self, field: str) -> float | None:
        """Read a setpoint, preferring the device record over the zone adapter.

        The command cache writes into the device record, so reading the
        adapter first would show the pre-command value for a minute and
        undo the very bounce the cache exists to prevent.
        """
        adapter = self.device.zone_data.get("adapter", {})
        value = self.device.device_data.get(field, adapter.get(field))
        return c_to_f(value)

    # ---- Temperature properties ---------------------------------------------

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature (converted to Fahrenheit)."""
        adapter = self.device.zone_data.get("adapter", {})
        return c_to_f(adapter.get("roomTemp"))

    @property
    def current_humidity(self) -> float | None:
        """Return the current humidity from the wireless sensor, if present.

        The API reports five decimal places. A thermostat shows a whole
        percent, and the spare digits are noise from the sensor rather than
        precision, so they are rounded off here. The standalone humidity
        sensor entity keeps a decimal for anyone who wants to graph it.
        """
        adapter = self.device.zone_data.get("adapter", {})
        device_data = self.device.device_data
        humidity = device_data.get("humidity", adapter.get("humidity"))
        return None if humidity is None else round(humidity)

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature for single-setpoint modes."""
        hvac_mode = self.hvac_mode

        if hvac_mode == HVACMode.COOL:
            return self._setpoint("spCool")
        if hvac_mode == HVACMode.HEAT:
            return self._setpoint("spHeat")
        if hvac_mode == HVACMode.DRY and self._uses_setpoint_in_dry:
            # Dry reuses the cool setpoint. Returning None on a unit that
            # does not support one is what makes Home Assistant hide the
            # control rather than offer a slider that does nothing.
            return self._setpoint("spCool")

        # HEAT_COOL uses target_temperature_high/low instead
        return None

    @property
    def target_temperature_high(self) -> float | None:
        """Return the upper bound temperature for heat/cool mode."""
        if self.hvac_mode == HVACMode.HEAT_COOL:
            adapter = self.device.zone_data.get("adapter", {})
            device_data = self.device.device_data
            return c_to_f(device_data.get("spCool", adapter.get("spCool")))
        return None

    @property
    def target_temperature_low(self) -> float | None:
        """Return the lower bound temperature for heat/cool mode."""
        if self.hvac_mode == HVACMode.HEAT_COOL:
            adapter = self.device.zone_data.get("adapter", {})
            device_data = self.device.device_data
            return c_to_f(device_data.get("spHeat", adapter.get("spHeat")))
        return None

    @property
    def _limit_key(self) -> str | None:
        """Return which of the profile's setpoint ranges applies right now.

        The profile carries a separate range per mode, and they genuinely
        differ: one unit here allows heat down to 10 C but cool only to 16 C.
        Merging them with min() and max() would offer a cooling setpoint the
        unit will not accept.
        """
        return {
            HVACMode.COOL: "cool",
            HVACMode.DRY: "cool",
            HVACMode.HEAT: "heat",
            HVACMode.HEAT_COOL: "auto",
        }.get(self.hvac_mode)

    @property
    def min_temp(self) -> float:
        """Return minimum temperature for the current mode."""
        limits = self._profile.get("minimumSetPoints", {})
        if not limits:
            return c_to_f(16.0)
        key = self._limit_key
        # Off and fan-only have no setpoint of their own, so report the
        # widest range the unit supports rather than an arbitrary one.
        if key is None or key not in limits:
            return c_to_f(min(limits.values()))
        return c_to_f(limits[key])

    @property
    def max_temp(self) -> float:
        """Return maximum temperature for the current mode."""
        limits = self._profile.get("maximumSetPoints", {})
        if not limits:
            return c_to_f(30.0)
        key = self._limit_key
        if key is None or key not in limits:
            return c_to_f(max(limits.values()))
        return c_to_f(limits[key])

    @property
    def target_temperature_step(self) -> float:
        """Return the supported step of target temperature."""
        return 1.0  # 1 F steps (maps to ~0.5 C steps internally)

    # ---- HVAC mode ----------------------------------------------------------

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        adapter = self.device.zone_data.get("adapter", {})
        device_data = self.device.device_data

        operation_mode = device_data.get(
            "operationMode", adapter.get("operationMode", OPERATION_MODE_OFF)
        )
        power = device_data.get("power", adapter.get("power", 0))

        # If power is 0, device is off regardless of operation mode
        if power == 0:
            return HVACMode.OFF

        return KUMO_TO_HVAC_MODE.get(operation_mode, HVACMode.OFF)

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available HVAC modes."""
        modes = [HVACMode.OFF]

        profile_data = self._profile
        if profile_data:
            max_setpoints = profile_data.get("maximumSetPoints", {})

            if profile_data.get("hasModeHeat", False) or "heat" in max_setpoints:
                modes.append(HVACMode.HEAT)
            if profile_data.get("hasModeCool", False) or "cool" in max_setpoints:
                modes.append(HVACMode.COOL)
            if profile_data.get("hasModeDry", False):
                modes.append(HVACMode.DRY)
            if profile_data.get("hasModeFan", False) or profile_data.get("hasModeVent", False):
                modes.append(HVACMode.FAN_ONLY)
            if profile_data.get("hasModeAuto", False) or "auto" in max_setpoints:
                modes.append(HVACMode.HEAT_COOL)
        else:
            modes.extend([HVACMode.HEAT, HVACMode.COOL])

        return modes

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current running HVAC operation."""
        device_data = self.device.device_data
        adapter = self.device.zone_data.get("adapter", {})

        operation_mode = device_data.get(
            "operationMode", adapter.get("operationMode", OPERATION_MODE_OFF)
        )
        power = device_data.get("power", adapter.get("power", 0))

        if operation_mode == OPERATION_MODE_OFF or power == 0:
            return HVACAction.OFF

        if operation_mode in _DIRECT_MODE_ACTIONS:
            return _DIRECT_MODE_ACTIONS[operation_mode]

        if operation_mode in _DELTA_MODE_ACTIONS:
            action, setpoint_attr, sign = _DELTA_MODE_ACTIONS[operation_mode]
            current = self.current_temperature
            target = getattr(self, setpoint_attr)
            if current is not None and target is not None:
                if sign > 0 and current >= target + HVAC_ACTION_DEADBAND_F:
                    return HVACAction.IDLE
                if sign < 0 and current <= target - HVAC_ACTION_DEADBAND_F:
                    return HVACAction.IDLE
            return action

        if operation_mode == OPERATION_MODE_AUTO:
            current = self.current_temperature
            target = self.target_temperature_high or self.target_temperature
            if current is not None and target is not None:
                diff = current - target
                if diff > HVAC_ACTION_DEADBAND_F:
                    return HVACAction.COOLING
                if diff < -HVAC_ACTION_DEADBAND_F:
                    return HVACAction.HEATING

        return HVACAction.IDLE

    # ---- Fan mode -----------------------------------------------------------

    @property
    def fan_mode(self) -> str | None:
        """Return current fan mode (canonical lowercase UI label)."""
        device_data = self.device.device_data
        adapter = self.device.zone_data.get("adapter", {})
        fan_speed = device_data.get("fanSpeed", adapter.get("fanSpeed"))
        _LOGGER.debug("API returned fanSpeed for %s: %s", self.device.device_serial, fan_speed)
        ui_label = API_TO_UI_FAN.get(fan_speed, fan_speed)
        _LOGGER.debug("HA presenting fan mode for %s as: %s", self.device.device_serial, ui_label)
        return ui_label

    @property
    def fan_modes(self) -> list[str]:
        """Return the list of available fan modes."""
        return UI_FAN_ORDER.copy()

    # ---- Swing (vane) mode --------------------------------------------------

    @property
    def swing_mode(self) -> str | None:
        """Return current vane position (canonical lowercase UI label)."""
        device_data = self.device.device_data
        adapter = self.device.zone_data.get("adapter", {})
        swing = device_data.get("airDirection", adapter.get("airDirection"))
        _LOGGER.debug("API returned airDirection for %s: %s", self.device.device_serial, swing)
        return API_TO_UI_VANE.get(swing, swing)

    @property
    def swing_modes(self) -> list[str] | None:
        """Return the list of available swing modes."""
        profile_data = self._profile
        if not profile_data:
            return None

        if not (profile_data.get("hasVaneDir", False) or profile_data.get("hasVaneSwing", False)):
            return None

        return UI_VANE_ORDER.copy()

    # ---- Misc properties ----------------------------------------------------

    @property
    def available(self) -> bool:
        """Return True if entity is available.

        Keep entity available when we have data even if the last poll failed.
        This prevents automations from triggering spuriously when the entity
        flickers between available/unavailable due to transient API errors.
        """
        has_data = (
            self.device.zone_data
            and self.device.device_data
            and self.coordinator.data is not None
        )
        return has_data and self.device.available

    # ---- Commands -----------------------------------------------------------

    async def _send_command_and_refresh(self, commands: dict[str, Any]) -> None:
        """Send command, cache it to prevent bounce, and refresh."""
        _LOGGER.debug("HA sending command to %s: %s", self.device.device_serial, commands)

        # Cache the command first so UI updates immediately
        self.device.cache_commands(commands)
        self.async_write_ha_state()

        # Send the command and refresh the device
        await self.device.send_command(commands)

        # Write state again after refresh
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target HVAC mode."""
        remember_last_hvac_mode(self.hass, self._attr_unique_id, hvac_mode)
        if hvac_mode == HVACMode.OFF:
            await self._send_command_and_refresh({"operationMode": OPERATION_MODE_OFF})
        else:
            kumo_mode = HVAC_TO_KUMO_MODE.get(hvac_mode)
            if kumo_mode:
                commands = {"operationMode": kumo_mode}

                # Include current setpoints to maintain them
                adapter = self.device.zone_data.get("adapter", {})
                device_data = self.device.device_data

                sp_cool = device_data.get("spCool", adapter.get("spCool"))
                sp_heat = device_data.get("spHeat", adapter.get("spHeat"))

                if sp_cool is not None:
                    commands["spCool"] = sp_cool
                if sp_heat is not None:
                    commands["spHeat"] = sp_heat

                await self._send_command_and_refresh(commands)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        adapter = self.device.zone_data.get("adapter", {})
        device_data = self.device.device_data
        commands: dict[str, Any] = {}

        # Range set (preferred for HEAT_COOL / auto)
        low_f = kwargs.get(ATTR_TARGET_TEMP_LOW)
        high_f = kwargs.get(ATTR_TARGET_TEMP_HIGH)

        if low_f is not None or high_f is not None:
            current_low_c = device_data.get("spHeat", adapter.get("spHeat"))
            current_high_c = device_data.get("spCool", adapter.get("spCool"))

            if low_f is not None:
                commands["spHeat"] = f_to_c(low_f)
            elif current_low_c is not None:
                commands["spHeat"] = current_low_c

            if high_f is not None:
                commands["spCool"] = f_to_c(high_f)
            elif current_high_c is not None:
                commands["spCool"] = current_high_c

            if commands:
                await self._send_command_and_refresh(commands)
            return

        # Single setpoint (heat/cool modes)
        target_temp_f = kwargs.get(ATTR_TEMPERATURE)
        if target_temp_f is None:
            return

        target_temp_c = f_to_c(target_temp_f)
        hvac_mode = self.hvac_mode

        # Dry reuses the cool setpoint on units that accept one at all.
        if hvac_mode in (HVACMode.COOL, HVACMode.DRY):
            if hvac_mode == HVACMode.DRY and not self._uses_setpoint_in_dry:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="no_setpoint_in_dry",
                    translation_placeholders={"name": self.device.name},
                )
            commands["spCool"] = target_temp_c
            sp_heat = device_data.get("spHeat", adapter.get("spHeat"))
            if sp_heat is not None:
                commands["spHeat"] = sp_heat

        elif hvac_mode == HVACMode.HEAT:
            commands["spHeat"] = target_temp_c
            sp_cool = device_data.get("spCool", adapter.get("spCool"))
            if sp_cool is not None:
                commands["spCool"] = sp_cool

        elif hvac_mode == HVACMode.HEAT_COOL:
            # Single setpoint in auto mode: set both with hysteresis
            commands["spCool"] = target_temp_c
            commands["spHeat"] = target_temp_c - 1.0  # ~2 F hysteresis

        else:
            # Off and fan-only have no setpoint. Saying so beats accepting
            # the call and doing nothing, which is what used to happen in
            # dry mode too.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_setpoint_in_mode",
                translation_placeholders={"name": self.device.name, "mode": str(hvac_mode)},
            )

        if commands:
            await self._send_command_and_refresh(commands)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode (accepts UI label, sends API value)."""
        api_value = UI_TO_API_FAN.get(fan_mode.lower(), fan_mode)
        _LOGGER.debug("Setting fan mode: UI '%s' -> API '%s'", fan_mode, api_value)
        await self._send_command_and_refresh({"fanSpeed": api_value})

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set vane position (accepts UI label, sends API value)."""
        api_value = UI_TO_API_VANE.get(swing_mode.lower(), swing_mode)
        _LOGGER.debug("Setting swing mode: UI '%s' -> API '%s'", swing_mode, api_value)
        await self._send_command_and_refresh({"airDirection": api_value})

    async def async_turn_on(self) -> None:
        """Turn the entity on.

        Restores the last mode the user explicitly set if we remember it,
        otherwise falls back to whatever the device reports (or COOL if
        the device is currently OFF).
        """
        adapter = self.device.zone_data.get("adapter", {})
        device_data = self.device.device_data

        last = recall_last_hvac_mode(
            self.hass, self._attr_unique_id, self.hvac_modes
        )
        if last is not None:
            operation_mode = HVAC_TO_KUMO_MODE.get(last, OPERATION_MODE_COOL)
        else:
            operation_mode = device_data.get(
                "operationMode", adapter.get("operationMode", OPERATION_MODE_COOL)
            )
            if operation_mode == OPERATION_MODE_OFF:
                operation_mode = OPERATION_MODE_COOL

        commands = {"operationMode": operation_mode}

        sp_cool = device_data.get("spCool", adapter.get("spCool"))
        sp_heat = device_data.get("spHeat", adapter.get("spHeat"))

        if sp_cool is not None:
            commands["spCool"] = sp_cool
        if sp_heat is not None:
            commands["spHeat"] = sp_heat

        await self._send_command_and_refresh(commands)

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        await self._send_command_and_refresh({"operationMode": OPERATION_MODE_OFF})
