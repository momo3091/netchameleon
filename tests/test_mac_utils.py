"""Pure-logic tests -- no display, no OS calls, run anywhere including CI."""
import pytest

import mac_utils as mu
import oui_database as ouidb


def test_locally_administered_mac_is_valid_and_flagged():
    for _ in range(500):
        mac = mu.generate_locally_administered_mac()
        assert mu.is_valid_mac(mac)
        first_byte = int(mac.split(":")[0], 16)
        assert first_byte & 0b10, f"local-admin bit not set: {mac}"
        assert not first_byte & 0b01, f"multicast bit set, expected unicast: {mac}"


@pytest.mark.parametrize("vendor", ouidb.all_vendor_names())
def test_vendor_style_mac_uses_real_oui(vendor):
    for _ in range(50):
        oui = ouidb.random_oui_for_vendor(vendor)
        mac = mu.generate_vendor_style_mac(oui)
        assert mu.is_valid_mac(mac)
        assert mac.startswith(oui.upper())


@pytest.mark.parametrize("mac,expected", [
    ("AC:DE:48:12:34:56", True),
    ("ac:de:48:12:34:56", True),
    ("AC-DE-48-12-34-56", False),
    ("AC:DE:48:12:34", False),
    ("not a mac", False),
    ("", False),
])
def test_is_valid_mac(mac, expected):
    assert mu.is_valid_mac(mac) is expected


def test_mac_vendor_prefix():
    assert mu.mac_vendor_prefix("14:B3:1F:AA:BB:CC") == "14:B3:1F"


def test_oui_to_bytes_rejects_malformed_input():
    with pytest.raises(ValueError):
        mu.oui_to_bytes("bad")


@pytest.mark.parametrize("vendor", ouidb.all_vendor_names())
def test_vendor_database_entries_are_well_formed(vendor):
    info = ouidb.VENDOR_OUIS[vendor]
    assert info["ouis"], f"{vendor} has no OUIs"
    for oui in info["ouis"]:
        parts = oui.split(":")
        assert len(parts) == 3
        for p in parts:
            assert len(p) == 2 and all(c in "0123456789ABCDEF" for c in p.upper())
