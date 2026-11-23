"""Switch platform for optional Google Health auto-sync."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import HuaweiAH100Coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Google Health auto-sync switch when Google Health is connected."""
    coordinator: HuaweiAH100Coordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.google_health_connected:
        async_add_entities([HuaweiAH100GoogleHealthSwitch(coordinator, entry)])


class HuaweiAH100GoogleHealthSwitch(SwitchEntity, RestoreEntity):
    """Switch entity controlling automatic push of measurements to Google Health."""

    _attr_has_entity_name = True
    _attr_translation_key = "google_health_auto_sync"
    _attr_icon = "mdi:cloud-upload-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: HuaweiAH100Coordinator,
        entry: ConfigEntry,
    ) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_google_health_auto_sync"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.mac_address}_user_{coordinator.user_id}")},
            connections={(CONNECTION_BLUETOOTH, coordinator.mac_address)},
            name=coordinator.user_name,
            manufacturer="Huawei / Honor",
            model="AH100 / CH100 Smart Scale",
        )

    @property
    def is_on(self) -> bool:
        """Return True if automatic sync to Google Health is enabled."""
        return self._coordinator.google_health_auto_sync

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return sync status attributes."""
        return {
            "last_sync": self._coordinator.last_google_health_sync,
            "last_error": self._coordinator.last_google_health_error,
        }

    async def async_added_to_hass(self) -> None:
        """Restore switch state across HA restarts."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._coordinator.set_google_health_auto_sync(last_state.state != STATE_OFF)

        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable automatic sync to Google Health."""
        self._coordinator.set_google_health_auto_sync(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable automatic sync to Google Health."""
        self._coordinator.set_google_health_auto_sync(False)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
