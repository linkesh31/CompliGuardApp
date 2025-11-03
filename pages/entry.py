# pages/entry.py
from __future__ import annotations
import os, time, threading
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any, List, Optional

import cv2
import numpy as np
from PIL import Image, ImageTk

from services.ui_theme import apply_theme, card, FONTS, PALETTE
from services.session import require_user

# Optional profile (company_id fallback)
try:
    from services.account import get_profile  # returns dict
except Exception:
    def get_profile() -> Dict[str, Any]:
        return {}

# Primary services (zones/cameras)
try:
    from services.zones import list_zones, list_cameras_by_zone
except Exception:
    def list_zones(_cid: str) -> List[Dict[str, Any]]: return []
    def list_cameras_by_zone(_zid: str) -> List[Dict[str, Any]]: return []

# Firestore fallback
try:
    from services.firebase_client import get_db
except Exception:
    def get_db(): return None

# Two-model detector helper (primary + secondary GB)
from services.ppe_infer import PPEDetector, DetectorResult

# Make RTSP robust
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp|stimeout;10000000|max_delay;5000000"
)

# ───────────────────────── helpers ─────────────────────────
def _s(v: Any) -> str:
    return ("" if v is None else str(v)).strip()

def _extract_company_id(user: Dict[str, Any], prof: Dict[str, Any]) -> Optional[str]:
    for k in ("company_id", "companyId", "companyID", "company"):
        if k in user and _s(user[k]): return _s(user[k])
    for k in ("company_id", "companyId", "companyID", "company"):
        if k in prof and _s(prof[k]): return _s(prof[k])
    return None

def _zone_id(z: Dict[str, Any]) -> str:
    return _s(z.get("id") or z.get("zone_id") or z.get("doc_id"))

def _zone_display_name(z: Dict[str, Any]) -> str:
    for k in ("name", "display_name", "code", "id", "zone_id"):
        s = _s(z.get(k))
        if s: return s
    return "Zone"

def _fs_fetch_zones(company_id: str) -> List[Dict[str, Any]]:
    db = get_db()
    if not db: return []
    try:
        q = db.collection("zones").where("company_id", "==", company_id).get()
        return [{**(snap.to_dict() or {}), "id": snap.id} for snap in q]
    except Exception:
        return []

def _fs_fetch_cameras(zone_id: str) -> List[Dict[str, Any]]:
    db = get_db()
    if not db: return []
    try:
        q = db.collection("cameras").where("zone_id", "==", zone_id).get()
        return [{**(snap.to_dict() or {}), "id": snap.id} for snap in q]
    except Exception:
        return []

def _camera_source(cam: Dict[str, Any]) -> Optional[str]:
    if not cam or cam.get("active") is False:
        return None
    rtsp = _s(cam.get("rtsp_url"))
    if rtsp: return rtsp
    http = _s(cam.get("http_url"))
    if http: return http
    return None

def _is_entry_camera(cam: Dict[str, Any]) -> bool:
    mode = (_s(cam.get("camera_mode")) or _s(cam.get("mode")) or "").lower()
    return mode == "entry"

def _zone_is_entry(z: Dict[str, Any], cams: List[Dict[str, Any]]) -> bool:
    for c in cams:
        if _is_entry_camera(c) and _camera_source(c):
            return True
    name = _zone_display_name(z).lower()
    if "entry" in name:
        return any(_camera_source(c) for c in cams)
    return False

# ───────────────────────── modern modal (with icons) ─────────────────────────
SUCCESS_ICON_PATH = "data/ui/icons/success.png"
WARNING_ICON_PATH = "data/ui/icons/warning.png"

