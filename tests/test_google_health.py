"""Unit tests for Google Health API v4 payload formatting and client push logic."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import types

# Load const.py and google_health.py directly without requiring homeassistant installed locally
ROOT = Path(__file__).resolve().parent.parent
PKG_DIR = ROOT / "custom_components" / "huawei_ah100"

pkg = types.ModuleType("custom_components.huawei_ah100")
pkg.__path__ = [str(PKG_DIR)]
sys.modules["custom_components"] = types.ModuleType("custom_components")
sys.modules["custom_components.huawei_ah100"] = pkg


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"custom_components.huawei_ah100.{name}", PKG_DIR / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"custom_components.huawei_ah100.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


_load("const")
gh = _load("google_health")


class _FakeResponse:
    def __init__(self, status: int, body: str = "{}") -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def json(self) -> dict:
        return {}


class _FakeOAuthSession:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.calls: list[tuple[str, str, dict]] = []

    async def async_request(self, method: str, url: str, json: dict | None = None):
        self.calls.append((method, url, json or {}))
        return _FakeResponse(self.status, "error body" if self.status >= 400 else "{}")


def test_payload_formatting() -> None:
    tz_stockholm = timezone(timedelta(hours=1))
    dt = datetime(2026, 11, 23, 14, 30, 0, tzinfo=tz_stockholm)

    w = gh.build_weight_payload(99.7, dt)
    assert w == {
        "weight": {
            "sampleTime": {
                "physicalTime": "2026-11-23T13:30:00Z",
                "utcOffset": "3600s",
            },
            "weightGrams": 99700,
        }
    }, f"Unexpected weight payload: {w}"

    bf = gh.build_body_fat_payload(31.64, dt)
    assert bf == {
        "bodyFat": {
            "sampleTime": {
                "physicalTime": "2026-11-23T13:30:00Z",
                "utcOffset": "3600s",
            },
            "percentage": 31.6,
        }
    }, f"Unexpected bodyFat payload: {bf}"


async def _test_client_async() -> None:
    tz_utc = timezone.utc
    dt = datetime(2026, 11, 23, 13, 30, 0, tzinfo=tz_utc)

    # 1. Both weight and body fat
    session = _FakeOAuthSession(status=200)
    client = gh.GoogleHealthClient(session)
    res = await client.async_push_measurement(99.7, 31.6, measured_at=dt)
    assert res["weight_pushed"] is True
    assert res["body_fat_pushed"] is True
    assert len(session.calls) == 2
    assert session.calls[0][1].endswith("/weight/dataPoints")
    assert session.calls[1][1].endswith("/body-fat/dataPoints")

    # 2. Weight only
    session2 = _FakeOAuthSession(status=200)
    client2 = gh.GoogleHealthClient(session2)
    res2 = await client2.async_push_measurement(99.7, None, measured_at=dt)
    assert res2["weight_pushed"] is True
    assert res2["body_fat_pushed"] is False
    assert len(session2.calls) == 1

    # 3. 401 raises GoogleHealthAuthError
    session3 = _FakeOAuthSession(status=401)
    client3 = gh.GoogleHealthClient(session3)
    try:
        await client3.async_push_measurement(99.7, 31.6, measured_at=dt)
        raise AssertionError("Expected GoogleHealthAuthError")
    except gh.GoogleHealthAuthError:
        pass

    # 4. 500 raises GoogleHealthError
    session4 = _FakeOAuthSession(status=500)
    client4 = gh.GoogleHealthClient(session4)
    try:
        await client4.async_push_measurement(99.7, 31.6, measured_at=dt)
        raise AssertionError("Expected GoogleHealthError")
    except gh.GoogleHealthError:
        pass


if __name__ == "__main__":
    test_payload_formatting()
    asyncio.run(_test_client_async())
    print("ALL GOOGLE HEALTH TESTS PASSED!")
