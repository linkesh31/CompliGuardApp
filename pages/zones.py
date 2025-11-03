# pages/zones.py
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from urllib.parse import urlparse

from services.ui_theme import apply_theme, card, FONTS, PALETTE
from services.ui_shell import PageShell
from services.session import require_user
from services.async_ui import run_async
from services.zones import (
    list_zones,
    create_zone,
    update_zone,
    delete_zone,
    list_cameras_by_zone,
    list_cameras_by_company,  # ← added: fetch all cameras once
    create_camera,
    delete_camera,
    update_camera,
    ALLOWED_SCHEMES,
    MAX_URL_LEN,
)

# Display values (Title Case)
RISK_VALUES = ["Low", "Medium", "High"]
MODE_VALUES = ["Monitor", "Entry"]

# ↓ make refresh less spammy (was 2_000)
AUTO_REFRESH_MS = 5_000
ONLINE_MAX_AGE_SEC = 60
REQUIRED_STREAK = 2

# ───────────────── theme (match Add Admin) ─────────────────
PAGE_BG = "#E6D8C3"
TEXT_FG = "#000000"
ENTRY_BG = "#F5EEDF"
CARD_BG = "#EFE3D0"

PRIMARY = "#0077b6"
PRIMARY_HOVER = "#00b4d8"
SUCCESS = "#22c55e"
SUCCESS_HOVER = "#16a34a"
DANGER = "#ef4444"
DANGER_HOVER = "#dc2626"

TAG_ONLINE_BG = "#E8F5E9"
TAG_ONLINE_FG = "#166534"
TAG_OFFLINE_BG = "#FDECEA"
TAG_OFFLINE_FG = "#991B1B"
TAG_ALT_BG = "#F7F1E6"


def _risk_to_store(v: str) -> str:
    x = (v or "").strip().lower()
    if x in ("low",):
        return "low"
    if x in ("med", "medium"):
        return "med"
    if x in ("high",):
        return "high"
    return "med"

def _risk_to_display(v: str) -> str:
    x = (v or "").strip().lower()
    return {"low": "Low", "med": "Medium", "high": "High"}.get(x, (v or "").strip().title() or "Medium")

def _mode_to_store(v: str) -> str:
    x = (v or "").strip().lower()
    if x in ("monitor",):
        return "monitor"
    if x in ("entry",):
        return "entry"
    return "monitor"

def _mode_to_display(v: str) -> str:
    x = (v or "").strip().lower()
    return {"monitor": "Monitor", "entry": "Entry"}.get(x, (v or "").strip().title() or "Monitor")


def _to_epoch_seconds(ts: Any) -> Optional[float]:
    if ts is None:
        return None
    if hasattr(ts, "timestamp"):
        try:
            return float(ts.timestamp())
        except Exception:
            pass
    if isinstance(ts, datetime):
        try:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts.timestamp()
        except Exception:
            pass
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            pass
    return None

def _camera_fresh(cam: Dict[str, Any]) -> bool:
    now = datetime.now(tz=timezone.utc).timestamp()
    for key in ("last_heartbeat", "last_seen", "last_ping"):
        age = _to_epoch_seconds(cam.get(key))
        if age is not None:
            return (now - age) <= ONLINE_MAX_AGE_SEC
    if "online" in cam:
        return bool(cam.get("online"))
    return False

def _validate_rtsp_for_ui(text: str) -> Optional[str]:
    u = (text or "").strip()
    if not u:
        return "RTSP / Source is required."
    if len(u) > MAX_URL_LEN:
        return f"Source URL is too long (>{MAX_URL_LEN} characters)."
    if any(ch.isspace() for ch in u):
        return "Source URL must not contain spaces."
    p = urlparse(u)
    if (p.scheme or "").lower() not in ALLOWED_SCHEMES:
        allowed = ", ".join(sorted(ALLOWED_SCHEMES))
        return f"Unsupported URL scheme '{p.scheme}'. Allowed: {allowed}."
    if not p.netloc:
        return "Source URL must include a host (e.g., rtsp://host/stream)."
    if p.path is None or len(p.path) == 0:
        return "Source URL must include a path (e.g., rtsp://host/stream)."
    return None


