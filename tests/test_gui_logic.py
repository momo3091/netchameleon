"""
Exercises OSPanel's actual click-path (select adapter -> generate ->
apply -> restore) with the OS backend mocked out, so CI can verify the
wiring without a real adapter or a real Windows/macOS host.

Needs a display. Locally that's whatever DISPLAY you already have; in CI
the workflow runs this under xvfb-run (see .github/workflows/tests.yml).
"""
import sys
import types

import pytest
import customtkinter as ctk

import main as app_module


@pytest.fixture
def fake_backend(monkeypatch):
    """A fake backend_windows module with an in-memory fake adapter."""
    fake = types.ModuleType("backend_windows")
    fake.list_adapters = lambda: [
        {"Name": "Ethernet0", "InterfaceDescription": "Fake NIC",
         "MacAddress": "00-11-22-33-44-55", "Status": "Up"}
    ]
    fake.get_current_ip = lambda name: "192.168.1.42"
    calls = {"applied_mac": None, "restored": False}
    fake.set_mac_address = lambda name, mac: calls.__setitem__("applied_mac", mac)
    fake.restore_original_mac = lambda name: calls.__setitem__("restored", True)
    fake.renew_ip = lambda name: None
    monkeypatch.setitem(sys.modules, "backend_windows", fake)
    return calls


@pytest.fixture
def root():
    r = ctk.CTk()
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def panel(root, fake_backend):
    messages = []
    p = app_module.OSPanel(root, "Windows", lambda msg, error=False: messages.append((msg, error)))
    p.messages = messages
    root.update()
    return p


def test_adapter_auto_selected_and_mac_normalized(panel):
    assert panel.current_adapter is not None
    assert panel.current_adapter["mac"] == "00:11:22:33:44:55"


def test_random_mode_generate_enables_apply(panel):
    panel.generate_preview()
    panel.master.update()
    assert panel.pending_mac is not None
    assert panel.apply_btn.cget("state") == "normal"


def test_vendor_mode_generate_uses_real_oui(panel):
    panel.mode_var.set("vendor")
    panel._on_mode_change()
    assert panel.vendor_menu.cget("state") == "normal"
    panel.vendor_menu.set("Dell")
    panel.generate_preview()
    dell_ouis = tuple(o.upper() for o in __import__("oui_database").VENDOR_OUIS["Dell"]["ouis"])
    assert panel.pending_mac.startswith(dell_ouis)


def test_apply_calls_backend(panel, fake_backend):
    panel.generate_preview()
    pending = panel.pending_mac
    panel.apply_mac()
    assert fake_backend["applied_mac"] == pending


def test_apply_on_macos_triggers_followup_dhcp_renew(root, monkeypatch):
    """After a successful MAC change on macOS, a DHCP renew should fire
    automatically (helps macOS re-validate connectivity faster)."""
    monkeypatch.setattr(app_module.time, "sleep", lambda s: None)
    fake = types.ModuleType("backend_macos")
    fake.list_adapters = lambda: [{"port": "Wi-Fi", "device": "en0", "mac": "F0:18:98:1B:D7:93"}]
    fake.get_current_ip = lambda device: "192.168.1.50"
    fake.get_live_mac = lambda device: None
    fake.set_mac_address = lambda device, mac, is_wifi=False: None
    renew_calls = []
    fake.renew_ip = lambda device: renew_calls.append(device)
    monkeypatch.setitem(sys.modules, "backend_macos", fake)

    p = app_module.OSPanel(root, "Darwin", lambda msg, error=False: None)
    root.update()
    p.generate_preview()
    p.apply_mac()
    assert renew_calls == ["en0"]


def test_apply_on_windows_does_not_trigger_macos_renew(panel, fake_backend):
    """The auto-renew is a macOS-specific mitigation; Windows must not call it."""
    import backend_macos
    calls = []
    backend_macos.renew_ip = lambda device: calls.append(device)
    panel.generate_preview()
    panel.apply_mac()
    assert calls == []


def test_restore_calls_backend(panel, fake_backend):
    panel.restore_mac()
    assert fake_backend["restored"] is True


def test_active_adapter_preferred_over_first_listed(root, monkeypatch):
    """
    Real-world bug: networksetup often lists 'Thunderbolt Bridge' before
    'Wi-Fi' even when only Wi-Fi is connected. The panel must prefer
    whichever adapter actually has an IP, not just take index 0.
    """
    fake = types.ModuleType("backend_windows")
    fake.list_adapters = lambda: [
        {"Name": "Bridge0", "InterfaceDescription": "Thunderbolt Bridge",
         "MacAddress": "00-00-00-00-00-01", "Status": "Up"},
        {"Name": "WiFi0", "InterfaceDescription": "Wi-Fi",
         "MacAddress": "00-00-00-00-00-02", "Status": "Up"},
    ]
    # Only the Wi-Fi-like adapter actually has an IP -- Thunderbolt Bridge doesn't.
    fake.get_current_ip = lambda name: "192.168.1.50" if name == "WiFi0" else None
    monkeypatch.setitem(sys.modules, "backend_windows", fake)

    messages = []
    p = app_module.OSPanel(root, "Windows", lambda msg, error=False: messages.append((msg, error)))
    root.update()
    assert p.current_adapter["id"] == "WiFi0"


# --- IPOctetEntry widget ---

def test_ip_octet_entry_get_set_roundtrip(root):
    entry = app_module.IPOctetEntry(root)
    entry.set_value("192.168.1.42")
    assert entry.get_value() == "192.168.1.42"


def test_ip_octet_entry_defaults_to_empty_dotted(root):
    entry = app_module.IPOctetEntry(root)
    assert entry.get_value() == "..."


