"""
backend_macos.py
macOS-specific network operations, driven through `networksetup` and
`ifconfig`.

Requirements:
  - Changing a MAC address needs root, so the app will shell out through
    `sudo`. macOS will prompt for the account password in the terminal
    that launched the app the first time in a session.
  - Honest limitation: since Apple Silicon + recent macOS versions, the
    built-in Wi-Fi radio increasingly ignores `ifconfig ... ether` for the
    *active* Wi-Fi interface -- the firmware re-asserts the burned-in
    address on association, so a spoofed MAC can silently revert on
    sleep/reconnect. It tends to work reliably on: Ethernet (incl. USB-C
    dongles), older Intel Macs, and while Wi-Fi is disconnected. We surface
    this in the UI rather than promising it always works. For pure privacy
    rotation on Wi-Fi, macOS's own System Settings > Wi-Fi > Private
    Wi-Fi Address toggle is the officially supported route.
"""

import re
import subprocess

MAC_LINE_RE = re.compile(r"Ethernet Address:\s*([0-9A-Fa-f:]{17})")
DEVICE_LINE_RE = re.compile(r"Device:\s*(\w+)")
PORT_LINE_RE = re.compile(r"Hardware Port:\s*(.+)")


class AdapterError(RuntimeError):
    """Raised when an adapter can't be read or changed, with a human reason."""


def _run(cmd: list, timeout: int = 20, use_sudo: bool = False) -> str:
    full_cmd = (["sudo", "-n"] + cmd) if use_sudo else cmd
    try:
        result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise AdapterError(f"Commande introuvable: {cmd[0]} -- ce module ne fonctionne que sous macOS.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdapterError("La commande a expiré (timeout).") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if use_sudo and ("password" in stderr.lower() or "a terminal is required" in stderr.lower()):
            raise AdapterError(
                "Droits administrateur requis. Lancez l'app depuis un Terminal avec "
                "`sudo python3 main.py` pour pouvoir saisir votre mot de passe."
            )
        raise AdapterError(stderr or f"Échec de la commande: {' '.join(cmd)}")
    return result.stdout.strip()


def list_adapters():
    """Return a list of dicts: port (e.g. 'Wi-Fi'), device (e.g. 'en0'), mac."""
    out = _run(["networksetup", "-listallhardwareports"])
    adapters, current = [], {}
    for line in out.splitlines():
        port_match = PORT_LINE_RE.match(line.strip())
        device_match = DEVICE_LINE_RE.match(line.strip())
        mac_match = MAC_LINE_RE.match(line.strip())
        if port_match:
            if current:
                adapters.append(current)
            current = {"port": port_match.group(1).strip()}
        elif device_match:
            current["device"] = device_match.group(1)
        elif mac_match:
            current["mac"] = mac_match.group(1).upper()
    if current:
        adapters.append(current)
    # Only adapters macOS could actually resolve to a device are useful to us.
    return [a for a in adapters if "device" in a]


def get_current_ip(device: str):
    result = subprocess.run(["ipconfig", "getifaddr", device], capture_output=True, text=True, timeout=10)
    return result.stdout.strip() or None


def get_live_mac(device: str):
    """
    The MAC actually in use on the wire right now -- which can differ from
    the factory address reported by list_adapters()/networksetup. Since
    macOS Monterey, "Private Wi-Fi Address" is on by default per network,
    so en0's live address is often already a locally-administered
    (randomized) one, not the hardware address. `networksetup` always
    reports the hardware address regardless; only a live `ifconfig` query
    reflects what's really active. Returns None if the interface has no
    ether line (e.g. a VPN tunnel) or the command fails.
    """
    try:
        result = subprocess.run(["ifconfig", device], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"ether ([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})", result.stdout)
    return match.group(1).upper() if match else None


def set_mac_address(device: str, new_mac: str):
    """
    Set the MAC address. Tries the direct form first -- `ifconfig <dev>
    ether <mac>` without touching link state, which is what actually
    works on most Wi-Fi drivers on recent macOS. Only falls back to the
    down/change/up bracket if that's rejected, and if the change step
    fails inside that bracket, ALWAYS brings the interface back up
    before raising -- a failed attempt must never leave Wi-Fi disabled.
    """
    try:
        _run(["ifconfig", device, "ether", new_mac.lower()], use_sudo=True)
        return
    except AdapterError:
        pass  # fall through to the more invasive down/up form below

    _run(["ifconfig", device, "down"], use_sudo=True)
    try:
        _run(["ifconfig", device, "ether", new_mac.lower()], use_sudo=True)
    finally:
        _run(["ifconfig", device, "up"], use_sudo=True)


def restore_original_mac(device: str, original_mac: str):
    set_mac_address(device, original_mac)


def renew_ip(device: str):
    _run(["ipconfig", "set", device, "DHCP"], use_sudo=True)


def set_static_ip(service_name: str, ip: str, subnet_mask: str, gateway: str):
    """service_name is the *port* name from list_adapters(), e.g. 'Wi-Fi', not 'en0'."""
    _run(["networksetup", "-setmanual", service_name, ip, subnet_mask, gateway], use_sudo=True)


def set_dhcp(service_name: str):
    _run(["networksetup", "-setdhcp", service_name], use_sudo=True)