# ───────────────── ZoneWizard ─────────────────
class ZoneWizard(tk.Toplevel):
    def __init__(self, master, *, company_id: str, on_done):
        super().__init__(master)
        self.title("New Zone")
        self.configure(bg=PAGE_BG)
        try:
            self.resizable(False, False)
        except Exception:
            pass

        # Make truly modal & anchored to parent
        try:
            self.transient(master.winfo_toplevel())
        except Exception:
            try:
                self.transient(master)
            except Exception:
                pass
        try:
            self.grab_set()
        except Exception:
            pass

        self.company_id = company_id
        self.on_done = on_done

        apply_theme(self)
        self._init_styles()
        self._build()

    def _init_styles(self):
        self.option_add("*Background", PAGE_BG)
        self.option_add("*Foreground", TEXT_FG)
        self.option_add("*highlightBackground", PAGE_BG)
        self.option_add("*insertBackground", TEXT_FG)
        self.option_add("*troughColor", PAGE_BG)
        self.option_add("*selectBackground", "#2563eb")
        self.option_add("*selectForeground", "#FFFFFF")

        for prefix in ("*TCombobox*Listbox", "*Combobox*Listbox", "*Listbox"):
            self.option_add(f"{prefix}.background", ENTRY_BG)
            self.option_add(f"{prefix}.foreground", TEXT_FG)
            self.option_add(f"{prefix}.selectBackground", "#2563eb")
            self.option_add(f"{prefix}.selectForeground", "#FFFFFF")
            self.option_add(f"{prefix}.highlightBackground", ENTRY_BG)

        s = ttk.Style(self)
        s.configure("Primary.TButton", font=("Segoe UI Semibold", 10), padding=(14, 6),
                    background=PRIMARY, foreground="white", borderwidth=0, relief="flat")
        s.map("Primary.TButton", background=[("active", PRIMARY_HOVER)], relief=[("pressed", "sunken")])

        s.configure("Danger.TButton", font=("Segoe UI Semibold", 10), padding=(14, 6),
                    background=DANGER, foreground="white", borderwidth=0, relief="flat")
        s.map("Danger.TButton", background=[("active", DANGER_HOVER)], relief=[("pressed", "sunken")])

        s.configure("Warm.TCombobox",
                    fieldbackground=ENTRY_BG,
                    background=ENTRY_BG,
                    foreground=TEXT_FG,
                    arrowcolor=TEXT_FG)
        s.map("Warm.TCombobox",
              fieldbackground=[("readonly", ENTRY_BG), ("!disabled", ENTRY_BG), ("active", ENTRY_BG)],
              foreground=[("readonly", TEXT_FG)],
              background=[("readonly", ENTRY_BG), ("!disabled", ENTRY_BG), ("active", ENTRY_BG)],
              arrowcolor=[("readonly", TEXT_FG), ("!disabled", TEXT_FG), ("active", TEXT_FG)])

        s.configure("FormKey.TLabel", background=CARD_BG, foreground="#333333", font=("Segoe UI", 10, "bold"))

    def _make_entry(self, parent, show: str | None = None) -> tk.Entry:
        e = tk.Entry(parent, bg=ENTRY_BG, fg=TEXT_FG, insertbackground=TEXT_FG,
                     relief="flat", highlightthickness=1,
                     highlightbackground="#CBBFA7", highlightcolor="#0096C7",
                     font=("Segoe UI", 10))
        if show:
            e.config(show=show)
        e.bind("<FocusIn>", lambda _e: e.configure(bg="#FFFFFF"))
        e.bind("<FocusOut>", lambda _e: e.configure(bg=ENTRY_BG))
        return e

    def _build(self):
        wrapper = tk.Frame(self, bg=PAGE_BG)
        wrapper.pack(fill="both", expand=True, padx=18, pady=18)

        tk.Label(wrapper, text="Create Zone", font=("Segoe UI Semibold", 16),
                 bg=PAGE_BG, fg="#222222").pack(anchor="w", pady=(0, 8))

        c, inner = card(wrapper, fg=CARD_BG, border_color="#DCCEB5", border_width=2)
        c.pack(fill="x"); c.configure(fg_color=CARD_BG)

        form = tk.Frame(inner, bg=CARD_BG)
        form.pack(fill="x", padx=12, pady=12)
        form.grid_columnconfigure(0, weight=0)
        form.grid_columnconfigure(1, weight=1)

        ttk.Label(form, text="Zone Name", style="FormKey.TLabel").grid(row=0, column=0, sticky="e", padx=(0, 10), pady=6)
        self.z_name = self._make_entry(form); self.z_name.grid(row=0, column=1, sticky="ew", pady=6)

        ttk.Label(form, text="Risk Level", style="FormKey.TLabel").grid(row=1, column=0, sticky="e", padx=(0, 10), pady=6)
        self.z_risk = ttk.Combobox(form, values=RISK_VALUES, state="readonly", style="Warm.TCombobox")
        self.z_risk.set("Medium"); self.z_risk.grid(row=1, column=1, sticky="w", pady=6)

        ttk.Label(form, text="Description", style="FormKey.TLabel").grid(row=2, column=0, sticky="e", padx=(0, 10), pady=6)
        self.z_desc = self._make_entry(form); self.z_desc.grid(row=2, column=1, sticky="ew", pady=6)

        ttk.Separator(form, orient="horizontal").grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 8))

        ttk.Label(form, text="Camera Name", style="FormKey.TLabel").grid(row=4, column=0, sticky="e", padx=(0, 10), pady=6)
        self.cam_name = self._make_entry(form); self.cam_name.grid(row=4, column=1, sticky="ew", pady=6)

        ttk.Label(form, text="RTSP / Source", style="FormKey.TLabel").grid(row=5, column=0, sticky="e", padx=(0, 10), pady=6)
        self.cam_rtsp = self._make_entry(form); self.cam_rtsp.grid(row=5, column=1, sticky="ew", pady=6)

        ttk.Label(form, text="Mode", style="FormKey.TLabel").grid(row=6, column=0, sticky="e", padx=(0, 10), pady=6)
        self.cam_mode = ttk.Combobox(form, values=MODE_VALUES, state="readonly", style="Warm.TCombobox")
        self.cam_mode.set("Monitor"); self.cam_mode.grid(row=6, column=1, sticky="w", pady=6)

        foot = tk.Frame(wrapper, bg=PAGE_BG); foot.pack(fill="x", pady=(12, 0))
        ttk.Button(foot, text="← Cancel", style="Danger.TButton", command=self.destroy).pack(side="left")
        self._save_btn = ttk.Button(foot, text="Save", style="Primary.TButton", command=self._save)
        self._save_btn.pack(side="right")

    def _save(self):
        # UI required-field validation — NEVER closes dialog
        name = (self.z_name.get() or "").strip()
        if not name:
            messagebox.showerror("Zone", "Zone name is required.", parent=self)
            return

        risk = _risk_to_store(self.z_risk.get())
        desc = (self.z_desc.get() or "").strip()

        cam_name = (self.cam_name.get() or "").strip()
        if not cam_name:
            messagebox.showerror("Camera", "Camera name is required.", parent=self)
            return

        rtsp = (self.cam_rtsp.get() or "").strip()
        err = _validate_rtsp_for_ui(rtsp)
        if err:
            messagebox.showerror("Camera Source", err, parent=self)
            return

        mode = _mode_to_store(self.cam_mode.get())

        # Disable save button during async save (so double-click doesn’t close)
        try:
            self._save_btn.configure(state="disabled")
        except Exception:
            pass

        def _work():
            # Backend validation; rollback zone if camera fails.
            z = create_zone(company_id=self.company_id, name=name, description=desc, risk_level=risk)
            zone_id = z["id"]
            try:
                create_camera(company_id=self.company_id, name=cam_name, rtsp_url=rtsp,
                              zone_id=zone_id, mode=mode)
                return True
            except Exception as e:
                try:
                    delete_zone(zone_id, force=True)
                except Exception:
                    pass
                return e

        def _done(result):
            # Re-enable Save so the user can correct and retry
            try:
                self._save_btn.configure(state="normal")
            except Exception:
                pass

            if isinstance(result, Exception):
                messagebox.showerror("Save Failed", str(result), parent=self)
                return

            # Success → show info + refresh parent + close
            messagebox.showinfo("Saved", "Zone and camera created successfully.", parent=self)
            if callable(self.on_done):
                self.on_done()
            self.destroy()

        run_async(_work, _done, self)