def _load_icon(path: str, size: int = 56) -> Optional[ImageTk.PhotoImage]:
    if not path or not os.path.exists(path):
        return None
    try:
        img = Image.open(path).convert("RGBA")
        img = img.resize((size, size), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None

def _show_modal(
    parent: tk.Widget,
    kind: str,                     # "success" | "warning"
    title: str,
    message: str,
    details: Optional[List[str]] = None,
    autoclose_ms: int = 5000,      # 5 seconds
) -> tk.Toplevel:
    # (kept as-is to preserve your popup behavior)
    bg = "#0f172a"       # slate-900
    text = "#e2e8f0"     # slate-200
    sub = "#cbd5e1"      # slate-300
    ok_col = "#16a34a"   # green-600
    warn_col = "#dc2626" # red-600
    accent = ok_col if kind == "success" else warn_col
    icon_path = SUCCESS_ICON_PATH if kind == "success" else WARNING_ICON_PATH

    top = tk.Toplevel(parent.winfo_toplevel())
    top.withdraw()
    top.configure(bg=bg)
    top.overrideredirect(True)

    parent.update_idletasks()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    w, h = 560, 300
    x = px + (pw - w) // 2
    y = py + (ph - h) // 2
    top.geometry(f"{w}x{h}+{max(0,x)}+{max(0,y)}")

    wrap = tk.Frame(top, bg=bg, bd=0, highlightthickness=0)
    wrap.pack(fill="both", expand=True, padx=22, pady=22)

    header = tk.Frame(wrap, bg=bg); header.pack(fill="x")
    icon_img = _load_icon(icon_path, size=56)
    if icon_img is not None:
        lbl_icon = tk.Label(header, image=icon_img, bg=bg); lbl_icon.image = icon_img
    else:
        badge = "✔" if kind == "success" else "⚠"
        lbl_icon = tk.Label(header, text=badge, fg=accent, bg=bg, font=("Segoe UI", 30, "bold"))
    lbl_icon.pack(side="left")

    tk.Label(header, text=title, fg=text, bg=bg, font=("Segoe UI", 22, "bold")).pack(side="left", padx=12)

    body = tk.Frame(wrap, bg=bg); body.pack(fill="both", expand=True, pady=(14, 8))
    tk.Label(body, text=message, fg=sub, bg=bg, font=("Segoe UI", 12)).pack(anchor="w")
    if details:
        box = tk.Frame(body, bg="#0b1220", bd=0); box.pack(fill="x", pady=(10, 0))
        for line in details:
            tk.Label(box, text=f"• {line}", fg=sub, bg="#0b1220", font=("Segoe UI", 11)).pack(anchor="w")

    footer = tk.Frame(wrap, bg=bg); footer.pack(fill="x", side="bottom", pady=(10, 0))
    btn = tk.Button(footer, text="OK", command=top.destroy, bg=accent, fg="white",
                    relief="flat", font=("Segoe UI", 11, "bold"), padx=18, pady=10,
                    activebackground=accent, cursor="hand2")
    btn.pack(side="right")

    top.update_idletasks()
    top.deiconify()
    try:
        top.attributes("-topmost", True)
        top.lift()
        top.focus_force()
        top.grab_set()
    except Exception:
        pass

    if autoclose_ms and autoclose_ms > 0:
        top.after(autoclose_ms, lambda: top.winfo_exists() and top.destroy())
    return top


# ───────────────────────── Entry Page (UI restyled only) ─────────────────────────
class EntryPage(tk.Frame):
    """
    10-second PPE check window:
      • Timer starts as soon as a person appears (P>0).
      • Success requires: helmet + vest + (≥1 glove) + (≥1 boot).
      • When all are present, start a 2s one-shot timer → success popup.
      • If the 10s deadline hits first → warning popup listing every missing item.
      • After any popup, require scene clear (P==0) before next window.
    """

    # Match AddAdmin page theme
    PAGE_BG = "#E6D8C3"
    TEXT_FG = "#000000"
    ENTRY_BG = "#F5EEDF"
    CARD_BG = "#EFE3D0"

    def __init__(self, parent, controller, *_, **__):
        super().__init__(parent, bg=self.PAGE_BG)
        self.controller = controller
        apply_theme(self)

        # Apply the same overrides & ttk styles used by Add Admin
        self._apply_page_theme_overrides()
        self._init_styles()

        # session
        self.company_id: Optional[str] = None
        self.zones: List[Dict[str, Any]] = []
        self.zone_by_name: Dict[str, Dict[str, Any]] = {}
        self.selected_zone = tk.StringVar(value="")

        # video state
        self._cap: Optional[cv2.VideoCapture] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_reader = threading.Event()
        self._last_frame: Optional[np.ndarray] = None
        self._online = False

        # detector
        self.detector: Optional[PPEDetector] = None

        # draw/state
        self._last_annotated: Optional[np.ndarray] = None
        self._last_result: Optional[DetectorResult] = None

        # 10s window state
        self._check_active = False
        self._check_deadline = 0.0
        self._check_duration = 10.0
        self._reset_required = False

        # success timer (no continuous check)
        self._success_delay = 2.0        # seconds
        self._success_timer_id: Optional[str | int] = None

        # keep modal ref
        self._last_modal: Optional[tk.Toplevel] = None

        self._build()
        self.after(50, self._init_data)

    # ───────── UI styling (match AddAdmin) ─────────
    def _apply_page_theme_overrides(self):
        self.option_add("*Background", self.PAGE_BG)
        self.option_add("*Foreground", self.TEXT_FG)
        self.option_add("*highlightBackground", self.PAGE_BG)
        self.option_add("*insertBackground", self.TEXT_FG)
        self.option_add("*troughColor", self.PAGE_BG)
        self.option_add("*selectBackground", "#2563eb")
        self.option_add("*selectForeground", "#FFFFFF")

    def _init_styles(self):
        # Use a theme that respects color maps for widgets
        try:
            ttk.Style().theme_use("clam")
        except Exception:
            pass

        self.style = ttk.Style(self)
        accent = "#0077b6"
        hover = "#00b4d8"

        # Modern button — blue like Add Admin
        self.style.configure(
            "Modern.TButton",
            font=("Segoe UI Semibold", 10),
            background=accent,
            foreground="white",
            padding=(14, 6),
            borderwidth=0,
            relief="flat"
        )
        self.style.map(
            "Modern.TButton",
            background=[("active", hover), ("!disabled", accent)],
            foreground=[("!disabled", "white")],
            relief=[("pressed", "sunken")]
        )

        # Slim muted label
        self.style.configure(
            "Muted.TLabel",
            background=self.CARD_BG,
            foreground="#333333",
            font=("Segoe UI", 10)
        )

        # Combobox visuals — keep WHITE always (no gray selection)
        self.style.configure(
            "Modern.TCombobox",
            fieldbackground="#FFFFFF",
            background="#FFFFFF",
            foreground="#000000",
            borderwidth=0,
            padding=4
        )
        self.style.map(
            "Modern.TCombobox",
            fieldbackground=[("readonly", "#FFFFFF"), ("focus", "#FFFFFF"), ("!disabled", "#FFFFFF")],
            background=[("readonly", "#FFFFFF"), ("focus", "#FFFFFF"), ("!disabled", "#FFFFFF")],
            foreground=[("readonly", "#000000"), ("focus", "#000000"), ("!disabled", "#000000")],
            selectbackground=[("readonly", "#FFFFFF"), ("focus", "#FFFFFF"), ("!disabled", "#FFFFFF")],
            selectforeground=[("readonly", "#000000"), ("focus", "#000000"), ("!disabled", "#000000")],
        )

    # UI (layout only; logic unchanged)
    def _build(self):
        # Header
        header = tk.Frame(self, bg=self.PAGE_BG)
        header.pack(fill="x", padx=16, pady=(12, 8))
        tk.Label(
            header, text="Entry Verification",
            font=("Segoe UI Semibold", 18),
            bg=self.PAGE_BG, fg="#222222"
        ).pack(anchor="w")
        # (Removed the descriptive sentence under the title)

        # Controls card
        ctrl_card, ctrl_inner = card(self, fg=self.CARD_BG, border_color="#DCCEB5", border_width=2, pad=(18, 12))
        ctrl_card.pack(fill="x", padx=16, pady=(6, 12))
        ctrl_card.configure(fg_color=self.CARD_BG)

        row = tk.Frame(ctrl_inner, bg=self.CARD_BG)
        row.pack(fill="x")

        ttk.Label(row, text="Zone", style="Muted.TLabel").pack(side="left", padx=(0, 10))
        self.zone_menu = ttk.Combobox(
            row, textvariable=self.selected_zone, values=[], state="readonly", width=30, style="Modern.TCombobox"
        )
        self.zone_menu.pack(side="left")
        self.zone_menu.bind("<<ComboboxSelected>>", self._on_zone_changed)

        tk.Frame(row, bg=self.CARD_BG).pack(side="left", padx=8)

        ttk.Button(
            row, text="Refresh", style="Modern.TButton",
            command=lambda: self._open_zone_stream(self.selected_zone.get())
        ).pack(side="left")

        # Main card
        main_card, main_inner = card(self, fg=self.CARD_BG, border_color="#DCCEB5", border_width=2)
        main_card.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        main_card.configure(fg_color=self.CARD_BG)

        main_inner.grid_columnconfigure(0, weight=3)
        main_inner.grid_columnconfigure(1, weight=1)
        main_inner.grid_rowconfigure(0, weight=1)

        # Video panel
        video_wrap = tk.Frame(main_inner, bg=self.CARD_BG)
        video_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        self.video_label = tk.Label(video_wrap, text="", bg="#000000", fg="#FFFFFF")
        self.video_label.pack(fill="both", expand=True, padx=6, pady=6)

        self.status = tk.Label(
            video_wrap, text="Initializing…", anchor="w",
            bg=self.CARD_BG, fg="#333333", font=("Segoe UI", 10)
        )
        self.status.pack(fill="x", padx=6, pady=(2, 6))

        # PPE side panel
        ppe_wrap = tk.Frame(main_inner, bg=self.CARD_BG)
        ppe_wrap.grid(row=0, column=1, sticky="nsw")

        tk.Label(
            ppe_wrap, text="PPE Status",
            font=("Segoe UI Semibold", 14), bg=self.CARD_BG, fg="#222222"
        ).pack(anchor="w", pady=(4, 8))

        self._ppe_rows: Dict[str, tk.Label] = {}
        for gear in ("Helmet", "Vest", "Gloves", "Boots"):
            rowg = tk.Frame(ppe_wrap, bg=self.CARD_BG)
            rowg.pack(anchor="w", pady=6, fill="x")
            tk.Label(
                rowg, text=gear,
                bg=self.CARD_BG, fg="#333333", font=("Segoe UI", 10, "bold")
            ).pack(side="left")
            pill = tk.Label(
                rowg, text=" ✖", fg="#dc2626", bg="#ffecec",
                font=("Segoe UI", 10, "bold"), padx=8, pady=2
            )
            pill.pack(side="right")
            self._ppe_rows[gear] = pill

        # (Counts label and "Green/Red" sentence removed)

        # Start UI updater
        self.after(50, self._ui_update_loop)

    # data init (unchanged)
    def _init_data(self):
        try: user = require_user(self.controller)
        except Exception: user = {}
        try: prof = get_profile() or {}
        except Exception: prof = {}
        self.company_id = _extract_company_id(user, prof)
        if not self.company_id:
            self._set_offline("No company assigned.")
            self.zone_menu["values"] = ["(No Company)"]; self.selected_zone.set("(No Company)")
            return

        # zones
        try: zones = list_zones(self.company_id)
        except Exception: zones = _fs_fetch_zones(self.company_id)
        zones = [z for z in zones if _s(z.get("company_id")) == self.company_id]

        entry_zones: List[Dict[str, Any]] = []
        for z in zones:
            zid = _zone_id(z)
            try: cams = list_cameras_by_zone(zid)
            except Exception: cams = _fs_fetch_cameras(zid)
            if _zone_is_entry(z, cams):
                entry_zones.append(z)

        if not entry_zones:
            self._set_offline("No Entry cameras found.")
            self.zone_menu["values"] = ["(No Entry Zones)"]; self.selected_zone.set("(No Entry Zones)")
            return

        self.zones = entry_zones
        self.zone_by_name = { _zone_display_name(z): z for z in entry_zones }
        names = list(self.zone_by_name.keys())
        self.zone_menu["values"] = names
        self.selected_zone.set(names[0])
        self.zone_menu.configure(state="disabled" if len(names) == 1 else "readonly")

        # Load detector
        try:
            # primary PPE
            p1 = os.path.join("data", "model", "best.pt")
            p2 = os.path.join("data", "models", "best.pt")
            ppe_path = p1 if os.path.exists(p1) else (p2 if os.path.exists(p2) else None)
            if not ppe_path:
                raise FileNotFoundError("Put best.pt in data/model/ or data/models/")

            # person model
            y1 = os.path.join("data", "model", "yolov8n.pt")
            y2 = os.path.join("data", "models", "yolov8n.pt")
            person_model = y1 if os.path.exists(y1) else (y2 if os.path.exists(y2) else "yolov8n.pt")

            # secondary gloves/boots (try specific file first, then scan)
            gb_candidates = [
                os.path.join("data", "models", "gloves_shoes_yolo9e.pt"),
                os.path.join("data", "model",  "gloves_shoes_yolo9e.pt"),
                os.path.join("data", "models", "gloves.pt"),
                os.path.join("data", "models", "gloves_boots.pt"),
            ]
            gb_model = next((p for p in gb_candidates if os.path.exists(p)), None)
            if gb_model is None:
                for root in ["data/models", "data/model"]:
                    if os.path.isdir(root):
                        for f in os.listdir(root):
                            fl = f.lower()
                            if fl.endswith(".pt") and any(k in fl for k in ["glove", "boot", "shoe", "yolo9"]):
                                gb_model = os.path.join(root, f); break
                    if gb_model: break

            self.detector = PPEDetector(
                ppe_model=ppe_path,
                person_model=person_model,
                glove_boot_model=gb_model,          # ← secondary (can be None)
                device="cuda:0", imgsz=832,
                conf=0.30, gb_conf=0.30, iou=0.70,
                part_conf=0.55,
                relax=True, fix_label_shift=True, show_parts=True,
            )
            sec_name = os.path.basename(gb_model) if gb_model else "—"
            self.status.config(
                text=f"Models ready — PPE:{os.path.basename(ppe_path)} / GB:{sec_name} / Person:{os.path.basename(str(person_model))}"
            )
        except Exception as e:
            self.status.config(text=f"Model init failed: {e}")
            self.detector = None

        self._open_zone_stream(names[0])

    # camera handling (unchanged)
    def _open_zone_stream(self, zone_name: str):
        zone = self.zone_by_name.get(zone_name)
        if not zone:
            self._set_offline("No zone."); return
        zid = _zone_id(zone)
        try: cams = list_cameras_by_zone(zid)
        except Exception: cams = _fs_fetch_cameras(zid)

        src = None
        for c in cams:
            if _is_entry_camera(c):
                src = _camera_source(c)
                if src: break
        if not src and "entry" in _zone_display_name(zone).lower():
            for c in cams:
                src = _camera_source(c)
                if src: break
        if not src:
            self._set_offline("No Entry camera in zone."); return

        self._stop_reader.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
        self._release_cap()

        cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
        if not cap or not cap.isOpened():
            self._set_offline("Camera Offline."); return
        try: cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception: pass

        self._cap = cap
        self._online = True
        self.status.config(text=f"Streaming (Entry) — {zone_name}")
        self._stop_reader.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def _reader_loop(self):
        fails = 0
        while not self._stop_reader.is_set():
            cap = self._cap
            if cap is None:
                self._set_offline("Camera Offline.")
                time.sleep(2)
                self._open_zone_stream(self.selected_zone.get())
                return
            ok, frame = cap.read()
            if not ok or frame is None:
                fails += 1; self._online = False
                if fails >= 30:
                    self._set_offline("Reconnecting…")
                    time.sleep(2)
                    self._open_zone_stream(self.selected_zone.get())
                    return
                time.sleep(0.03); continue
            fails = 0; self._online = True
            self._last_frame = frame
        self._release_cap()

    def _release_cap(self):
        try:
            if self._cap is not None: self._cap.release()
        except Exception: pass
        self._cap = None

    # ——— draw/update loop ———
    def _ui_update_loop(self):
        frame = self._last_frame
        if frame is not None and self._online:
            disp = frame

            if self.detector is not None:
                try:
                    annotated, result = self.detector.infer(disp)
                    self._last_annotated = annotated
                    self._last_result = result

                    # Right-side panel
                    self._update_ppe_panel_from_result(result)

                    # ── 10-second logic with simple 2s success delay ──
                    now = time.time()
                    persons = self._parse_person_count(getattr(result, "counts_text", ""))
                    scene_clear = (persons == 0)

                    if self._reset_required:
                        if scene_clear:
                            self._reset_required = False
                            self.status.config(text="Scene clear — ready for next check.")
                    else:
                        if not self._check_active:
                            if persons > 0:
                                self._check_active = True
                                self._check_deadline = now + self._check_duration
                                self._cancel_success_timer()
                                self.status.config(text=f"Check started — {int(self._check_duration)}s window for full PPE.")
                        else:
                            helmet = bool(getattr(result, "any_helmet", False))
                            vest   = bool(getattr(result, "any_vest", False))
                            gloves = bool(getattr(result, "any_gloves", False))
                            boots  = bool(getattr(result, "any_boots", False))

                            compliant = helmet and vest and gloves and boots

                            remaining = max(0, int(round(self._check_deadline - now)))
                            # Keep ENTRY TIMER overlay (requested)
                            cv2.putText(self._last_annotated, f"ENTRY TIMER: {remaining}s",
                                        (12, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                                        (0, 255, 0) if compliant else (0, 0, 255), 2, cv2.LINE_AA)

                            if compliant and self._success_timer_id is None:
                                delay_ms = int(self._success_delay * 1000)
                                self._success_timer_id = self.after(delay_ms, self._confirm_success)

                            if now >= self._check_deadline and self._check_active:
                                if self._success_timer_id is not None:
                                    self._cancel_success_timer()
                                missing = []
                                if not helmet: missing.append("Helmet")
                                if not vest:   missing.append("Vest")
                                if not gloves: missing.append("Gloves")
                                if not boots:  missing.append("Boots")
                                self.after(0, lambda: self._show_warning_popup(missing=missing or ["Helmet","Vest","Gloves","Boots"]))
                                self._check_active = False
                                self._reset_required = True
                                self.status.config(text="⚠ Missing PPE — access denied.")

                    # REMOVE counts_text overlay on the video (as requested)
                    # (Previously drew counts_text at (12,28); now removed.)

                except Exception:
                    self._update_ppe_panel(False, False, False, False)

            to_show = self._last_annotated if self._last_annotated is not None else disp

            # draw to UI (preserve aspect)
            h = max(1, self.video_label.winfo_height())
            w = max(1, self.video_label.winfo_width())
            fh, fw = to_show.shape[:2]
            scale = min(w / max(1, fw), h / max(1, fh))
            new_w, new_h = max(1, int(fw * scale)), max(1, int(fh * scale))
            resized = cv2.resize(to_show, (new_w, new_h), interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            imgtk = ImageTk.PhotoImage(image=Image.fromarray(rgb))
            self.video_label.imgtk = imgtk
            self.video_label.config(image=imgtk, text="")
        else:
            if not self._online:
                self._draw_offline_canvas("Camera Offline")

        self.after(66, self._ui_update_loop)  # ~15 FPS

    # success confirm handler (unchanged)
    def _confirm_success(self):
        if not self._check_active:
            self._success_timer_id = None
            return
        self._show_success_popup()
        self._check_active = False
        self._reset_required = True
        self._success_timer_id = None
        self.status.config(text="✅ PPE Verified — helmet, vest, gloves, boots detected.")

    def _cancel_success_timer(self):
        if self._success_timer_id is not None:
            try:
                self.after_cancel(self._success_timer_id)
            except Exception:
                pass
            self._success_timer_id = None

    def _parse_person_count(self, counts_text: str) -> int:
        if not counts_text:
            return 0
        try:
            seg = counts_text.split("|", 1)[0]
            for token in seg.split():
                if token.startswith("P:"):
                    return int(token.split(":", 1)[1])
        except Exception:
            pass
        return 0

    def _draw_offline_canvas(self, text: str):
        w = max(320, self.video_label.winfo_width())
        h = max(180, self.video_label.winfo_height())
        canvas = np.zeros((h, w, 3), dtype=np.uint8)
        cv2.putText(canvas, text, (20, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        imgtk = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)))
        self.video_label.imgtk = imgtk
        self.video_label.config(image=imgtk)

    def _on_zone_changed(self, _e=None):
        name = self.selected_zone.get()
        if not name or name.startswith("("):
            self._set_offline("No zones.")
            return
        self._open_zone_stream(name)

    def _set_offline(self, msg: str):
        self._online = False
        self.status.config(text=msg)
        self._last_frame = None
        self._last_annotated = None
        self._last_result = None
        self._update_ppe_panel(False, False, False, False)
        self._check_active = False
        self._reset_required = False
        self._cancel_success_timer()

    # ───────────────────── popup helpers (unchanged) ─────────────────────
    def _show_success_popup(self):
        self._last_modal = _show_modal(
            self, "success",
            title="Access Granted",
            message="PPE compliant. You may proceed.",
            details=None,
            autoclose_ms=5000
        )

    def _show_warning_popup(self, missing: List[str]):
        details = [f"{x} missing" for x in (missing or [])] if missing else ["Helmet, Vest, Gloves, Boots missing"]
        self._last_modal = _show_modal(
            self, "warning",
            title="Access Denied",
            message="Missing required PPE. Please equip the items listed below.",
            details=details,
            autoclose_ms=5000
        )

    # ───────────────────── panel helpers (unchanged) ─────────────────────
    def _update_ppe_panel_from_result(self, res: DetectorResult):
        h = bool(getattr(res, "any_helmet", False))
        v = bool(getattr(res, "any_vest", False))
        g = bool(getattr(res, "any_gloves", False))
        b = bool(getattr(res, "any_boots", False))
        self._update_ppe_panel(h, v, g, b)
        # counts overlay/label removed

    def _update_ppe_panel(self, helmet: bool, vest: bool, gloves: bool, boots: bool):
        def set_row(gear: str, ok: bool):
            if ok:
                self._ppe_rows[gear].config(text=" ✓", fg="#16a34a", bg="#eaffef")
            else:
                self._ppe_rows[gear].config(text=" ✖", fg="#dc2626", bg="#ffecec")
        set_row("Helmet", helmet)
        set_row("Vest", vest)
        set_row("Gloves", gloves)
        set_row("Boots", boots)

    def destroy(self):
        try:
            self._stop_reader.set()
            if self._reader_thread and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=1.0)
            self._release_cap()
            self._cancel_success_timer()
        except Exception:
            pass
        super().destroy()
