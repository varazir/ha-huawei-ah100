"""Google Health API v4 client for pushing weight and body fat measurements."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import TYPE_CHECKING, Any

from .const import GOOGLE_HEALTH_API_BASE

if TYPE_CHECKING:
    from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session

_LOGGER = logging.getLogger(__name__)


class GoogleHealthError(Exception):
    """Base exception for Google Health API errors."""


class GoogleHealthAuthError(GoogleHealthError):
    """Raised when Google Health OAuth2 authentication fails or is revoked."""


def _build_sample_time(measured_at: datetime) -> dict[str, str]:
    """Build a Google Health API v4 sampleTime object with physicalTime and utcOffset."""
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=timezone.utc)

    utc_dt = measured_at.astimezone(timezone.utc)
    physical_time = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    offset = measured_at.utcoffset()
    offset_seconds = int(offset.total_seconds()) if offset is not None else 0

    return {
        "physicalTime": physical_time,
        "utcOffset": f"{offset_seconds}s",
    }


def build_weight_payload(weight_kg: float, measured_at: datetime) -> dict[str, Any]:
    """Build the JSON payload for POST /v4/users/me/dataTypes/weight/dataPoints."""
    return {
        "weight": {
            "sampleTime": _build_sample_time(measured_at),
            "weightGrams": round(float(weight_kg) * 1000),
        }
    }


def build_body_fat_payload(body_fat_pct: float, measured_at: datetime) -> dict[str, Any]:
    """Build the JSON payload for POST /v4/users/me/dataTypes/body-fat/dataPoints."""
    return {
        "bodyFat": {
            "sampleTime": _build_sample_time(measured_at),
            "percentage": round(float(body_fat_pct), 1),
        }
    }


class GoogleHealthClient:
    """Async client that pushes scale measurements to Google Health API v4."""

    def __init__(self, oauth_session: OAuth2Session) -> None:
        """Initialize with a Home Assistant OAuth2Session."""
        self._oauth_session = oauth_session

    async def _async_post_data_point(
        self, data_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """POST a single dataPoint to Google Health API v4."""
        url = f"{GOOGLE_HEALTH_API_BASE}/{data_type}/dataPoints"
        try:
            resp = await self._oauth_session.async_request("post", url, json=payload)
        except Exception as err:
            raise GoogleHealthError(
                f"Failed to send {data_type} to Google Health: {err}"
            ) from err

        if resp.status in (401, 403):
            body = await resp.text()
            raise GoogleHealthAuthError(
                f"Google Health authorization error ({resp.status}): {body[:300]}"
            )

        if resp.status >= 400:
            body = await resp.text()
            raise GoogleHealthError(
                f"Google Health API error ({resp.status}) for {data_type}: {body[:300]}"
            )

        try:
            return await resp.json()
        except Exception:
            return {}

    async def async_push_measurement(
        self,
        weight_kg: float | None,
        body_fat_pct: float | None = None,
        measured_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Push weight (and optionally body fat %) to Google Health API v4."""
        ts = measured_at or datetime.now().astimezone()
        result: dict[str, Any] = {
            "weight_pushed": False,
            "body_fat_pushed": False,
            "timestamp": ts.isoformat(),
        }

        if weight_kg is not None and weight_kg > 0:
            payload = build_weight_payload(weight_kg, ts)
            await self._async_post_data_point("weight", payload)
            result["weight_pushed"] = True
            _LOGGER.info(
                "Pushed weight (%.1f kg / %d g) to Google Health",
                weight_kg,
                payload["weight"]["weightGrams"],
            )

        if body_fat_pct is not None and body_fat_pct > 0:
            payload = build_body_fat_payload(body_fat_pct, ts)
            await self._async_post_data_point("body-fat", payload)
            result["body_fat_pushed"] = True
            _LOGGER.info(
                "Pushed body fat (%.1f%%) to Google Health",
                body_fat_pct,
            )

        return result
