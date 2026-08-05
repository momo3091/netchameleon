"""
NetChameleon
Cross-platform desktop utility to view and change the MAC / IP identity
of your own network adapter, with a native-feeling panel for Windows and
one for macOS.

Run:
    Windows (as Administrator):  python main.py
    macOS   (needs sudo for the actual changes): python main.py

See README.md for setup, permissions, and the honest list of platform
limitations (especially Wi-Fi MAC spoofing on modern macOS).
"""

import platform
import datetime
import time
import customtkinter as ctk

import mac_utils
import oui_database as ouidb

# --------------------------------------------------------------------------
# Design tokens -- deliberately not the default CTk blue-on-gray theme.
# Palette: deep ink-navy base, teal accent for "new identity", warm amber
# for "current / original identity", soft coral for restore/danger actions.
# --------------------------------------------------------------------------
COLOR_BG = "#12151B"
COLOR_PANEL = "#1A1E27"
COLOR_PANEL_ALT = "#20242F"
COLOR_BORDER = "#2A3040"
COLOR_TEXT = "#E8EAED"
COLOR_TEXT_DIM = "#8B93A7"
COLOR_TEAL = "#3DDC97"
COLOR_TEAL_HOVER = "#31B87F"
COLOR_AMBER = "#FFB454"
COLOR_CORAL = "#FF6B6B"
COLOR_CORAL_HOVER = "#E85555"

MONO_FAMILY = {"Windows": "Consolas", "Darwin": "Menlo"}.get(platform.system(), "Courier New")

ctk.set_appearance_mode("dark")


def mono_font(size=15, weight="normal"):
    return ctk.CTkFont(family=MONO_FAMILY, size=size, weight=weight)


def ui_font(size=13, weight="normal"):
    return ctk.CTkFont(size=size, weight=weight)


def now_str():
    return datetime.datetime.now().strftime("%H:%M:%S")


# --------------------------------------------------------------------------
# Backend adapters normalized to a common shape:
#   {"id": <used for MAC ops>, "label": <shown to user>, "mac": <AA:BB:..>}
# --------------------------------------------------------------------------
def normalized_adapters(os_name: str):
    if os_name == "Windows":
        import backend_windows as be
        raw = be.list_adapters()
        return [{"id": a["Name"], "label": f'{a["Name"]} ({a.get("InterfaceDescription", "")})',
                  "mac": a.get("MacAddress", "").replace("-", ":").upper()} for a in raw]
    else:
        import backend_macos as be
        raw = be.list_adapters()
        return [{"id": a["device"], "label": f'{a["port"]} ({a["device"]})',
                  "mac": a.get("mac", "").upper(), "service_name": a["port"],
                  "is_wifi": a["port"].strip().lower() in ("wi-fi", "airport")} for a in raw]


# --------------------------------------------------------------------------
# The "signature" widget: an ID-badge style card for the current identity.
# --------------------------------------------------------------------------
class IdentityCard(ctk.CTkFrame):
    KIND_COLORS = {"connected": COLOR_TEAL, "disconnected": COLOR_CORAL, "pending": COLOR_AMBER}

    def __init__(self, master, title):
        super().__init__(master, fg_color=COLOR_PANEL_ALT, corner_radius=14,
                          border_width=1, border_color=COLOR_BORDER)
        self._dot = ctk.CTkLabel(self, text="●", font=ui_font(14), text_color=COLOR_TEXT_DIM, width=14)
        self._dot.grid(row=0, column=0, rowspan=2, padx=(16, 4), pady=14, sticky="n")

        self._title = ctk.CTkLabel(self, text=title, font=ui_font(12), text_color=COLOR_TEXT_DIM, anchor="w")
        self._title.grid(row=0, column=1, padx=(0, 16), pady=(14, 0), sticky="w")

        self._mac_label = ctk.CTkLabel(self, text="--:--:--:--:--:--", font=mono_font(19, "bold"),
                                        text_color=COLOR_TEXT, anchor="w")
        self._mac_label.grid(row=1, column=1, padx=(0, 16), pady=(0, 4), sticky="w")

        self._sub_label = ctk.CTkLabel(self, text="IP -- · vendeur inconnu", font=ui_font(12),
                                        text_color=COLOR_TEXT_DIM, anchor="w", justify="left", wraplength=320)
        self._sub_label.grid(row=2, column=1, padx=(0, 16), pady=(0, 14), sticky="w")

        self.grid_columnconfigure(1, weight=1)

    def update_card(self, mac: str, ip: str = None, vendor_guess: str = None, note: str = None, kind: str = "current"):
        color = self.KIND_COLORS.get(kind, COLOR_TEXT_DIM)
        self._dot.configure(text_color=color)
        self._mac_label.configure(text=mac or "--:--:--:--:--:--", text_color=COLOR_TEXT if mac else COLOR_TEXT_DIM)
        ip_part = ip or "IP inconnue"
        if note:
            vendor_part = note
        elif vendor_guess:
            vendor_part = f"probable: {vendor_guess}"
        else:
            vendor_part = "vendeur non identifié"
        self._sub_label.configure(text=f"{ip_part}  ·  {vendor_part}")


