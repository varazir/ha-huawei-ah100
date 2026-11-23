"""Config flow, OAuth2 Google Health flow, and options flow for Huawei AH100 / Honor CH100 Scale."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow, selector

from .const import (
    CONF_AGE,
    CONF_GENDER,
    CONF_GOOGLE_HEALTH_ENABLED,
    CONF_HEIGHT_CM,
    CONF_INITIAL_WEIGHT,
    CONF_MAC_ADDRESS,
    CONF_TIMEOUT_SECONDS,
    CONF_USER_ID,
    CONF_USER_NAME,
    DEFAULT_AGE,
    DEFAULT_GENDER,
    DEFAULT_HEIGHT_CM,
    DEFAULT_INITIAL_WEIGHT,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_USER_ID,
    DEFAULT_USER_NAME,
    DOMAIN,
    GOOGLE_HEALTH_WRITE_SCOPE,
)

_LOGGER = logging.getLogger(__name__)
MAC_REGEX = re.compile(r"^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$")


def _normalize_mac(mac: str) -> str:
    clean = mac.strip().replace("-", ":").upper()
    if not MAC_REGEX.match(clean):
        raise ValueError("invalid_mac")
    return clean


class HuaweiAH100ConfigFlow(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle a config flow for Huawei AH100 / Honor CH100 Scale with optional Google Health OAuth2."""

    DOMAIN = DOMAIN
    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._discovered_mac: str | None = None
        self._discovered_name: str | None = None
        self._pending_scale_data: dict[str, Any] | None = None
        self._reconfigure_entry: config_entries.ConfigEntry | None = None
        self._reauth_entry: config_entries.ConfigEntry | None = None

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Extra data appended to the Google OAuth2 authorize URL."""
        return {
            "scope": GOOGLE_HEALTH_WRITE_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle Bluetooth discovery of an AH100 / CH100 scale."""
        mac = discovery_info.address.upper()
        await self.async_set_unique_id(f"{mac}_user_{DEFAULT_USER_ID}")
        self._abort_if_unique_id_configured()

        self._discovered_mac = mac
        self._discovered_name = discovery_info.name or DEFAULT_USER_NAME
        self.context["title_placeholders"] = {
            "name": f"{self._discovered_name} ({mac})"
        }
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual or post-discovery user setup (Google Health OAuth2 is optional)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                mac = _normalize_mac(user_input[CONF_MAC_ADDRESS])
            except ValueError:
                errors[CONF_MAC_ADDRESS] = "invalid_mac"
            else:
                user_id = int(user_input.get(CONF_USER_ID, DEFAULT_USER_ID))
                await self.async_set_unique_id(f"{mac}_user_{user_id}")
                self._abort_if_unique_id_configured()

                data: dict[str, Any] = {
                    CONF_MAC_ADDRESS: mac,
                    CONF_USER_NAME: user_input[CONF_USER_NAME].strip() or DEFAULT_USER_NAME,
                    CONF_HEIGHT_CM: int(user_input[CONF_HEIGHT_CM]),
                    CONF_AGE: int(user_input[CONF_AGE]),
                    CONF_GENDER: user_input[CONF_GENDER],
                    CONF_INITIAL_WEIGHT: float(user_input[CONF_INITIAL_WEIGHT]),
                    CONF_TIMEOUT_SECONDS: int(user_input[CONF_TIMEOUT_SECONDS]),
                    CONF_USER_ID: user_id,
                }

                if user_input.get(CONF_GOOGLE_HEALTH_ENABLED, False):
                    self._pending_scale_data = data
                    return await self.async_step_pick_implementation()

                return self.async_create_entry(
                    title=f"{data[CONF_USER_NAME]} ({mac})",
                    data=data,
                )

        default_mac = self._discovered_mac or ""
        default_name = self._discovered_name or DEFAULT_USER_NAME

        data_schema = vol.Schema(
            {
                vol.Required(CONF_MAC_ADDRESS, default=default_mac): str,
                vol.Required(CONF_USER_NAME, default=default_name): str,
                vol.Required(CONF_HEIGHT_CM, default=DEFAULT_HEIGHT_CM): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=50, max=250, step=1, unit_of_measurement="cm", mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(CONF_AGE, default=DEFAULT_AGE): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=120, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(CONF_GENDER, default=DEFAULT_GENDER): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["male", "female"],
                        translation_key="gender",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_INITIAL_WEIGHT, default=DEFAULT_INITIAL_WEIGHT): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10, max=250, step=0.1, unit_of_measurement="kg", mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(CONF_TIMEOUT_SECONDS, default=DEFAULT_TIMEOUT_SECONDS): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=30, max=180, step=5, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(CONF_USER_ID, default=DEFAULT_USER_ID): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=10, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(CONF_GOOGLE_HEALTH_ENABLED, default=False): bool,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Allow connecting or disconnecting Google Health on an existing scale entry."""
        self._reconfigure_entry = self._get_reconfigure_entry()
        has_google_health = "token" in self._reconfigure_entry.data

        menu_options = ["connect_google_health"]
        if has_google_health:
            menu_options.append("disconnect_google_health")

        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=menu_options,
        )

    async def async_step_connect_google_health(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Start Google OAuth2 linking flow from reconfigure."""
        return await self.async_step_pick_implementation()

    async def async_step_disconnect_google_health(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Disconnect Google Health OAuth2 tokens from the scale entry."""
        entry = self._reconfigure_entry or self._get_reconfigure_entry()
        new_data = {
            k: v
            for k, v in entry.data.items()
            if k not in ("token", "auth_implementation")
        }
        return self.async_update_reload_and_abort(
            entry,
            data=new_data,
            reason="google_health_disconnected",
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Perform reauth when Google Health OAuth2 token is expired or revoked."""
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm Google Health re-authentication."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_pick_implementation()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> FlowResult:
        """Finalize OAuth2 linking for initial setup, reconfigure, or reauth."""
        if self._reauth_entry is not None:
            merged = {**self._reauth_entry.data, **data}
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                data=merged,
            )

        if self._reconfigure_entry is not None:
            merged = {**self._reconfigure_entry.data, **data}
            return self.async_update_reload_and_abort(
                self._reconfigure_entry,
                data=merged,
                reason="reconfigure_successful",
            )

        if self._pending_scale_data is not None:
            merged = {**self._pending_scale_data, **data}
            return self.async_create_entry(
                title=f"{merged[CONF_USER_NAME]} ({merged[CONF_MAC_ADDRESS]})",
                data=merged,
            )

        return self.async_abort(reason="unknown")

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HuaweiAH100OptionsFlow:
        """Return the options flow."""
        return HuaweiAH100OptionsFlow(config_entry)


class HuaweiAH100OptionsFlow(config_entries.OptionsFlow):
    """Allow updating height, age, gender, and measurement timeout from the UI."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_HEIGHT_CM: int(user_input[CONF_HEIGHT_CM]),
                    CONF_AGE: int(user_input[CONF_AGE]),
                    CONF_GENDER: user_input[CONF_GENDER],
                    CONF_TIMEOUT_SECONDS: int(user_input[CONF_TIMEOUT_SECONDS]),
                },
            )

        current_height = self._entry.options.get(
            CONF_HEIGHT_CM, self._entry.data.get(CONF_HEIGHT_CM, DEFAULT_HEIGHT_CM)
        )
        current_age = self._entry.options.get(
            CONF_AGE, self._entry.data.get(CONF_AGE, DEFAULT_AGE)
        )
        current_gender = self._entry.options.get(
            CONF_GENDER, self._entry.data.get(CONF_GENDER, DEFAULT_GENDER)
        )
        current_timeout = self._entry.options.get(
            CONF_TIMEOUT_SECONDS,
            self._entry.data.get(CONF_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS),
        )

        options_schema = vol.Schema(
            {
                vol.Required(CONF_HEIGHT_CM, default=current_height): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=50, max=250, step=1, unit_of_measurement="cm", mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(CONF_AGE, default=current_age): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=120, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(CONF_GENDER, default=current_gender): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["male", "female"],
                        translation_key="gender",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_TIMEOUT_SECONDS, default=current_timeout): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=30, max=180, step=5, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)