# --- static IP apply / revert to DHCP ---

def test_apply_static_ip_rejects_invalid_input_without_calling_backend(panel, fake_backend):
    fake_backend["static_ip_calls"] = []
    import backend_windows
    backend_windows.set_static_ip = lambda *a: fake_backend["static_ip_calls"].append(a)

    panel.ip_octets.set_value("999.1.1.1")  # invalid octet
    panel.mask_octets.set_value("255.255.255.0")
    panel.gateway_octets.set_value("192.168.1.1")
    panel.apply_static_ip()

    assert fake_backend["static_ip_calls"] == []
    assert any(err for _, err in panel.messages), "expected an error to be logged"


def test_apply_static_ip_calls_backend_with_converted_prefix(panel, fake_backend):
    calls = []
    import backend_windows
    backend_windows.set_static_ip = lambda name, ip, prefix, gw: calls.append((name, ip, prefix, gw))

    panel.ip_octets.set_value("192.168.1.50")
    panel.mask_octets.set_value("255.255.255.0")
    panel.gateway_octets.set_value("192.168.1.1")
    panel.apply_static_ip()

    assert calls == [("Ethernet0", "192.168.1.50", 24, "192.168.1.1")]


def test_revert_to_dhcp_calls_backend(panel, fake_backend):
    calls = []
    import backend_windows
    backend_windows.set_dhcp = lambda name: calls.append(name)

    panel.revert_to_dhcp()
    assert calls == ["Ethernet0"]


def test_sidebar_starts_on_mac_section(panel):
    assert panel.active_section == "mac"
    assert panel.mac_section.winfo_manager() == "grid"
    assert panel.ip_section.winfo_manager() == ""


def test_sidebar_switches_to_ip_section(panel):
    panel._show_section("ip")
    assert panel.active_section == "ip"
    assert panel.ip_section.winfo_manager() == "grid"
    assert panel.mac_section.winfo_manager() == ""


def test_sidebar_nav_button_highlights_active_section(panel):
    panel._show_section("ip")
    assert panel.nav_buttons["ip"].cget("fg_color") != "transparent"
    assert panel.nav_buttons["mac"].cget("fg_color") == "transparent"


# --- is_wifi passthrough (Wi-Fi vs. Ethernet needs a different recovery path) ---

def test_apply_mac_passes_is_wifi_true_for_a_wifi_adapter(root, monkeypatch):
    fake = types.ModuleType("backend_macos")
    fake.list_adapters = lambda: [{"port": "Wi-Fi", "device": "en0", "mac": "F0:18:98:1B:D7:93"}]
    fake.get_current_ip = lambda device: "192.168.1.50"
    fake.get_live_mac = lambda device: None
    fake.renew_ip = lambda device: None
    calls = []
    fake.set_mac_address = lambda device, mac, is_wifi=False: calls.append((device, mac, is_wifi))
    monkeypatch.setitem(sys.modules, "backend_macos", fake)

    p = app_module.OSPanel(root, "Darwin", lambda msg, error=False: None)
    root.update()
    p.generate_preview()
    pending = p.pending_mac
    p.apply_mac()
    assert calls == [("en0", pending, True)]


def test_apply_mac_passes_is_wifi_false_for_ethernet(root, monkeypatch):
    fake = types.ModuleType("backend_macos")
    fake.list_adapters = lambda: [{"port": "USB 10/100/1000 LAN", "device": "en5", "mac": "AC:DE:48:00:11:22"}]
    fake.get_current_ip = lambda device: "192.168.1.50"
    fake.get_live_mac = lambda device: None
    fake.renew_ip = lambda device: None
    calls = []
    fake.set_mac_address = lambda device, mac, is_wifi=False: calls.append((device, mac, is_wifi))
    monkeypatch.setitem(sys.modules, "backend_macos", fake)

    p = app_module.OSPanel(root, "Darwin", lambda msg, error=False: None)
    root.update()
    p.generate_preview()
    pending = p.pending_mac
    p.apply_mac()
    assert calls == [("en5", pending, False)]


# --- sticky adapter selection (field bug: jumped to Thunderbolt Bridge) ---

def test_refresh_keeps_selection_even_if_it_transiently_has_no_ip(root, monkeypatch):
    """
    Field bug: right after applying a MAC change, Wi-Fi can briefly have
    no IP while it reconnects. A refresh during that window must NOT
    jump to a different adapter (e.g. Thunderbolt Bridge) just because
    Wi-Fi's IP check failed at that exact moment.
    """
    fake = types.ModuleType("backend_windows")
    fake.list_adapters = lambda: [
        {"Name": "Bridge0", "InterfaceDescription": "Thunderbolt Bridge",
         "MacAddress": "00-00-00-00-00-01", "Status": "Up"},
        {"Name": "WiFi0", "InterfaceDescription": "Wi-Fi",
         "MacAddress": "00-00-00-00-00-02", "Status": "Up"},
    ]
    ip_state = {"WiFi0": "192.168.1.50"}  # starts with an IP
    fake.get_current_ip = lambda name: ip_state.get(name)
    monkeypatch.setitem(sys.modules, "backend_windows", fake)

    p = app_module.OSPanel(root, "Windows", lambda msg, error=False: None)
    root.update()
    assert p.current_adapter["id"] == "WiFi0"  # correctly auto-picked at first

    ip_state.clear()  # simulate Wi-Fi transiently losing its IP mid-reconnect
    p.refresh_adapters()
    assert p.current_adapter["id"] == "WiFi0", "must stay on Wi-Fi, not jump to Bridge0"