# ───────────────── ZonesPage ─────────────────
class ZonesPage(PageShell):
    def __init__(self, parent, controller, user: Optional[Dict[str, Any]] = None, **_):
        super().__init__(parent, controller, title="Zone Management", active_key="zones")
        self.controller = controller
        apply_theme(self)

        # page overrides
        self.option_add("*Background", PAGE_BG)
        self.option_add("*Foreground", TEXT_FG)
        self.option_add("*highlightBackground", PAGE_BG)
        self.option_add("*insertBackground", TEXT_FG)
        self.option_add("*troughColor", PAGE_BG)
        self.option_add("*selectBackground", "#2563eb")
        self.option_add("*selectForeground", "#FFFFFF")
        for prefix in ("*TCombobox*Listbox", "*Combobox*Listbox", "*Listbox"):
            self.option_add(f"{prefix}.background", ENTRY_BG)
            self.option_add(f"{prefix}.foreground", TEXT_FG)
            self.option_add(f"{prefix}.selectBackground", "#2563eb")
            self.option_add(f"{prefix}.selectForeground", "#FFFFFF")
            self.option_add(f"{prefix}.highlightBackground", ENTRY_BG)

        self.company_id: Optional[str] = None
        self._zones: List[Dict[str, Any]] = []
        self._refresh_job: Optional[str] = None
        self._streaks: Dict[str, int] = {}
        self._decision: Dict[str, bool] = {}
        self._COL_ACTIONS_INDEX = 8

        # Strong ref to wizard so it NEVER gets GC'ed unexpectedly
        self._wizard: Optional[ZoneWizard] = None

        self._init_styles()
        self._build(self.content)

        self._refresh_all_async()
        self._schedule_next_refresh()
        try:
            self.bind("<Visibility>", lambda _e: self._refresh_all_async())
        except Exception:
            pass

    def _init_styles(self):
        s = ttk.Style(self)
        s.configure("Primary.TButton", font=("Segoe UI Semibold", 10), padding=(14, 6),
                    background=PRIMARY, foreground="white", borderwidth=0, relief="flat")
        s.map("Primary.TButton", background=[("active", PRIMARY_HOVER)], relief=[("pressed", "sunken")])

        s.configure("Success.TButton", font=("Segoe UI Semibold", 10), padding=(14, 6),
                    background=SUCCESS, foreground="white", borderwidth=0, relief="flat")
        s.map("Success.TButton", background=[("active", SUCCESS_HOVER)], relief=[("pressed", "sunken")])

        s.configure("Danger.TButton", font=("Segoe UI Semibold", 10), padding=(14, 6),
                    background=DANGER, foreground="white", borderwidth=0, relief="flat")
        s.map("Danger.TButton", background=[("active", DANGER_HOVER)], relief=[(["pressed"], "sunken")])

        s.configure("Admin.Treeview",
                    background=CARD_BG, fieldbackground=CARD_BG, foreground=TEXT_FG,
                    rowheight=28, borderwidth=0)
        s.configure("Admin.Treeview.Heading",
                    font=("Segoe UI Semibold", 10), foreground=TEXT_FG, background=CARD_BG, padding=(10, 8))

        s.configure("FormKey.TLabel", background=CARD_BG, foreground="#333333", font=("Segoe UI", 10, "bold"))

        s.configure("Warm.TCombobox",
                    fieldbackground=ENTRY_BG, background=ENTRY_BG, foreground=TEXT_FG, arrowcolor=TEXT_FG)
        s.map("Warm.TCombobox",
              fieldbackground=[("readonly", ENTRY_BG), ("!disabled", ENTRY_BG), ("active", ENTRY_BG)],
              foreground=[("readonly", TEXT_FG)],
              background=[("readonly", ENTRY_BG), ("!disabled", ENTRY_BG), ("active", ENTRY_BG)],
              arrowcolor=[("readonly", TEXT_FG), ("!disabled", TEXT_FG), ("active", TEXT_FG)])

    def _build(self, root: tk.Frame):
        page = tk.Frame(root, bg=PAGE_BG)
        page.pack(fill="both", expand=True, padx=16, pady=16)

        head = tk.Frame(page, bg=PAGE_BG); head.pack(fill="x")
        tk.Label(head, text="Zone Management", font=("Segoe UI Semibold", 16),
                 bg=PAGE_BG, fg="#222222").pack(side="left")

        btns = tk.Frame(head, bg=PAGE_BG); btns.pack(side="right")
        ttk.Button(btns, text="Refresh", style="Success.TButton",
                   command=self._refresh_all_async).pack(side="left")
        ttk.Button(btns, text="New Zone", style="Primary.TButton",
                   command=self._open_wizard).pack(side="left", padx=(8, 0))

        c_card, inner = card(page, fg=CARD_BG, border_color="#DCCEB5", border_width=2)
        c_card.pack(fill="both", expand=True, pady=(12, 0))
        c_card.configure(fg_color=CARD_BG)

        tk.Label(inner, text="Zones", font=("Segoe UI Semibold", 14),
                 bg=CARD_BG, fg="#222222").pack(anchor="w", pady=(0, 6))

        table_wrap = tk.Frame(inner, bg=CARD_BG)
        table_wrap.pack(fill="both", expand=True, padx=6, pady=(0, 0))

        self.tree = ttk.Treeview(
            table_wrap,
            columns=("id", "status", "name", "risk", "description", "camera", "mode", "actions"),
            show="headings",
            height=18,
            style="Admin.Treeview",
            selectmode="none",
        )

        for col, txt in [
            ("status", "Status"),
            ("name", "Zone"),
            ("risk", "Risk"),
            ("description", "Description"),
            ("camera", "Camera"),
            ("mode", "Mode"),
            ("actions", "Actions"),
        ]:
            self.tree.heading(col, text=txt, anchor="center")

        self.tree.column("id", width=1, stretch=False)
        self.tree.column("status", width=140, anchor="center")
        self.tree.column("name", width=220, anchor="center")
        self.tree.column("risk", width=100, anchor="center")
        self.tree.column("description", width=420, anchor="center")
        self.tree.column("camera", width=110, anchor="center")
        self.tree.column("mode", width=110, anchor="center")
        self.tree.column("actions", width=170, anchor="center")

        yscroll = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_wrap.grid_rowconfigure(0, weight=1)
        table_wrap.grid_columnconfigure(0, weight=1)

        for ev in ("<ButtonRelease-1>", "<space>", "<Return>"):
            self.tree.bind(ev, lambda e: "break")
        self.tree.bind("<Button-1>", self._on_tree_click)

        self.tree.tag_configure("row-online", background=TAG_ONLINE_BG, foreground=TAG_ONLINE_FG)
        self.tree.tag_configure("row-offline", background=TAG_OFFLINE_BG, foreground=TAG_OFFLINE_FG)
        self.tree.tag_configure("row-alt", background=TAG_ALT_BG)
        self.tree.tag_configure("row", background=CARD_BG, foreground=TEXT_FG)

        leg = tk.Frame(inner, bg=CARD_BG); leg.pack(fill="x", pady=(8, 2))
        self._chip(leg, "● Online", fg=TAG_ONLINE_FG, bg=TAG_ONLINE_BG).pack(side="left", padx=(0, 8))
        self._chip(leg, "● Offline", fg=TAG_OFFLINE_FG, bg=TAG_OFFLINE_BG).pack(side="left")

    def _chip(self, parent, text, fg="#1f2937", bg="#eef2ff"):
        return tk.Label(parent, text=text, bg=bg, fg=fg, padx=10, pady=4, font=("Segoe UI Semibold", 9))

    def _refresh_all_async(self):
        try:
            user = require_user()
        except Exception as e:
            messagebox.showerror("Zones", f"No session: {e}")
            return

        self.company_id = str(user.get("company_id") or "").strip()
        if not self.company_id:
            self._zones = []
            self._fill_table({})  # pass empty camera map
            return

        def _work():
            try:
                zones = list_zones(self.company_id) or []
                cams = list_cameras_by_company(self.company_id) or []
                cam_by_zone: Dict[str, List[Dict[str, Any]]] = {}
                for c in cams:
                    zid = str(c.get("zone_id") or "")
                    if not zid:
                        continue
                    cam_by_zone.setdefault(zid, []).append(c)
                return (zones, cam_by_zone)
            except Exception as e:
                return e

        def _done(result):
            if isinstance(result, Exception):
                messagebox.showerror("Zones", f"Failed to load: {result}")
                return
            zones, cam_by_zone = result
            self._zones = zones
            self._fill_table(cam_by_zone)

        run_async(_work, _done, self)

    def _debounced_online(self, cam: Dict[str, Any]) -> bool:
        cam_id = str(cam.get("id") or cam.get("name") or "")
        if not cam_id:
            return _camera_fresh(cam)
        fresh = _camera_fresh(cam)
        prev_decision = self._decision.get(cam_id, False)
        streak = self._streaks.get(cam_id, 0)
        if fresh:
            streak = streak + 1 if streak >= 0 else 1
        else:
            streak = streak - 1 if streak <= 0 else -1
        decision = prev_decision
        if streak >= REQUIRED_STREAK:
            decision = True
            streak = min(streak, REQUIRED_STREAK)
        elif streak <= -REQUIRED_STREAK:
            decision = False
            streak = max(streak, -REQUIRED_STREAK)
        self._streaks[cam_id] = streak
        self._decision[cam_id] = decision
        return decision

    def _status_chip_text(self, online: bool) -> str:
        return "● Online" if online else "● Offline"

    # ← now accepts a precomputed camera map (no per-zone queries)
    def _fill_table(self, cam_by_zone: Dict[str, List[Dict[str, Any]]] | None = None):
        cam_by_zone = cam_by_zone or {}

        for r in self.tree.get_children():
            self.tree.delete(r)

        for i, z in enumerate(self._zones):
            cams = cam_by_zone.get(z["id"], [])
            status_txt, cam_txt, tag, mode_disp = "● Offline", "—", "row-offline", "—"
            if cams:
                first = cams[0]
                online = self._debounced_online(first)
                status_txt = self._status_chip_text(online)
                tag = "row-online" if online else "row-offline"
                name = first.get("name") or first.get("id", "")
                mode_disp = _mode_to_display(first.get("mode") or "monitor")
                extra = len(cams) - 1
                cam_txt = f"{name} (+{extra})" if extra > 0 else name

            vals = (
                z["id"], status_txt, z.get("name", ""),
                _risk_to_display(z.get("risk_level") or "med"),
                z.get("description", ""), cam_txt, mode_disp,
                "✏ Edit   🗑 Delete",
            )
            row = self.tree.insert("", "end", values=vals, tags=("row", tag))
            if i % 2:
                self.tree.item(row, tags=self.tree.item(row, "tags") + ("row-alt",))

    def _on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        item_id = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not item_id or col != f"#{self._COL_ACTIONS_INDEX}":
            return
        bbox = self.tree.bbox(item_id, col)
        if not bbox:
            return
        x, _, w, _ = bbox
        relx = event.x - x
        if relx < w / 2:
            self._edit_zone_dialog(item_id)
        else:
            self._delete_zone_cascade(item_id)

    def _edit_zone_dialog(self, item_id: str):
        vals = self.tree.item(item_id, "values")
        if not vals:
            return
        zone_id, _status, cur_name, cur_risk, cur_desc, _camera, cur_mode, _ = vals

        dlg = tk.Toplevel(self); dlg.title("Edit Zone")
        dlg.transient(self.winfo_toplevel()); dlg.grab_set(); dlg.configure(bg=CARD_BG); dlg.resizable(False, False)

        s = ttk.Style(dlg)
        s.configure("FormKey.TLabel", background=CARD_BG, foreground="#333333", font=("Segoe UI", 10, "bold"))
        s.configure("Primary.TButton", font=("Segoe UI Semibold", 10), padding=(14, 6),
                    background=PRIMARY, foreground="white", borderwidth=0, relief="flat")
        s.map("Primary.TButton", background=[("active", PRIMARY_HOVER)])
        s.configure("Danger.TButton", font=("Segoe UI Semibold", 10), padding=(14, 6),
                    background=DANGER, foreground="white", borderwidth=0, relief="flat")
        s.map("Danger.TButton", background=[("active", DANGER_HOVER)])
        s.configure("Warm.TCombobox",
                    fieldbackground=ENTRY_BG, background=ENTRY_BG, foreground=TEXT_FG, arrowcolor=TEXT_FG)
        s.map("Warm.TCombobox",
              fieldbackground=[("readonly", ENTRY_BG), ("!disabled", ENTRY_BG), ("active", ENTRY_BG)],
              foreground=[("readonly", TEXT_FG)],
              background=[("readonly", ENTRY_BG), ("!disabled", ENTRY_BG), ("active", ENTRY_BG)],
              arrowcolor=[("readonly", TEXT_FG), ("!disabled", TEXT_FG), ("active", TEXT_FG)])

        for prefix in ("*TCombobox*Listbox", "*Combobox*Listbox", "*Listbox"):
            dlg.option_add(f"{prefix}.background", ENTRY_BG)
            dlg.option_add(f"{prefix}.foreground", TEXT_FG)
            dlg.option_add(f"{prefix}.selectBackground", "#2563eb")
            dlg.option_add(f"{prefix}.selectForeground", "#FFFFFF")
            dlg.option_add(f"{prefix}.highlightBackground", ENTRY_BG)

        frm = tk.Frame(dlg, bg=CARD_BG); frm.pack(padx=16, pady=16)
        frm.grid_columnconfigure(1, weight=1)

        ttk.Label(frm, text="Zone Name", style="FormKey.TLabel").grid(row=0, column=0, sticky="e", padx=(0, 10), pady=6)
        name_e = tk.Entry(frm, bg=ENTRY_BG, fg=TEXT_FG, relief="flat")
        name_e.insert(0, cur_name); name_e.grid(row=0, column=1, sticky="ew", pady=6)

        ttk.Label(frm, text="Risk", style="FormKey.TLabel").grid(row=1, column=0, sticky="e", padx=(0, 10), pady=6)
        risk_cb = ttk.Combobox(frm, values=RISK_VALUES, state="readonly", style="Warm.TCombobox")
        risk_cb.set(_risk_to_display(cur_risk)); risk_cb.grid(row=1, column=1, sticky="w", pady=6)

        ttk.Label(frm, text="Description", style="FormKey.TLabel").grid(row=2, column=0, sticky="e", padx=(0, 10), pady=6)
        desc_e = tk.Entry(frm, bg=ENTRY_BG, fg=TEXT_FG, relief="flat")
        desc_e.insert(0, cur_desc or ""); desc_e.grid(row=2, column=1, sticky="ew", pady=6)

        ttk.Label(frm, text="Camera Mode", style="FormKey.TLabel").grid(row=3, column=0, sticky="e", padx=(0, 10), pady=6)
        mode_cb = ttk.Combobox(frm, values=MODE_VALUES, state="readonly", style="Warm.TCombobox")
        mode_cb.set(_mode_to_display(cur_mode)); mode_cb.grid(row=3, column=1, sticky="w", pady=6)

        btns = tk.Frame(frm, bg=CARD_BG); btns.grid(row=4, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Cancel", style="Danger.TButton", command=dlg.destroy).pack(side="right", padx=(0, 8))

        def save():
            def _work():
                update_zone(zone_id,
                            name=(name_e.get() or "").strip(),
                            description=(desc_e.get() or "").strip(),
                            risk_level=_risk_to_store(risk_cb.get()))
                cams = list_cameras_by_zone(zone_id)  # one-off query is fine here
                if cams:
                    update_camera(cams[0]["id"], mode=_mode_to_store(mode_cb.get()))
                return True

            def _done(result):
                if isinstance(result, Exception):
                    messagebox.showerror("Edit Zone", str(result), parent=dlg); return
                dlg.destroy(); self._refresh_all_async()
            run_async(_work, _done, dlg)

        ttk.Button(btns, text="Save", style="Primary.TButton", command=save).pack(side="right")

    def _delete_zone_cascade(self, item_id: str):
        vals = self.tree.item(item_id, "values")
        if not vals:
            return
        zone_id = vals[0]
        try:
            cameras = list_cameras_by_zone(zone_id)
        except Exception:
            cameras = []
        cam_names = ", ".join([(c.get("name") or c.get("id", "")) for c in cameras]) or "None"
        if not messagebox.askyesno(
            "Delete Zone",
            f"This will permanently delete the zone AND its camera(s).\n\n"
            f"Zone ID: {zone_id}\n"
            f"Cameras: {cam_names}\n\n"
            "Continue?"
        ):
            return

        def _work():
            for c in cameras:
                delete_camera(c["id"])
            delete_zone(zone_id, force=True)
            return True

        def _done(result):
            if isinstance(result, Exception):
                messagebox.showerror("Delete Zone", str(result)); return
            self._refresh_all_async()
        run_async(_work, _done, self)

    def _open_wizard(self):
        if not self.company_id:
            messagebox.showerror("New Zone", "No company id."); return

        # Keep a strong reference so GC can’t close it unexpectedly.
        if self._wizard and self._wizard.winfo_exists():
            try:
                self._wizard.lift(); self._wizard.focus_force()
            except Exception:
                pass
            return

        self._wizard = ZoneWizard(self, company_id=self.company_id, on_done=self._refresh_all_async)
        # Clear the reference when it really closes
        self._wizard.bind("<Destroy>", lambda _e: setattr(self, "_wizard", None))

    def _schedule_next_refresh(self):
        if self._refresh_job:
            try:
                self.after_cancel(self._refresh_job)
            except Exception:
                pass
        self._refresh_job = self.after(AUTO_REFRESH_MS, self._refresh_and_reschedule)

    def _refresh_and_reschedule(self):
        self._refresh_all_async()
        self._schedule_next_refresh()

    def destroy(self):
        try:
            if self._refresh_job:
                self.after_cancel(self._refresh_job)
        except Exception:
            pass
        super().destroy()
