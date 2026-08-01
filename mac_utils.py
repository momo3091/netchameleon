"""
mac_utils.py
Pure-logic helpers for generating and validating MAC addresses.
No OS calls here on purpose -- this module is 100% unit-testable
on any platform, independent of backend_windows.py / backend_macos.py.
"""

import random
import re

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def is_valid_mac(mac: str) -> bool:
    """True if `mac` is a well-formed AA:BB:CC:DD:EE:FF address."""
    return bool(MAC_RE.match(mac))


def format_mac(byte_list) -> str:
    """[0xAC, 0xDE, 0x48, 0x12, 0x34, 0x56] -> 'AC:DE:48:12:34:56'"""
    return ":".join(f"{b:02X}" for b in byte_list)


def oui_to_bytes(oui: str):
    """'AC:DE:48' -> [0xAC, 0xDE, 0x48]"""
    parts = oui.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"'{oui}' is not a 3-byte OUI like 'AC:DE:48'")
    return [int(p, 16) for p in parts]


def generate_locally_administered_mac() -> str:
    """
    Fully random MAC with the 'locally administered' + 'unicast' bits set.

    This is the mode we recommend by default. It can never collide with a
    real manufacturer block, which is exactly how iOS / Android / Windows
    generate their own private Wi-Fi MAC addresses -- it's honest about
    being a randomized address rather than pretending to be a specific
    factory-issued one.
    """
    first_byte = random.randint(0x00, 0xFF)
    first_byte = (first_byte & 0b11111100) | 0b00000010  # bit1=1 (local), bit0=0 (unicast)
    rest = [random.randint(0x00, 0xFF) for _ in range(5)]
    return format_mac([first_byte] + rest)


def generate_vendor_style_mac(oui: str) -> str:
    """
    Real vendor OUI (first 3 bytes) + a random device-specific suffix
    (last 3 bytes). Looks like a genuine factory address for that vendor.

    Use this mode deliberately -- see the README for why it exists and
    where it's appropriate.
    """
    oui_bytes = oui_to_bytes(oui)
    suffix = [random.randint(0x00, 0xFF) for _ in range(3)]
    return format_mac(oui_bytes + suffix)


def mac_vendor_prefix(mac: str) -> str:
    """'AC:DE:48:12:34:56' -> 'AC:DE:48'"""
    return ":".join(mac.split(":")[:3]).upper()
