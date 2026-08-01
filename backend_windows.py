"""
backend_windows.py
Windows-specific network operations, driven through PowerShell.

Every function here shells out to `powershell.exe`. That's deliberate:
the PowerShell NetAdapter cmdlets give structured, version-stable output
(via ConvertTo-Json) instead of scraping `ipconfig` text.

Requirements:
  - Must be run with an elevated (Administrator) shell. Changing a
    NetworkAddress or restarting an adapter both need admin rights;
    Windows will raise an access-denied error otherwise, which we
    surface to the caller rather than swallow.
  - Not every NIC driver exposes the "NetworkAddress" advanced property.
    If it's missing, spoofing isn't possible on that adapter and we
    report that clearly instead of pretending it worked.
"""

import json
import subprocess

PS_EXE = "powershell.exe"


class AdapterError(RuntimeError):
    """Raised when an adapter can't be read or changed, with a human reason."""


def _run_ps(command: str, timeout: int = 20) -> str:
    """Run a PowerShell command and return stdout, raising AdapterError on failure."""
    try:
        result = subprocess.run(
            [PS_EXE, "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise AdapterError("powershell.exe introuvable -- ce module ne fonctionne que sous Windows.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdapterError("La commande PowerShell a expiré (timeout).") from exc

    if result.returncode != 0:
        raise AdapterError(result.stderr.strip() or "Commande PowerShell échouée.")
    return result.stdout.strip()


def list_adapters():
    """Return a list of dicts: Name, InterfaceDescription, MacAddress, Status."""
    out = _run_ps(
        "Get-NetAdapter | Where-Object {$_.Virtual -eq $false} | "
        "Select-Object Name, InterfaceDescription, MacAddress, Status | ConvertTo-Json"
    )
    if not out:
        return []
    data = json.loads(out)
    return data if isinstance(data, list) else [data]


def get_current_ip(adapter_name: str):
    out = _run_ps(
        f"Get-NetIPAddress -InterfaceAlias '{adapter_name}' -AddressFamily IPv4 "
        "-ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty IPAddress"
    )
    return out or None


def set_mac_address(adapter_name: str, new_mac: str):
    """
    Set NetworkAddress via the adapter's advanced registry property, then
    restart the adapter so it takes effect. `new_mac` should already be
    validated (mac_utils.is_valid_mac) before calling this.
    """
    compact = new_mac.replace(":", "").upper()
    _run_ps(
        f"Set-NetAdapterAdvancedProperty -Name '{adapter_name}' "
        f"-RegistryKeyword NetworkAddress -RegistryValue {compact} -ErrorAction Stop"
    )
    _run_ps(f"Restart-NetAdapter -Name '{adapter_name}' -Confirm:$false -ErrorAction Stop")


def restore_original_mac(adapter_name: str):
    """
    Remove the NetworkAddress override so the adapter falls back to its
    burned-in hardware MAC, then restart it.
    """
    _run_ps(
        f"Set-NetAdapterAdvancedProperty -Name '{adapter_name}' "
        f"-RegistryKeyword NetworkAddress -RegistryValue '' -ErrorAction SilentlyContinue"
    )
    _run_ps(f"Restart-NetAdapter -Name '{adapter_name}' -Confirm:$false -ErrorAction Stop")


def renew_ip(adapter_name: str):
    """Release then renew the DHCP lease for this adapter."""
    _run_ps(f"ipconfig /release '{adapter_name}'")
    _run_ps(f"ipconfig /renew '{adapter_name}'")


def set_static_ip(adapter_name: str, ip: str, prefix_len: int, gateway: str):
    _run_ps(
        f"Remove-NetIPAddress -InterfaceAlias '{adapter_name}' -Confirm:$false -ErrorAction SilentlyContinue; "
        f"New-NetIPAddress -InterfaceAlias '{adapter_name}' -IPAddress {ip} "
        f"-PrefixLength {prefix_len} -DefaultGateway {gateway} -ErrorAction Stop"
    )
