"""Config flow for the Kumo Cloud integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .api import KumoCloudAPI, KumoCloudAuthError, KumoCloudConnectionError
from .const import CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN, CONF_SITE_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA_USER = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_auth(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate credentials and return account info.

    Only KumoCloudAuthError / KumoCloudConnectionError propagate -- the
    caller maps them to "invalid_auth" / "cannot_connect" errors in the
    config-flow UI. Other exceptions bubble up to the caller's
    `except Exception` branch, which surfaces an "unknown" error.
    """
    api = KumoCloudAPI(hass)

    login_result = await api.login(
        user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
    )
    account_info = await api.get_account_info()
    sites = await api.get_sites()

    return {
        "login_result": login_result,
        "account_info": account_info,
        "sites": sites,
        "api": api,
    }


class KumoCloudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kumo Cloud."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.data: dict[str, Any] = {}
        self.api: KumoCloudAPI | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_auth(self.hass, user_input)

                self.data.update(user_input)
                self.data.update(info)
                self.api = info["api"]

                # If only one site, auto-select it
                if len(info["sites"]) == 1:
                    site = info["sites"][0]
                    self.data[CONF_SITE_ID] = site["id"]
                    return await self._create_entry()

                # Multiple sites, let user choose
                return await self.async_step_site()

            except KumoCloudAuthError:
                errors["base"] = "invalid_auth"
            except KumoCloudConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA_USER,
            errors=errors,
        )

    async def async_step_site(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle site selection step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self.data[CONF_SITE_ID] = user_input[CONF_SITE_ID]
            return await self._create_entry()

        # Create site selection schema
        sites = self.data["sites"]
        site_options = {site["id"]: site["name"] for site in sites}

        data_schema = vol.Schema({vol.Required(CONF_SITE_ID): vol.In(site_options)})

        return self.async_show_form(
            step_id="site",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"num_sites": str(len(sites))},
        )

    async def _create_entry(self) -> ConfigFlowResult:
        """Create the config entry."""
        # Find the selected site
        selected_site = next(
            site for site in self.data["sites"] if site["id"] == self.data[CONF_SITE_ID]
        )

        # Use username as unique ID
        await self.async_set_unique_id(self.data[CONF_USERNAME])
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"Kumo Cloud - {selected_site['name']}",
            data={
                CONF_USERNAME: self.data[CONF_USERNAME],
                CONF_PASSWORD: self.data[CONF_PASSWORD],
                CONF_SITE_ID: self.data[CONF_SITE_ID],
                CONF_ACCESS_TOKEN: self.api.access_token,
                CONF_REFRESH_TOKEN: self.api.refresh_token,
            },
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle discovery of a Mitsubishi WiFi adapter via DHCP.

        Kumo Cloud is account-scoped (one config entry covers every zone the
        user owns), so we just prompt the user to set up if they haven't
        already, and quietly abort otherwise.
        """
        _LOGGER.debug(
            "Discovered Mitsubishi adapter via DHCP: %s (%s)",
            discovery_info.ip,
            discovery_info.macaddress,
        )
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        return await self.async_step_user()

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle reauth flow."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauth confirmation."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                # Get the original entry data
                entry = self._get_reauth_entry()
                username = entry.data[CONF_USERNAME]

                # Validate new password
                info = await validate_auth(
                    self.hass,
                    {CONF_USERNAME: username, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

                # Update the entry with new tokens
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_ACCESS_TOKEN: info["api"].access_token,
                        CONF_REFRESH_TOKEN: info["api"].refresh_token,
                    },
                )

            except KumoCloudAuthError:
                errors["base"] = "invalid_auth"
            except KumoCloudConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during reauth")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )
