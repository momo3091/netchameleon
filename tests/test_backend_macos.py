"""
Regression test for get_live_mac(): macOS's own Private Wi-Fi Address
feature (on by default per network since Monterey) means the address
actually in use on en0 can differ from the factory address that
`networksetup` reports. This was caught via a real `ifconfig` paste
during manual testing, not written from a hunch -- see the fixture below.
"""
import types

import backend_macos as be

# Real capture (MAC values only, nothing identifying) from a MacBook Pro
# where macOS had already assigned a private/randomized Wi-Fi address.
REAL_EN0_BLOCK = """en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
options=6460<TSO4,TSO6,CHANNEL_IO,PARTIAL_CSUM,ZEROINVERT_CSUM>
ether 02:88:8d:e5:43:dc
inet6 fe80::490:497e:e6e3:da4e%en0 prefixlen 64 secured scopeid 0x6
inet 192.168.10.166 netmask 0xffffff00 broadcast 192.168.10.255
nd6 options=201<PERFORMNUD,DAD>
media: autoselect
status: active
"""

NO_ETHER_BLOCK = """utun0: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1500
inet6 fe80::4d3c:6827:1106:9f9f%utun0 prefixlen 64 scopeid 0xe
nd6 options=201<PERFORMNUD,DAD>
"""


def _fake_run(output: str):
    def run(cmd, capture_output, text, timeout):
        return types.SimpleNamespace(stdout=output, stderr="", returncode=0)
    return run


def test_get_live_mac_parses_real_capture(monkeypatch):
    monkeypatch.setattr(be.subprocess, "run", _fake_run(REAL_EN0_BLOCK))
    assert be.get_live_mac("en0") == "02:88:8D:E5:43:DC"


def test_get_live_mac_is_locally_administered_in_this_capture():
    # The whole point of the bug: this address has the local-admin bit
    # set, proving it's macOS-generated, not the factory address.
    first_byte = int("02:88:8D:E5:43:DC".split(":")[0], 16)
    assert first_byte & 0b10, "expected the locally-administered bit to be set"


def test_get_live_mac_returns_none_without_ether_line(monkeypatch):
    monkeypatch.setattr(be.subprocess, "run", _fake_run(NO_ETHER_BLOCK))
    assert be.get_live_mac("utun0") is None


# --- set_mac_address: the "Wi-Fi left disabled after a failed change" bug ---

def test_set_mac_uses_direct_form_when_it_succeeds(monkeypatch):
    """If the direct ether change works, we must not touch link state at all."""
    calls = []
    monkeypatch.setattr(be, "_run", lambda cmd, use_sudo=False, timeout=20: calls.append(cmd))
    be.set_mac_address("en0", "AA:BB:CC:DD:EE:FF")
    assert calls == [["ifconfig", "en0", "ether", "aa:bb:cc:dd:ee:ff"]]


def test_set_mac_falls_back_to_down_up_bracket(monkeypatch):
    """If the direct form is rejected, fall back to down -> ether -> up, in order."""
    calls = []

    def fake_run(cmd, use_sudo=False, timeout=20):
        calls.append(cmd)
        if cmd == ["ifconfig", "en0", "ether", "aa:bb:cc:dd:ee:ff"] and calls.count(cmd) == 1:
            raise be.AdapterError("simulated: rejected without down first")

    monkeypatch.setattr(be, "_run", fake_run)
    be.set_mac_address("en0", "AA:BB:CC:DD:EE:FF")
    assert calls == [
        ["ifconfig", "en0", "ether", "aa:bb:cc:dd:ee:ff"],  # direct attempt, fails
        ["ifconfig", "en0", "down"],
        ["ifconfig", "en0", "ether", "aa:bb:cc:dd:ee:ff"],  # retry inside the bracket
        ["ifconfig", "en0", "up"],
    ]


def test_wifi_is_never_left_down_when_the_bracketed_change_also_fails(monkeypatch):
    """
    The exact bug from the field report: direct form fails, then the
    ether change inside the down/up bracket ALSO fails (e.g. the real
    'Network is down' ioctl error). The interface must still come back
    up before the error propagates.
    """
    calls = []

    def fake_run(cmd, use_sudo=False, timeout=20):
        calls.append(cmd)
        if cmd[-2:] == ["ether", "aa:bb:cc:dd:ee:ff"]:
            raise be.AdapterError("simulated: ioctl (SIOCAIFADDR): Network is down")

    monkeypatch.setattr(be, "_run", fake_run)
    try:
        be.set_mac_address("en0", "AA:BB:CC:DD:EE:FF")
        assert False, "expected AdapterError to propagate"
    except be.AdapterError:
        pass
    assert ["ifconfig", "en0", "up"] in calls, "interface must be brought back up even on failure"
    assert calls[-1] == ["ifconfig", "en0", "up"], "up must be the last action taken"
