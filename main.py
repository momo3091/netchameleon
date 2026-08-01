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
                  "mac": a.get("mac", "").upper(), "service_name": a["port"]} for a in raw]


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
                                        text_color=COLOR_TEXT_DIM, anchor="w")
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
# One full panel of controls for a given OS.
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

        self.grid_columnconfigure(0, weight=1)

        # --- adapter picker row ---------------------------------------
        picker_row = ctk.CTkFrame(self, fg_color="transparent")
        picker_row.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        picker_row.grid_columnconfigure(0, weight=1)

        self.adapter_menu = ctk.CTkOptionMenu(
            picker_row, values=["(aucun adaptateur détecté)"], command=self._on_adapter_change,
            fg_color=COLOR_PANEL_ALT, button_color=COLOR_BORDER, button_hover_color=COLOR_BORDER,
            dropdown_fg_color=COLOR_PANEL_ALT, font=ui_font(13), dropdown_font=ui_font(13),
        )
        self.adapter_menu.grid(row=0, column=0, sticky="ew", ipady=4)

        refresh_btn = ctk.CTkButton(picker_row, text="🔄 Actualiser", width=110, command=self.refresh_adapters,
                                     fg_color=COLOR_PANEL_ALT, hover_color=COLOR_BORDER, font=ui_font(13))
        refresh_btn.grid(row=0, column=1, padx=(10, 0))

        # --- identity cards ---------------------------------------------
        cards_row = ctk.CTkFrame(self, fg_color="transparent")
        cards_row.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        cards_row.grid_columnconfigure((0, 1), weight=1)

        self.current_card = IdentityCard(cards_row, "ADRESSE ACTUELLE")
        self.current_card.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.preview_card = IdentityCard(cards_row, "NOUVELLE ADRESSE (aperçu)")
        self.preview_card.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        # --- generation mode ---------------------------------------------
        mode_box = ctk.CTkFrame(self, fg_color=COLOR_PANEL, corner_radius=14, border_width=1,
                                 border_color=COLOR_BORDER)
        mode_box.grid(row=2, column=0, sticky="ew", pady=(0, 16))
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

        # --- action buttons ---------------------------------------------
        actions_row = ctk.CTkFrame(self, fg_color="transparent")
        actions_row.grid(row=3, column=0, sticky="ew", pady=(0, 16))
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

        # --- IP row ---------------------------------------------
        ip_row = ctk.CTkFrame(self, fg_color=COLOR_PANEL, corner_radius=14, border_width=1,
                               border_color=COLOR_BORDER)
        ip_row.grid(row=4, column=0, sticky="ew")
        ip_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(ip_row, text="Adresse IP locale (DHCP)", font=ui_font(13, "bold"), text_color=COLOR_TEXT
                     ).grid(row=0, column=0, padx=16, pady=14, sticky="w")
        renew_btn = ctk.CTkButton(ip_row, text="🔁  Renouveler l'IP", command=self.renew_ip, width=160,
                                   fg_color=COLOR_PANEL_ALT, hover_color=COLOR_BORDER, font=ui_font(13))
        renew_btn.grid(row=0, column=1, padx=16, pady=14)

        self.refresh_adapters()

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
        best = self._pick_active_adapter(self.adapters)
        self.adapter_menu.set(best["label"])
        self._select_adapter(best)

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
                be.set_mac_address(self.current_adapter["id"], self.pending_mac)
            self.log(f"[{self.os_name}] Adresse appliquée avec succès : {self.pending_mac}")
        except Exception as exc:  # noqa: BLE001 -- shown to user, app must keep running
            self.log(f"[{self.os_name}] Échec de l'application : {exc}", error=True)
        finally:
            self.refresh_adapters()

    def restore_mac(self):
        if not (self.current_adapter and self.original_mac):
            return
        try:
            if self.os_name == "Windows":
                import backend_windows as be
                be.restore_original_mac(self.current_adapter["id"])
            else:
                import backend_macos as be
                be.restore_original_mac(self.current_adapter["id"], self.original_mac)
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


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("NetChameleon")
        self.geometry("880x760")
        self.configure(fg_color=COLOR_BG)
        self.minsize(760, 680)

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
        self.log_box = ctk.CTkTextbox(log_frame, height=190, fg_color=COLOR_PANEL_ALT, text_color=COLOR_TEXT,
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

        # Now that self.log_box exists, it's safe for a panel's initial
        # refresh_adapters() call to log to it.
        pad = dict(padx=18, pady=16)
        self.win_panel = OSPanel(win_tab, "Windows", self.log)
        self.win_panel.grid(row=0, column=0, sticky="ew", **pad)
        self.mac_panel = OSPanel(mac_tab, "Darwin", self.log)
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
