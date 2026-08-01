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
