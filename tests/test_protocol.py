"""Unit tests for Huawei AH100 / Honor CH100 wire protocol primitives.

Uses the verified fixtures and real hardware captures from openScale's
HuaweiAhCh100HandlerTest and HuaweiUserRecordWireTest.
"""

import importlib.util
import sys
import types
from pathlib import Path

# Load scale.py directly without requiring homeassistant/bleak to be installed locally
REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = REPO_ROOT / "custom_components" / "huawei_ah100"

# Stub bleak & bleak_retry_connector for pure-protocol unit tests
for mod_name in ("bleak", "bleak_retry_connector"):
    if mod_name not in sys.modules:
        stub = types.ModuleType(mod_name)
        stub.BleakClient = object
        stub.BleakScanner = object
        stub.establish_connection = None
        sys.modules[mod_name] = stub

pkg_stub = types.ModuleType("huawei_ah100")
pkg_stub.__path__ = [str(PKG_DIR)]
sys.modules["huawei_ah100"] = pkg_stub

const_spec = importlib.util.spec_from_file_location("huawei_ah100.const", PKG_DIR / "const.py")
const_mod = importlib.util.module_from_spec(const_spec)
sys.modules["huawei_ah100.const"] = const_mod
const_spec.loader.exec_module(const_mod)

scale_spec = importlib.util.spec_from_file_location("huawei_ah100.scale", PKG_DIR / "scale.py")
scale = importlib.util.module_from_spec(scale_spec)
sys.modules["huawei_ah100.scale"] = scale
scale_spec.loader.exec_module(scale)


def test_auth_token_and_magic_key():
    mac = scale.mac_to_bytes("5C:CA:D3:08:7B:4F")
    token = scale.build_auth_token(1)
    assert token.hex() == "11223344551001"
    mk = scale.derive_magic_key(token, mac)
    assert mk.hex() == "4de8e04c2e5f5d2a980fde3456732156"


def test_plain_frame_uses_len_plus_1():
    mac = scale.mac_to_bytes("5C:CA:D3:08:7B:4F")
    frame = scale.build_plain_frame(const_mod.CMD_AUTH, bytes.fromhex("11223344"), mac)
    assert frame[0] == 0xDB
    assert frame[1] == 5  # len(payload) + 1
    assert frame[2] == const_mod.CMD_AUTH


def test_user_info_frame_declares_14_and_sends_16():
    mac = scale.mac_to_bytes("00:11:22:33:44:55")
    token = scale.build_auth_token(1)
    mk = scale.derive_magic_key(token, mac)
    profile = scale.ScaleUserProfile(
        height_cm=176, age=46, gender="male", reference_weight_kg=99.1, user_id=1
    )
    frame = scale.build_user_info_frame(token, mk, mac, profile)
    assert frame[0] == 0xDC
    assert frame[1] == 0x0E  # 14 declared
    assert frame[2] == const_mod.CMD_USER_INFO
    assert len(frame) == 3 + 16  # 16 bytes transmitted

    # Round-trip decrypt and verify fields
    plain = scale.aes_ctr(scale.xor_with_mac(frame[3:], mac), mk)
    assert len(plain) == 16
    assert plain[7] == 46       # age | male(0x00)
    assert plain[8] == 176      # height_cm
    assert (plain[10] | (plain[11] << 8)) == 991  # 99.1 kg in tenth-kg
    assert plain[14] == 0x1C
    assert plain[15] == 0xE2


def test_real_hardware_capture_decoding():
    mac = scale.mac_to_bytes("5C:CA:D3:14:2B:B3")
    mk = scale.derive_magic_key(scale.build_auth_token(1), mac)
    frame = bytes.fromhex("bc110eabf78678303ba462fc93d1db4b348861")
    m = scale.decode_measurement_frame(frame, mk, mac, height_cm=180)
    assert m is not None
    assert m.user_id == 1
    assert m.weight_kg == 126.6
    assert m.body_fat_pct == 33.8
    assert m.impedance_ohm == 306
    assert m.timestamp.year == 2026
    assert m.timestamp.month == 8
    assert m.timestamp.day == 10


if __name__ == "__main__":
    test_auth_token_and_magic_key()
    test_plain_frame_uses_len_plus_1()
    test_user_info_frame_declares_14_and_sends_16()
    test_real_hardware_capture_decoding()
    print("ALL PROTOCOL TESTS PASSED!")