# --------------------------------------------------------------------------
# A "[ . . . . ]" style entry for one IPv4 address, one octet per box.
# --------------------------------------------------------------------------
class IPOctetEntry(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.boxes = []
        for i in range(4):
            box = ctk.CTkEntry(self, width=44, justify="center", font=mono_font(14),
                                fg_color=COLOR_PANEL_ALT, border_color=COLOR_BORDER, border_width=1)
            box.grid(row=0, column=i * 2, padx=(0 if i == 0 else 3))
            box.bind("<KeyRelease>", lambda e, idx=i: self._on_key_release(idx, e))
            box.bind("<BackSpace>", lambda e, idx=i: self._on_backspace(idx, e))
            self.boxes.append(box)
            if i < 3:
                ctk.CTkLabel(self, text=".", font=ui_font(16, "bold"), text_color=COLOR_TEXT_DIM, width=6
                             ).grid(row=0, column=i * 2 + 1)

    def _on_key_release(self, idx, event):
        box = self.boxes[idx]
        digits = "".join(c for c in box.get() if c.isdigit())[:3]
        if digits and int(digits) > 255:
            digits = digits[:2]
        if digits != box.get():
            box.delete(0, "end")
            box.insert(0, digits)
        if len(digits) >= 3 and idx < 3 and event.keysym not in ("BackSpace", "Delete", "Left", "Right"):
            self.boxes[idx + 1].focus_set()
            self.boxes[idx + 1].select_range(0, "end")

    def _on_backspace(self, idx, event):
        if not self.boxes[idx].get() and idx > 0:
            self.boxes[idx - 1].focus_set()
            self.boxes[idx - 1].select_range(0, "end")

    def get_value(self) -> str:
        return ".".join(b.get().strip() for b in self.boxes)

    def set_value(self, ip: str):
        parts = (ip or "").split(".")
        for i, box in enumerate(self.boxes):
            box.delete(0, "end")
            if i < len(parts):
                box.insert(0, parts[i])


# --------------------------------------------------------------------------
# One full panel of controls for a given OS: sidebar nav + content area.
# --------------------------------------------------------------------------
class OSPanel(ctk.CTkFrame):
    def __init__(self, master, os_name: str, log_fn):
        super().__init__(master, fg_color="transparent")
        self.os_name = os_name
        self.log = log_fn
        self.adapters = []
        self.current_adapter = None
        self.original_mac = None
        self.pending_mac = None
        self.nav_buttons = {}

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ==================================================== SIDEBAR ====
        sidebar = ctk.CTkFrame(self, fg_color=COLOR_PANEL, corner_radius=14, border_width=1,
                                border_color=COLOR_BORDER, width=196)
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(sidebar, text="ADAPTATEUR", font=ui_font(10, "bold"), text_color=COLOR_TEXT_DIM, anchor="w"
                     ).grid(row=0, column=0, padx=14, pady=(18, 4), sticky="w")
        self.adapter_menu = ctk.CTkOptionMenu(
            sidebar, values=["(aucun adaptateur détecté)"], command=self._on_adapter_change,
            fg_color=COLOR_PANEL_ALT, button_color=COLOR_BORDER, button_hover_color=COLOR_BORDER,
            dropdown_fg_color=COLOR_PANEL_ALT, font=ui_font(12), dropdown_font=ui_font(12), width=168,
        )
        self.adapter_menu.grid(row=1, column=0, padx=14, sticky="ew", ipady=2)

        refresh_btn = ctk.CTkButton(sidebar, text="🔄  Actualiser", command=self.refresh_adapters, anchor="w",
                                     fg_color="transparent", hover_color=COLOR_PANEL_ALT, font=ui_font(11),
                                     text_color=COLOR_TEXT_DIM, height=26)
        refresh_btn.grid(row=2, column=0, padx=12, pady=(4, 16), sticky="ew")

        ctk.CTkFrame(sidebar, height=1, fg_color=COLOR_BORDER).grid(row=3, column=0, padx=14, sticky="ew")

        ctk.CTkLabel(sidebar, text="SECTIONS", font=ui_font(10, "bold"), text_color=COLOR_TEXT_DIM, anchor="w"
                     ).grid(row=4, column=0, padx=14, pady=(16, 4), sticky="w")

        self.nav_buttons["mac"] = self._make_nav_button(sidebar, "🔑  Adresse MAC", "mac")
        self.nav_buttons["mac"].grid(row=5, column=0, padx=10, pady=2, sticky="ew")
        self.nav_buttons["ip"] = self._make_nav_button(sidebar, "🌐  Adresse IP", "ip")
        self.nav_buttons["ip"].grid(row=6, column=0, padx=10, pady=2, sticky="ew")

        sidebar.grid_rowconfigure(7, weight=1)  # spacer pushes the status chip to the bottom

        status_row = ctk.CTkFrame(sidebar, fg_color="transparent")
        status_row.grid(row=8, column=0, padx=14, pady=(0, 18), sticky="w")
        self.status_dot = ctk.CTkLabel(status_row, text="●", font=ui_font(11), text_color=COLOR_TEXT_DIM, width=12)
        self.status_dot.grid(row=0, column=0)
        self.status_label = ctk.CTkLabel(status_row, text="--", font=ui_font(11), text_color=COLOR_TEXT_DIM,
                                          anchor="w")
        self.status_label.grid(row=0, column=1, padx=(4, 0))

        # ==================================================== CONTENT ====
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        # --- MAC section --------------------------------------------
        self.mac_section = ctk.CTkFrame(content, fg_color="transparent")
        self.mac_section.grid_columnconfigure(0, weight=1)

        cards_row = ctk.CTkFrame(self.mac_section, fg_color="transparent")
        cards_row.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        cards_row.grid_columnconfigure((0, 1), weight=1)

        self.current_card = IdentityCard(cards_row, "ADRESSE ACTUELLE")
        self.current_card.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.preview_card = IdentityCard(cards_row, "NOUVELLE ADRESSE (aperçu)")
        self.preview_card.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        mode_box = ctk.CTkFrame(self.mac_section, fg_color=COLOR_PANEL, corner_radius=14, border_width=1,
                                 border_color=COLOR_BORDER)
        mode_box.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        mode_box.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(mode_box, text="Mode de génération", font=ui_font(13, "bold"), text_color=COLOR_TEXT
                     ).grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 6), sticky="w")

        self.mode_var = ctk.StringVar(value="random")
        vendor_radio = ctk.CTkRadioButton(mode_box, text="Style constructeur :",
                                           variable=self.mode_var, value="vendor", command=self._on_mode_change,
                                           font=ui_font(13), fg_color=COLOR_TEAL, hover_color=COLOR_TEAL_HOVER)
        vendor_radio.grid(row=1, column=0, padx=16, pady=4, sticky="w")

        self.vendor_menu = ctk.CTkOptionMenu(mode_box, values=ouidb.all_vendor_names(), width=160,
                                              fg_color=COLOR_PANEL_ALT, button_color=COLOR_BORDER,
                                              button_hover_color=COLOR_BORDER, dropdown_fg_color=COLOR_PANEL_ALT,
                                              font=ui_font(13), state="disabled")
        self.vendor_menu.grid(row=1, column=1, padx=(0, 16), pady=4, sticky="w")

        random_radio = ctk.CTkRadioButton(mode_box, text="Aléatoire respectueuse de la vie privée (recommandé)",
                                           variable=self.mode_var, value="random", command=self._on_mode_change,
                                           font=ui_font(13), fg_color=COLOR_TEAL, hover_color=COLOR_TEAL_HOVER)
        random_radio.grid(row=2, column=0, columnspan=2, padx=16, pady=(4, 14), sticky="w")

        actions_row = ctk.CTkFrame(self.mac_section, fg_color="transparent")
        actions_row.grid(row=2, column=0, sticky="ew")
        actions_row.grid_columnconfigure((0, 1, 2), weight=1)

        gen_btn = ctk.CTkButton(actions_row, text="🎲  Générer une adresse", command=self.generate_preview,
                                 fg_color=COLOR_PANEL_ALT, hover_color=COLOR_BORDER, font=ui_font(13, "bold"),
                                 height=38)
        gen_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.apply_btn = ctk.CTkButton(actions_row, text="✅  Appliquer", command=self.apply_mac,
                                        fg_color=COLOR_TEAL, hover_color=COLOR_TEAL_HOVER, text_color="#0A1410",
                                        font=ui_font(13, "bold"), height=38, state="disabled")
        self.apply_btn.grid(row=0, column=1, sticky="ew", padx=6)

        restore_btn = ctk.CTkButton(actions_row, text="↺  Restaurer l'originale", command=self.restore_mac,
                                     fg_color="transparent", hover_color=COLOR_CORAL_HOVER,
                                     border_width=1, border_color=COLOR_CORAL, text_color=COLOR_CORAL,
                                     font=ui_font(13, "bold"), height=38)
        restore_btn.grid(row=0, column=2, sticky="ew", padx=(6, 0))

        # --- IP section ---------------------------------------------
        self.ip_section = ctk.CTkFrame(content, fg_color="transparent")
        self.ip_section.grid_columnconfigure(0, weight=1)

        ip_row = ctk.CTkFrame(self.ip_section, fg_color=COLOR_PANEL, corner_radius=14, border_width=1,
                               border_color=COLOR_BORDER)
        ip_row.grid(row=0, column=0, sticky="ew")
        ip_row.grid_columnconfigure(0, weight=1)

        dhcp_line = ctk.CTkFrame(ip_row, fg_color="transparent")
        dhcp_line.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 10))
        dhcp_line.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(dhcp_line, text="Adresse IP locale (DHCP)", font=ui_font(13, "bold"), text_color=COLOR_TEXT
                     ).grid(row=0, column=0, sticky="w")
        renew_btn = ctk.CTkButton(dhcp_line, text="🔁  Renouveler l'IP", command=self.renew_ip, width=160,
                                   fg_color=COLOR_PANEL_ALT, hover_color=COLOR_BORDER, font=ui_font(13))
        renew_btn.grid(row=0, column=1)

        ctk.CTkFrame(ip_row, height=1, fg_color=COLOR_BORDER).grid(row=1, column=0, sticky="ew", padx=16)

        ctk.CTkLabel(ip_row, text="IP manuelle (statique)", font=ui_font(13, "bold"), text_color=COLOR_TEXT
                     ).grid(row=2, column=0, padx=16, pady=(14, 8), sticky="w")

        fields = ctk.CTkFrame(ip_row, fg_color="transparent")
        fields.grid(row=3, column=0, padx=16, sticky="w")
        for r, (label, attr) in enumerate([("IP", "ip_octets"), ("Masque", "mask_octets"), ("Passerelle", "gateway_octets")]):
            ctk.CTkLabel(fields, text=label, font=ui_font(11), text_color=COLOR_TEXT_DIM, width=80, anchor="w"
                         ).grid(row=r, column=0, sticky="w", pady=3)
            entry = IPOctetEntry(fields)
            entry.grid(row=r, column=1, pady=3, sticky="w")
            setattr(self, attr, entry)
        self.mask_octets.set_value("255.255.255.0")

        ip_buttons = ctk.CTkFrame(ip_row, fg_color="transparent")
        ip_buttons.grid(row=4, column=0, padx=16, pady=(12, 18), sticky="w")
        apply_ip_btn = ctk.CTkButton(ip_buttons, text="Appliquer l'IP statique", command=self.apply_static_ip,
                                      fg_color=COLOR_TEAL, hover_color=COLOR_TEAL_HOVER, text_color="#0A1410",
                                      font=ui_font(13, "bold"), height=34)
        apply_ip_btn.grid(row=0, column=0, padx=(0, 8))
        dhcp_revert_btn = ctk.CTkButton(ip_buttons, text="Repasser en DHCP", command=self.revert_to_dhcp,
                                         fg_color="transparent", hover_color=COLOR_PANEL_ALT, border_width=1,
                                         border_color=COLOR_BORDER, font=ui_font(13), height=34)
        dhcp_revert_btn.grid(row=0, column=1)

        self._show_section("mac")
        self.refresh_adapters()

    def _make_nav_button(self, parent, text, section_key):
        return ctk.CTkButton(
            parent, text=text, anchor="w", font=ui_font(13), command=lambda: self._show_section(section_key),
            fg_color="transparent", hover_color=COLOR_PANEL_ALT, text_color=COLOR_TEXT_DIM,
            height=38, corner_radius=8,
        )

    def _show_section(self, section_key: str):
        self.active_section = section_key
        for key, btn in self.nav_buttons.items():
            active = key == section_key
            btn.configure(fg_color=COLOR_PANEL_ALT if active else "transparent",
                           text_color=COLOR_TEXT if active else COLOR_TEXT_DIM)
        if section_key == "mac":
            self.ip_section.grid_forget()
            self.mac_section.grid(row=0, column=0, sticky="new")
        else:
            self.mac_section.grid_forget()
            self.ip_section.grid(row=0, column=0, sticky="new")

    # ---------------------------------------------------------------- data
    def refresh_adapters(self):
        try:
            self.adapters = normalized_adapters(self.os_name)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user, not swallowed silently
            self.adapters = []
            self.log(f"[{self.os_name}] Impossible de lister les adaptateurs : {exc}", error=True)

        if not self.adapters:
            self.adapter_menu.configure(values=["(aucun adaptateur détecté)"])
            self.adapter_menu.set("(aucun adaptateur détecté)")
            self.current_adapter = None
            self.current_card.update_card(None)
            return

        labels = [a["label"] for a in self.adapters]
        self.adapter_menu.configure(values=labels)

        # Prefer staying on whatever adapter was already selected, even
        # if it's transiently without an IP (e.g. mid-reconnect right
        # after a MAC change) -- only auto-pick the "best" adapter when
        # there's no existing selection to preserve (first load, or the
        # previously-selected adapter disappeared entirely).
        kept = None
        if self.current_adapter:
            kept = next((a for a in self.adapters if a["id"] == self.current_adapter["id"]), None)
        chosen = kept or self._pick_active_adapter(self.adapters)
        self.adapter_menu.set(chosen["label"])
        self._select_adapter(chosen)

    def _pick_active_adapter(self, adapters):
        """Prefer whichever adapter is actually carrying traffic (has an
        IP) over whatever order the OS happens to list them in -- e.g.
        Thunderbolt Bridge often sorts before Wi-Fi even when only Wi-Fi
        is in use."""
        for adapter in adapters:
            if self._safe_get_ip(adapter):
                return adapter
        return adapters[0]

    def _on_adapter_change(self, label):
        match = next((a for a in self.adapters if a["label"] == label), None)
        if match:
            self._select_adapter(match)

    def _select_adapter(self, adapter):
        self.current_adapter = adapter
        self.original_mac = adapter["mac"]
        self.pending_mac = None
        self.apply_btn.configure(state="disabled")
        self.preview_card.update_card(None)
        self._refresh_current_card()

    def _refresh_current_card(self):
        if not self.current_adapter:
            return
        ip = self._safe_get_ip()
        live_mac = self._safe_get_live_mac()
        display_mac = live_mac or self.current_adapter["mac"]
        vendor = self._guess_vendor(display_mac)
        note = "adresse déjà randomisée par macOS pour ce réseau" \
            if (live_mac and live_mac != self.current_adapter["mac"]) else None
        kind = "connected" if ip else "disconnected"
        self.current_card.update_card(display_mac, ip, vendor_guess=vendor, note=note, kind=kind)
        dot_color = COLOR_TEAL if ip else COLOR_CORAL
        self.status_dot.configure(text_color=dot_color)
        self.status_label.configure(text=self.current_adapter["label"][:22])

    def _safe_get_live_mac(self):
        if self.os_name != "Darwin":
            return None  # Get-NetAdapter on Windows already reflects the live address
        try:
            import backend_macos as be
            return be.get_live_mac(self.current_adapter["id"])
        except Exception:  # noqa: BLE001 -- best-effort, falls back to the hardware address
            return None

    def _safe_get_ip(self, adapter=None):
        adapter = adapter or self.current_adapter
        if not adapter:
            return None
        try:
            if self.os_name == "Windows":
                import backend_windows as be
            else:
                import backend_macos as be
            return be.get_current_ip(adapter["id"])
        except Exception:  # noqa: BLE001 -- IP lookup is best-effort, never fatal
            return None

    @staticmethod
    def _guess_vendor(mac: str):
        if not mac:
            return None
        prefix = mac_utils.mac_vendor_prefix(mac)
        for vendor, info in ouidb.VENDOR_OUIS.items():
            if prefix in info["ouis"]:
                return vendor
        return None

    # ------------------------------------------------------------- actions
    def _on_mode_change(self):
        self.vendor_menu.configure(state="normal" if self.mode_var.get() == "vendor" else "disabled")

    def generate_preview(self):
        if not self.current_adapter:
            self.log("Aucun adaptateur sélectionné.", error=True)
            return
        if self.mode_var.get() == "random":
            new_mac = mac_utils.generate_locally_administered_mac()
            vendor_label = "Aléatoire (bit local)"
        else:
            vendor = self.vendor_menu.get()
            oui = ouidb.random_oui_for_vendor(vendor)
            new_mac = mac_utils.generate_vendor_style_mac(oui)
            vendor_label = f"{ouidb.icon_for_vendor(vendor)} {vendor} ({ouidb.random_model_label(vendor)})"

        self.pending_mac = new_mac
        self.preview_card.update_card(new_mac, ip="IP attribuée après application", vendor_guess=vendor_label, kind="pending")
        self.apply_btn.configure(state="normal")
        self.log(f"[{self.os_name}] Adresse générée : {new_mac} ({vendor_label})")

    def apply_mac(self):
        if not (self.current_adapter and self.pending_mac):
            return
        try:
            if self.os_name == "Windows":
                import backend_windows as be
                be.set_mac_address(self.current_adapter["id"], self.pending_mac)
            else:
                import backend_macos as be
                be.set_mac_address(self.current_adapter["id"], self.pending_mac,
                                    is_wifi=self.current_adapter.get("is_wifi", False))
            self.log(f"[{self.os_name}] Adresse appliquée avec succès : {self.pending_mac}")
            if self.os_name == "Darwin":
                self._renew_ip_after_mac_change()
        except Exception as exc:  # noqa: BLE001 -- shown to user, app must keep running
            self.log(f"[{self.os_name}] Échec de l'application : {exc}", error=True)
        finally:
            self.refresh_adapters()

    def _renew_ip_after_mac_change(self):
        """
        macOS re-validates internet connectivity per MAC address, and can
        briefly show a Wi-Fi '!' / "no internet" warning after a live
        change even though the connection is actually fine. A fresh DHCP
        handshake speeds up that re-validation. Best-effort: if this
        fails, the MAC change itself already succeeded, so we don't
        surface it as an error.
        """
        try:
            import backend_macos as be
            time.sleep(1)
            be.renew_ip(self.current_adapter["id"])
            self.log(f"[{self.os_name}] IP renouvelée (accélère la revalidation Wi-Fi de macOS).")
        except Exception:  # noqa: BLE001
            pass

    def restore_mac(self):
        if not (self.current_adapter and self.original_mac):
            return
        try:
            if self.os_name == "Windows":
                import backend_windows as be
                be.restore_original_mac(self.current_adapter["id"])
            else:
                import backend_macos as be
                be.restore_original_mac(self.current_adapter["id"], self.original_mac,
                                         is_wifi=self.current_adapter.get("is_wifi", False))
            self.log(f"[{self.os_name}] Adresse d'origine restaurée : {self.original_mac}")
        except Exception as exc:  # noqa: BLE001
            self.log(f"[{self.os_name}] Échec de la restauration : {exc}", error=True)
        finally:
            self.refresh_adapters()

    def renew_ip(self):
        if not self.current_adapter:
            return
        try:
            if self.os_name == "Windows":
                import backend_windows as be
                be.renew_ip(self.current_adapter["id"])
            else:
                import backend_macos as be
                be.renew_ip(self.current_adapter["id"])
            self.log(f"[{self.os_name}] Renouvellement DHCP demandé.")
        except Exception as exc:  # noqa: BLE001
            self.log(f"[{self.os_name}] Échec du renouvellement IP : {exc}", error=True)
        finally:
            self._refresh_current_card()

    def apply_static_ip(self):
        if not self.current_adapter:
            self.log("Aucun adaptateur sélectionné.", error=True)
            return
        ip, mask, gw = self.ip_octets.get_value(), self.mask_octets.get_value(), self.gateway_octets.get_value()
        for label, value in (("IP", ip), ("masque", mask), ("passerelle", gw)):
            if not mac_utils.is_valid_ipv4(value):
                self.log(f"[{self.os_name}] Adresse {label} invalide : '{value}'", error=True)
                return
        try:
            if self.os_name == "Windows":
                import backend_windows as be
                prefix = mac_utils.netmask_to_prefix_len(mask)
                be.set_static_ip(self.current_adapter["id"], ip, prefix, gw)
            else:
                import backend_macos as be
                be.set_static_ip(self.current_adapter["service_name"], ip, mask, gw)
            self.log(f"[{self.os_name}] IP statique appliquée : {ip}")
        except Exception as exc:  # noqa: BLE001 -- includes a malformed netmask, surfaced not swallowed
            self.log(f"[{self.os_name}] Échec de l'IP statique : {exc}", error=True)
        finally:
            self._refresh_current_card()

    def revert_to_dhcp(self):
        if not self.current_adapter:
            return
        try:
            if self.os_name == "Windows":
                import backend_windows as be
                be.set_dhcp(self.current_adapter["id"])
            else:
                import backend_macos as be
                be.set_dhcp(self.current_adapter["service_name"])
            self.log(f"[{self.os_name}] Repassé en DHCP automatique.")
        except Exception as exc:  # noqa: BLE001
            self.log(f"[{self.os_name}] Échec du retour en DHCP : {exc}", error=True)
        finally:
            self._refresh_current_card()


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("NetChameleon")
        self.configure(fg_color=COLOR_BG)

        # Size relative to the actual screen instead of a fixed guess --
        # a fixed height doesn't account for smaller displays, or menu
        # bar / dock chrome eating into usable vertical space.
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        win_w = max(980, min(1120, int(screen_w * 0.80)))
        win_h = max(680, min(950, int(screen_h * 0.82)))
        self.geometry(f"{win_w}x{win_h}+{(screen_w - win_w) // 2}+{max(0, (screen_h - win_h) // 2 - 20)}")
        self.minsize(min(920, win_w), min(620, win_h))

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(24, 8))
        ctk.CTkLabel(header, text="🦎 NetChameleon", font=ui_font(24, "bold"), text_color=COLOR_TEXT
                     ).pack(side="left")
        ctk.CTkLabel(header, text="identité réseau, sur votre propre appareil",
                     font=ui_font(13), text_color=COLOR_TEXT_DIM).pack(side="left", padx=(12, 0), pady=(6, 0))

        detected = platform.system()
        default_tab = "🪟  Windows" if detected == "Windows" else "🍎  macOS"

        # --- Bottom-anchored widgets are CREATED here (before the panels)
        # because OSPanel.__init__ calls self.log(...) immediately via
        # refresh_adapters(). They are only *packed* further down, once
        # the tabview has claimed the expanding middle area.
        footer = ctk.CTkLabel(
            self, text="À utiliser sur vos propres appareils / réseaux que vous administrez.",
            font=ui_font(11), text_color=COLOR_TEXT_DIM)

        log_frame = ctk.CTkFrame(self, fg_color=COLOR_PANEL_ALT, corner_radius=14)
        ctk.CTkLabel(log_frame, text="Journal", font=ui_font(12, "bold"), text_color=COLOR_TEXT_DIM
                     ).pack(anchor="w", padx=16, pady=(10, 0))
        self.log_box = ctk.CTkTextbox(log_frame, height=145, fg_color=COLOR_PANEL_ALT, text_color=COLOR_TEXT,
                                       font=mono_font(12), activate_scrollbars=True)
        self.log_box.pack(fill="x", padx=16, pady=(4, 14))
        self.log_box.configure(state="disabled")

        note = None
        if detected not in ("Windows", "Darwin"):
            note = ctk.CTkLabel(
                self, text=f"⚠️  Système détecté : {detected}. Les changements réels ne fonctionnent "
                           "que sous Windows ou macOS -- vous pouvez explorer l'interface ici, "
                           "mais lancez l'app sur la machine cible pour l'utiliser pour de vrai.",
                font=ui_font(12), text_color=COLOR_AMBER, wraplength=800, justify="left")

        self.tabview = ctk.CTkTabview(
            self, fg_color=COLOR_PANEL, segmented_button_fg_color=COLOR_PANEL_ALT,
            segmented_button_selected_color=COLOR_TEAL, segmented_button_selected_hover_color=COLOR_TEAL_HOVER,
            segmented_button_unselected_color=COLOR_PANEL_ALT, text_color=COLOR_TEXT,
            text_color_disabled=COLOR_TEXT_DIM, corner_radius=16,
        )
        win_tab = self.tabview.add("🪟  Windows")
        mac_tab = self.tabview.add("🍎  macOS")
        self.tabview.set(default_tab)

        for tab in (win_tab, mac_tab):
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)

        # Each panel lives inside a scrollable frame: if content ever
        # exceeds the visible height (new sections added later, a small
        # display, a shorter window), it scrolls instead of getting
        # silently clipped -- the bug we hit when the log box grew.
        win_scroll = ctk.CTkScrollableFrame(win_tab, fg_color="transparent")
        win_scroll.grid(row=0, column=0, sticky="nsew")
        win_scroll.grid_columnconfigure(0, weight=1)
        mac_scroll = ctk.CTkScrollableFrame(mac_tab, fg_color="transparent")
        mac_scroll.grid(row=0, column=0, sticky="nsew")
        mac_scroll.grid_columnconfigure(0, weight=1)

        # Now that self.log_box exists, it's safe for a panel's initial
        # refresh_adapters() call to log to it.
        pad = dict(padx=18, pady=16)
        self.win_panel = OSPanel(win_scroll, "Windows", self.log)
        self.win_panel.grid(row=0, column=0, sticky="ew", **pad)
        self.mac_panel = OSPanel(mac_scroll, "Darwin", self.log)
        self.mac_panel.grid(row=0, column=0, sticky="ew", **pad)

        # --- Final visual stacking: header (already packed, top) / tabview
        # (expands to fill remaining space) / optional OS note / log / footer.
        footer.pack(side="bottom", pady=(0, 14))
        log_frame.pack(side="bottom", fill="x", padx=28, pady=(4, 12))
        if note is not None:
            note.pack(side="bottom", fill="x", padx=28, pady=(0, 8))
        self.tabview.pack(fill="both", expand=True, padx=28, pady=12)

    def log(self, message: str, error: bool = False):
        self.log_box.configure(state="normal")
        prefix = "✗" if error else "•"
        self.log_box.insert("end", f"[{now_str()}] {prefix} {message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")


if __name__ == "__main__":
    app = App()
    app.mainloop()
