"""Button platform for starting measurements and pushing to Google Health."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HuaweiAH100Coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Huawei AH100 buttons."""
    coordinator: HuaweiAH100Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = [HuaweiAH100StartButton(coordinator, entry)]
    if coordinator.google_health_connected:
        entities.append(HuaweiAH100PushGoogleHealthButton(coordinator, entry))
    async_add_entities(entities)


class HuaweiAH100StartButton(ButtonEntity):
    """Button entity to start an on-demand weigh-in window."""

    _attr_has_entity_name = True
    _attr_translation_key = "start_measurement"
    _attr_icon = "mdi:scale-bathroom"

    def __init__(
        self,
        coordinator: HuaweiAH100Coordinator,
        entry: ConfigEntry,
    ) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_start_measurement"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.mac_address}_user_{coordinator.user_id}")},
            connections={(CONNECTION_BLUETOOTH, coordinator.mac_address)},
            name=coordinator.user_name,
            manufacturer="Huawei / Honor",
            model="AH100 / CH100 Smart Scale",
        )

    async def async_press(self) -> None:
        """Start the on-demand BLE measurement in the background."""
        self.hass.async_create_task(self._coordinator.async_start_measurement())


class HuaweiAH100PushGoogleHealthButton(ButtonEntity):
    """Button entity to manually push the latest measurement to Google Health."""

    _attr_has_entity_name = True
    _attr_translation_key = "push_to_google_health"
    _attr_icon = "mdi:cloud-sync-outline"

    def __init__(
        self,
        coordinator: HuaweiAH100Coordinator,
        entry: ConfigEntry,
    ) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_push_to_google_health"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.mac_address}_user_{coordinator.user_id}")},
            connections={(CONNECTION_BLUETOOTH, coordinator.mac_address)},
            name=coordinator.user_name,
            manufacturer="Huawei / Honor",
            model="AH100 / CH100 Smart Scale",
        )

    async def async_press(self) -> None:
        """Push the latest measurement to Google Health."""
        await self._coordinator.async_push_to_google_health()
