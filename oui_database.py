"""
oui_database.py
A small starter set of real, IEEE-registered OUI (Organizationally Unique
Identifier) prefixes for well-known laptop/PC vendors.

An OUI is just the first 3 bytes of a MAC address, and the full registry is
public information published by the IEEE (standards.ieee.org) -- it's the
same kind of lookup any router admin page or `arp -a` implicitly relies on.

This file is deliberately a *starter* list, not a complete or guaranteed
up-to-the-minute mirror of the IEEE database. Vendors register new blocks
and retire old ones over time. If you're extending this project:
  - Verify / add prefixes via https://maclookup.app or https://standards.ieee.org
  - Keep one dict entry per vendor: "Vendor Name": ["OUI1", "OUI2", ...]
  - This is a great first pull request for the repo (see README).

The "model" labels shown in the app next to a vendor are illustrative
device-type labels, not a claim that a given OUI is reserved for that exact
model -- vendors don't publish that level of detail, and this app doesn't
pretend otherwise.
"""

VENDOR_OUIS = {
    "Apple": {
        "ouis": ["F0:18:98", "A4:C3:61", "AC:BC:32", "3C:07:54", "DC:A9:04"],
        "sample_models": ["MacBook Pro", "MacBook Air", "iMac", "Mac mini"],
        "icon": "🍎",
    },
    "Dell": {
        # Verified against Dell's registered MA-L blocks.
        "ouis": ["14:B3:1F", "D4:BE:D9", "B8:CA:3A", "00:14:22", "D0:67:E5", "3C:2C:30"],
        "sample_models": ["XPS 13", "Latitude", "Inspiron", "Precision"],
        "icon": "💻",
    },
    "Lenovo": {
        "ouis": ["54:EE:75", "60:F2:62", "F0:79:59", "8C:16:45"],
        "sample_models": ["ThinkPad X1", "IdeaPad", "Legion", "Yoga"],
        "icon": "💻",
    },
    "HP": {
        "ouis": ["3C:52:82", "94:57:A5", "D8:9D:67", "A0:8C:FD"],
        "sample_models": ["EliteBook", "Pavilion", "Spectre", "ProBook"],
        "icon": "💻",
    },
    "ASUS": {
        "ouis": ["1C:87:2C", "70:8B:CD", "AC:22:0B"],
        "sample_models": ["ZenBook", "ROG", "VivoBook"],
        "icon": "💻",
    },
    "Microsoft": {
        "ouis": ["00:15:5D", "7C:1E:52"],
        "sample_models": ["Surface Laptop", "Surface Pro"],
        "icon": "🪟",
    },
    "Acer": {
        "ouis": ["00:1D:73"],
        "sample_models": ["Swift", "Aspire", "Predator"],
        "icon": "💻",
    },
}


def all_vendor_names():
    return list(VENDOR_OUIS.keys())


def random_oui_for_vendor(vendor: str) -> str:
    import random
    return random.choice(VENDOR_OUIS[vendor]["ouis"])


def random_model_label(vendor: str) -> str:
    import random
    return random.choice(VENDOR_OUIS[vendor]["sample_models"])


def icon_for_vendor(vendor: str) -> str:
    return VENDOR_OUIS.get(vendor, {}).get("icon", "💻")
