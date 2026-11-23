"""Coordinator for on-demand Huawei AH100 / Honor CH100 scale measurements."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_AGE,
    CONF_GENDER,
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
    STATUS_COMPLETE,
    STATUS_IDLE,
    STATUS_SEARCHING,
    STATUS_TIMEOUT,
)
from .scale import ScaleMeasurement, ScaleUserProfile, read_scale_measurement

_LOGGER = logging.getLogger(__name__)


class HuaweiAH100Coordinator:
    """Manages on-demand BLE measurement sessions and pushes updates to entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self.mac_address: str = entry.data[CONF_MAC_ADDRESS].upper()
        self.user_name: str = entry.data.get(CONF_USER_NAME, DEFAULT_USER_NAME)

        self.status: str = STATUS_IDLE
        self.weight_kg: float | None = None
        self.bmi: float | None = None
        self.body_fat_pct: float | None = None
        self.impedance_ohm: int | None = None

        self._listeners: list[Callable[[], None]] = []
        self._measure_lock = asyncio.Lock()
        self._reset_task: asyncio.Task[Any] | None = None

    @property
    def height_cm(self) -> int:
        return int(self.entry.options.get(CONF_HEIGHT_CM, self.entry.data.get(CONF_HEIGHT_CM, DEFAULT_HEIGHT_CM)))

    @property
    def age(self) -> int:
        return int(self.entry.options.get(CONF_AGE, self.entry.data.get(CONF_AGE, DEFAULT_AGE)))

    @property
    def gender(self) -> str:
        return str(self.entry.options.get(CONF_GENDER, self.entry.data.get(CONF_GENDER, DEFAULT_GENDER)))

    @property
    def timeout_seconds(self) -> int:
        return int(
            self.entry.options.get(
                CONF_TIMEOUT_SECONDS,
                self.entry.data.get(CONF_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS),
            )
        )

    @property
    def user_id(self) -> int:
        return int(self.entry.data.get(CONF_USER_ID, DEFAULT_USER_ID))

    @property
    def reference_weight_kg(self) -> float:
        if self.weight_kg is not None and 10.0 < self.weight_kg < 250.0:
            return self.weight_kg
        return float(self.entry.data.get(CONF_INITIAL_WEIGHT, DEFAULT_INITIAL_WEIGHT))

    @callback
    def async_add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        """Register an entity listener."""
        self._listeners.append(update_callback)

        @callback
        def remove_listener() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return remove_listener

    @callback
    def _async_notify_listeners(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def set_status(self, new_status: str) -> None:
        if self.status != new_status:
            self.status = new_status
            self._async_notify_listeners()

    @callback
    def restore_value(self, key: str, value: float | int) -> None:
        """Restore persisted sensor values on HA startup so USER_INFO has the last weight."""
        if key == "weight_kg" and self.weight_kg is None:
            self.weight_kg = float(value)
        elif key == "bmi" and self.bmi is None:
            self.bmi = float(value)
        elif key == "body_fat_pct" and self.body_fat_pct is None:
            self.body_fat_pct = float(value)
        elif key == "impedance_ohm" and self.impedance_ohm is None:
            self.impedance_ohm = int(value)

    async def async_start_measurement(self, timeout_override: int | None = None) -> ScaleMeasurement | None:
        """Run an on-demand measurement window against the scale."""
        if self._measure_lock.locked():
            _LOGGER.info("Measurement already in progress for %s", self.mac_address)
            return None

        if self._reset_task and not self._reset_task.done():
            self._reset_task.cancel()

        async with self._measure_lock:
            timeout = float(timeout_override or self.timeout_seconds)
            profile = ScaleUserProfile(
                height_cm=self.height_cm,
                age=self.age,
                gender=self.gender,
                reference_weight_kg=self.reference_weight_kg,
                user_id=self.user_id,
            )

            self.set_status(STATUS_SEARCHING)
            _LOGGER.info(
                "Starting Huawei AH100 measurement (%ss) for %s (ref_weight=%.1f kg)",
                timeout,
                self.mac_address,
                profile.reference_weight_kg,
            )

            measurement = await read_scale_measurement(
                self.hass,
                self.mac_address,
                profile,
                timeout_seconds=timeout,
                on_status_change=self.set_status,
            )

            if measurement is not None:
                self.weight_kg = measurement.weight_kg
                self.bmi = measurement.bmi
                if measurement.body_fat_pct is not None:
                    self.body_fat_pct = measurement.body_fat_pct
                if measurement.impedance_ohm is not None:
                    self.impedance_ohm = measurement.impedance_ohm
                self.status = STATUS_COMPLETE
                self._async_notify_listeners()
                _LOGGER.info(
                    "Measurement saved for %s: %.1f kg, BMI %.1f, fat=%s%%, impedance=%s Ω",
                    self.mac_address,
                    self.weight_kg,
                    self.bmi,
                    self.body_fat_pct,
                    self.impedance_ohm,
                )
            else:
                self.set_status(STATUS_TIMEOUT)
                _LOGGER.warning("Measurement timed out for %s", self.mac_address)

            # Reset status back to idle after 15 seconds so automations can trigger cleanly next time
            self._reset_task = self.hass.async_create_task(self._async_reset_status_later())
            return measurement

    async def _async_reset_status_later(self) -> None:
        try:
            await asyncio.sleep(15)
            if not self._measure_lock.locked():
                self.set_status(STATUS_IDLE)
        except asyncio.CancelledError:
            pass
