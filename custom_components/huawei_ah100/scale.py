"""BLE protocol implementation for Huawei AH100 / Honor CH100 smart scales.

SPDX-License-Identifier: GPL-3.0-or-later

Portions of the BLE wire protocol (XOR obfuscation, AES-128-CTR session key
derivation, frame encoding/decoding, CMD_USER_INFO length quirk from issue #1449,
and 2-second heartbeat keep-alive) are derived from openScale:
  - https://github.com/oliexdev/openScale
  - BluetoothHuaweiAH100.java (v2.5.4), Copyright (C) 2014 olie.xdev
  - HuaweiAhCh100Handler.kt, Copyright (C) 2026 openScale contributors
Licensed under the GNU General Public License v3.0 or later.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import datetime
import logging
import struct
import time
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak_retry_connector import establish_connection
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import (
    CMD_AUTH,
    CMD_BIND_USER,
    CMD_FAT_RESULT_ACK,
    CMD_GET_VERSION,
    CMD_HEART_BEAT,
    CMD_SET_SCALE_CLOCK,
    CMD_SET_UNIT,
    CMD_USER_INFO,
    INITIAL_IV,
    INITIAL_KEY,
    NTFY_AUTH_RESULT,
    NTFY_BIND_OK,
    NTFY_GO_SLEEP,
    NTFY_HISTORY_RECORD,
    NTFY_HISTORY_RECORD2,
    NTFY_MEASUREMENT,
    NTFY_MEASUREMENT2,
    NTFY_MEASUREMENT_WEIGHT,
    NTFY_USER_CHANGED,
    STATUS_CONNECTED,
    STATUS_MEASURING,
    UUID_CHAR_RX,
    UUID_CHAR_TX,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScaleMeasurement:
    """Decoded measurement from a Huawei AH100 / Honor CH100 scale."""

    user_id: int
    weight_kg: float
    bmi: float
    body_fat_pct: float | None
    impedance_ohm: int | None
    timestamp: datetime.datetime | None = None


@dataclass(frozen=True)
class ScaleUserProfile:
    """User profile pushed to the scale via CMD_USER_INFO."""

    height_cm: int
    age: int
    gender: str  # "male" or "female"
    reference_weight_kg: float
    user_id: int = 1


def mac_to_bytes(mac_address: str) -> bytes:
    """Convert 'AA:BB:CC:DD:EE:FF' to 6 bytes."""
    clean = mac_address.replace(":", "").replace("-", "").strip()
    if len(clean) != 12:
        raise ValueError(f"Invalid MAC address: {mac_address}")
    return bytes.fromhex(clean)


def xor_with_mac(data: bytes, mac_bytes: bytes) -> bytes:
    """Self-inverse XOR obfuscation with the 6-byte scale MAC."""
    if not mac_bytes:
        return data
    return bytes(data[i] ^ mac_bytes[i % len(mac_bytes)] for i in range(len(data)))


def aes_ctr(data: bytes, key: bytes, iv: bytes = INITIAL_IV) -> bytes:
    """Symmetric AES-128-CTR encryption/decryption."""
    cipher = Cipher(algorithms.AES(key), modes.CTR(iv))
    ctx = cipher.encryptor()
    return ctx.update(data) + ctx.finalize()


def build_auth_token(user_id: int = 1) -> bytes:
    """Build the 7-byte AUTH token whose XOR checksum equals 0."""
    token = bytearray([0x11, 0x22, 0x33, 0x44, 0x55, 0x00, user_id & 0xFF])
    checksum = 0
    for b in token:
        checksum ^= b
    token[5] = checksum
    return bytes(token)


def derive_magic_key(auth_token: bytes, mac_bytes: bytes) -> bytes:
    """Derive the 16-byte session AES-128 key."""
    if len(auth_token) != 7:
        raise ValueError(f"auth_token must be 7 bytes, got {len(auth_token)}")
    return xor_with_mac(auth_token, mac_bytes) + INITIAL_KEY[7:]


def build_plain_frame(
    cmd_byte: int,
    payload: bytes,
    mac_bytes: bytes,
    explicit_len: int | None = None,
) -> bytes:
    """Build a host->scale plain command frame (0xDB, len+1, cmd, xor(payload))."""
    wire_len = explicit_len if explicit_len is not None else (len(payload) + 1)
    header = struct.pack("BBB", 0xDB, wire_len & 0xFF, cmd_byte & 0xFF)
    return header + xor_with_mac(payload, mac_bytes)


def build_clock_payload(now: datetime.datetime | None = None) -> bytes:
    """Build the 8-byte CMD_SET_SCALE_CLOCK payload."""
    dt = now or datetime.datetime.now()
    return struct.pack(
        "<HBBBBBB",
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.isoweekday(),  # Monday=1 .. Sunday=7
    )


def build_user_info_payload(auth_token: bytes, profile: ScaleUserProfile) -> bytes:
    """Build the 16-byte plaintext CMD_USER_INFO payload (v2.5.4 / issue #1449)."""
    sex_bit = 0x00 if profile.gender.lower() == "male" else 0x80
    age_byte = (profile.age & 0x7F) | sex_bit
    height_byte = profile.height_cm & 0xFF
    # Weight must never be 0; scale uses it to match the user profile.
    weight_tenth = max(100, min(2500, int(round(profile.reference_weight_kg * 10))))
    tail = struct.pack(
        "<BBBHHBB",
        age_byte,
        height_byte,
        0x00,
        weight_tenth,
        0xFFFF,  # Unknown resistance sentinel
        0x1C,    # Constant trailer (uncounted in declared length)
        0xE2,
    )
    return auth_token + tail


def build_user_info_frame(
    auth_token: bytes,
    magic_key: bytes,
    mac_bytes: bytes,
    profile: ScaleUserProfile,
) -> bytes:
    """Build the encrypted 0xDC CMD_USER_INFO frame (declaredLen=14, 16 bytes sent)."""
    plaintext = build_user_info_payload(auth_token, profile)
    encrypted = aes_ctr(plaintext, magic_key, INITIAL_IV)
    # Vendor app & v2.5.4 declare 14 (0x0E) while transmitting 16 bytes.
    header = struct.pack("BBB", 0xDC, 14, CMD_USER_INFO)
    return header + xor_with_mac(encrypted, mac_bytes)


def decode_measurement_frame(
    frame: bytes,
    magic_key: bytes,
    mac_bytes: bytes,
    height_cm: int,
) -> ScaleMeasurement | None:
    """Decode the first half of an encrypted 0x0E/0x10 measurement notification."""
    if len(frame) < 8:
        return None
    deobfuscated = xor_with_mac(frame[3:], mac_bytes)
    plaintext = aes_ctr(deobfuscated, magic_key, INITIAL_IV)
    if len(plaintext) < 5:
        return None

    user_id = plaintext[0]
    weight_raw = (plaintext[2] << 8) | plaintext[1]
    fat_raw = (plaintext[4] << 8) | plaintext[3]
    weight_kg = round(weight_raw / 10.0, 1)

    if not (10.0 < weight_kg < 250.0):
        return None

    fat_val = round(fat_raw / 10.0, 1)
    body_fat_pct = fat_val if (3.0 < fat_val < 75.0) else None

    impedance_ohm: int | None = None
    if len(plaintext) >= 15:
        imp = (plaintext[14] << 8) | plaintext[13]
        if 1 <= imp <= 3999:
            impedance_ohm = imp

    ts: datetime.datetime | None = None
    if len(plaintext) >= 12:
        try:
            year = (plaintext[6] << 8) | plaintext[5]
            month = plaintext[7]
            day = plaintext[8]
            hour = plaintext[9]
            minute = plaintext[10]
            second = plaintext[11]
            if 2000 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                ts = datetime.datetime(year, month, day, hour, minute, second)
        except ValueError:
            ts = None

    height_m = height_cm / 100.0
    bmi = round(weight_kg / (height_m * height_m), 1) if height_m > 0.5 else 0.0

    return ScaleMeasurement(
        user_id=user_id,
        weight_kg=weight_kg,
        bmi=bmi,
        body_fat_pct=body_fat_pct,
        impedance_ohm=impedance_ohm,
        timestamp=ts,
    )


async def read_scale_measurement(
    hass: Any,
    mac_address: str,
    profile: ScaleUserProfile,
    timeout_seconds: float = 90.0,
    on_status_change: Callable[[str], None] | None = None,
) -> ScaleMeasurement | None:
    """Connect to the Huawei AH100/CH100 scale on demand and return a measurement."""
    from homeassistant.components import bluetooth as ha_bluetooth

    mac_upper = mac_address.upper()
    mac_bytes = mac_to_bytes(mac_upper)
    deadline = time.monotonic() + timeout_seconds
    announced_connected = False

    def set_status(status: str) -> None:
        if on_status_change is not None:
            on_status_change(status)

    while time.monotonic() < deadline:
        device = ha_bluetooth.async_ble_device_from_address(
            hass, mac_upper, connectable=True
        )
        if device is None:
            try:
                device = await BleakScanner.find_device_by_address(
                    mac_upper, timeout=3.0
                )
            except Exception:  # noqa: BLE001
                device = None

        if device is None:
            await asyncio.sleep(0.5)
            continue

        state: dict[str, Any] = {
            "client": None,
            "auth_token": build_auth_token(profile.user_id),
            "magic_key": None,
            "authorised": False,
            "result": None,
            "disconnected": False,
            "last_cmd_time": time.monotonic(),
            "last_user_info_time": 0.0,
        }

        async def send_plain(cmd_byte: int, payload: bytes) -> None:
            client = state["client"]
            if not client or state["disconnected"]:
                return
            packet = build_plain_frame(cmd_byte, payload, mac_bytes)
            state["last_cmd_time"] = time.monotonic()
            try:
                await client.write_gatt_char(UUID_CHAR_TX, packet, response=True)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("write_gatt_char (cmd %s) failed: %s", cmd_byte, err)

        async def send_user_info() -> None:
            client = state["client"]
            mk = state["magic_key"]
            if not client or state["disconnected"] or not mk:
                return
            packet = build_user_info_frame(state["auth_token"], mk, mac_bytes, profile)
            state["last_cmd_time"] = time.monotonic()
            state["last_user_info_time"] = time.monotonic()
            try:
                await client.write_gatt_char(UUID_CHAR_TX, packet, response=True)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("write_gatt_char (USER_INFO) failed: %s", err)

        async def run_post_auth_init() -> None:
            try:
                await send_plain(CMD_SET_UNIT, bytes([0x01]))
                await asyncio.sleep(0.08)
                await send_plain(CMD_SET_SCALE_CLOCK, build_clock_payload())
                await asyncio.sleep(0.08)
                await send_user_info()
                await asyncio.sleep(0.08)
                await send_plain(CMD_GET_VERSION, b"")
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("post-auth init error: %s", err)

        async def notification_handler(_sender: Any, data: bytearray) -> None:
            nonlocal announced_connected
            if state["disconnected"] or len(data) < 3:
                return
            op_code = data[2]
            _LOGGER.debug("Scale notify: op=0x%02X len=%d", op_code, len(data))

            if op_code == NTFY_AUTH_RESULT:
                payload = xor_with_mac(bytes(data[3:]), mac_bytes)
                if payload and payload[0] == 1:
                    state["magic_key"] = derive_magic_key(state["auth_token"], mac_bytes)
                    state["authorised"] = True
                    asyncio.create_task(run_post_auth_init())
                    if not announced_connected:
                        announced_connected = True
                        set_status(STATUS_CONNECTED)
                else:
                    await send_plain(CMD_BIND_USER, state["auth_token"])

            elif op_code == NTFY_BIND_OK:
                await send_plain(CMD_AUTH, state["auth_token"])

            elif op_code == NTFY_USER_CHANGED:
                now = time.monotonic()
                if state["authorised"] and (now - state["last_user_info_time"]) > 1.0:
                    asyncio.create_task(send_user_info())

            elif op_code == NTFY_MEASUREMENT_WEIGHT:
                set_status(STATUS_MEASURING)

            elif op_code == NTFY_GO_SLEEP:
                state["disconnected"] = True

            elif op_code in (NTFY_MEASUREMENT, NTFY_HISTORY_RECORD):
                mk = state["magic_key"]
                if not mk:
                    return
                measurement = decode_measurement_frame(
                    bytes(data), mk, mac_bytes, profile.height_cm
                )
                if measurement is not None:
                    state["result"] = measurement
                    await send_plain(CMD_FAT_RESULT_ACK, bytes([0x00]))

            elif op_code in (NTFY_MEASUREMENT2, NTFY_HISTORY_RECORD2):
                if state["result"] is not None:
                    await send_plain(CMD_FAT_RESULT_ACK, bytes([0x00]))

        def handle_disconnect(_client: BleakClient) -> None:
            state["disconnected"] = True

        client: BleakClient | None = None
        notify_started = False
        try:
            client = await establish_connection(
                BleakClient,
                device,
                f"Huawei AH100 ({mac_upper})",
                disconnected_callback=handle_disconnect,
                max_attempts=1,
                timeout=5.0,
            )
            state["client"] = client
            await client.start_notify(UUID_CHAR_RX, notification_handler)
            notify_started = True
            await send_plain(CMD_AUTH, state["auth_token"])

            while (
                not state["disconnected"]
                and client.is_connected
                and time.monotonic() < deadline
            ):
                if state["result"] is not None:
                    await asyncio.sleep(0.4)
                    return state["result"]

                if (
                    state["authorised"]
                    and (time.monotonic() - state["last_cmd_time"]) >= 2.0
                ):
                    await send_plain(CMD_HEART_BEAT, b"")

                await asyncio.sleep(0.25)

        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Connection cycle ended: %s", err)
            await asyncio.sleep(0.5)
        finally:
            state["disconnected"] = True
            if client is not None:
                if notify_started:
                    try:
                        await client.stop_notify(UUID_CHAR_RX)
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001
                    pass

        if state["result"] is not None:
            return state["result"]

        await asyncio.sleep(0.4)

    return None
