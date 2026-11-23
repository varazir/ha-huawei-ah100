"""Sensor platform for Huawei AH100 / Honor CH100 Scale."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfMass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, STATUS_OPTIONS
from .coordinator import HuaweiAH100Coordinator


@dataclass(frozen=True, kw_only=True)
class HuaweiScaleSensorDescription(SensorEntityDescription):
    """Describes a Huawei AH100 sensor entity."""

    value_fn: Callable[[HuaweiAH100Coordinator], Any]
    restore_key: str | None = None


SENSORS: tuple[HuaweiScaleSensorDescription, ...] = (
    HuaweiScaleSensorDescription(
        key="weight",
        translation_key="weight",
        icon="mdi:scale-bathroom",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: c.weight_kg,
        restore_key="weight_kg",
    ),
    HuaweiScaleSensorDescription(
        key="bmi",
        translation_key="bmi",
        icon="mdi:human",
        native_unit_of_measurement="BMI",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: c.bmi,
        restore_key="bmi",
    ),
    HuaweiScaleSensorDescription(
        key="body_fat",
        translation_key="body_fat",
        icon="mdi:percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: c.body_fat_pct,
        restore_key="body_fat_pct",
    ),
    HuaweiScaleSensorDescription(
        key="impedance",
        translation_key="impedance",
        icon="mdi:omega",
        native_unit_of_measurement="Ω",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda c: c.impedance_ohm,
        restore_key="impedance_ohm",
    ),
    HuaweiScaleSensorDescription(
        key="status",
        translation_key="status",
        icon="mdi:bluetooth-connect",
        device_class=SensorDeviceClass.ENUM,
        options=STATUS_OPTIONS,
        value_fn=lambda c: c.status,
        restore_key=None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Huawei AH100 sensors from a config entry."""
    coordinator: HuaweiAH100Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        HuaweiAH100Sensor(coordinator, entry, description)
        for description in SENSORS
    )


class HuaweiAH100Sensor(RestoreSensor, SensorEntity):
    """Representation of a Huawei AH100 / Honor CH100 sensor."""

    entity_description: HuaweiScaleSensorDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: HuaweiAH100Coordinator,
        entry: ConfigEntry,
        description: HuaweiScaleSensorDescription,
    ) -> None:
        self._coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.mac_address}_user_{coordinator.user_id}")},
            connections={(CONNECTION_BLUETOOTH, coordinator.mac_address)},
            name=coordinator.user_name,
            manufacturer="Huawei / Honor",
            model="AH100 / CH100 Smart Scale",
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._coordinator)

    async def async_added_to_hass(self) -> None:
        """Restore persisted measurement values across HA restarts."""
        await super().async_added_to_hass()
        if self.entity_description.restore_key is not None:
            last_data = await self.async_get_last_sensor_data()
            if last_data is not None and last_data.native_value is not None:
                try:
                    self._coordinator.restore_value(
                        self.entity_description.restore_key,
                        float(last_data.native_value),
                    )
                except (TypeError, ValueError):
                    pass

        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
