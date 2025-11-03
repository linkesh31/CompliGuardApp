import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional, Any
import threading, time, os, base64, sys
import cv2
import numpy as np
from PIL import Image, ImageTk

from services.ui_theme import apply_theme, card, FONTS, PALETTE
from services.session import require_user

# Optional profile
try:
    from services.account import get_profile  # returns dict
except Exception:
    def get_profile() -> Dict[str, Any]:
        return {}

# Zones & Cameras
try:
    from services.zones import list_zones, list_cameras_by_zone
except Exception:
    def list_zones(_company_id: str) -> List[Dict[str, Any]]: return []
    def list_cameras_by_zone(_zone_id: str) -> List[Dict[str, Any]]: return []

# Firestore client
try:
    from services.firebase_client import get_db
except Exception:
    def get_db(): return None

# Detector: same pipeline as Entry (YOLOv8n person + custom PPE model with smoothing)
from services.ppe_infer import PPEDetector

# ───────────────────────── RTSP capture tuning (lower latency) ─────────────────────────
# You previously forced TCP with big timeouts; for live preview this adds delay.
# This set keeps TCP, but adds nobuffer/low_delay and smaller probe/analyze windows.
# (FFmpeg ignores unknown keys, so it’s safe.)
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp|"          # keep TCP for reliability on Wi-Fi
    "fflags;nobuffer|"             # disable internal buffering
    "flags;low_delay|"             # reduce decoder latency
    "reorder_queue_size;0|"        # don't queue frames
    "probesize;3200|"              # small probe
    "analyzeduration;0|"           # no long analysis
    "stimeout;7000000|"            # 7s open timeout
    "max_delay;2000000"            # <= 2s muxer delay
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

def _zone_display_name(z: Dict[str, Any]) -> str:
    for k in ("name", "display_name", "code", "id", "zone_id"):
        s = _s(z.get(k))
        if s: return s
    return "Unknown Zone"

def _zone_id(z: Dict[str, Any]) -> str:
    return _s(z.get("id") or z.get("zone_id") or z.get("doc_id"))

def _zone_level(z: Dict[str, Any]) -> str:
    """Normalize zone risk level to 'low'/'medium'/'high' ('' if unknown)."""
    t = _s(z.get("risk_level") or z.get("level") or z.get("severity")).lower()
    if t in ("1", "low"): return "low"
    if t in ("2", "medium", "med"): return "medium"
    if t in ("3", "high", "critical", "severe"): return "high"
    return ""

def _pick_monitor_camera(cam: Dict[str, Any]) -> Optional[str]:
    if not cam or not cam.get("active", True): return None
    mode = (_s(cam.get("camera_mode")) or _s(cam.get("mode"))).lower()
    if mode != "monitor": return None
    rtsp = _s(cam.get("rtsp_url"))
    if rtsp: return rtsp
    http = _s(cam.get("http_url"))
    if http: return http
    return None

# Firestore fallbacks
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
        q = (db.collection("cameras")
             .where("zone_id", "==", zone_id)
             .where("active", "==", True).get())
        return [{**(snap.to_dict() or {}), "id": snap.id} for snap in q]
    except Exception:
        return []

def _jpeg_b64(img_bgr: np.ndarray, max_side: int = 560, quality: int = 82) -> str:
    h, w = img_bgr.shape[:2]
    scale = 1.0
    if max(h, w) > max_side:
        scale = max_side / float(max(h, w))
    if scale != 1.0:
        img_bgr = cv2.resize(img_bgr, (int(w*scale), int(h*scale)))
    ok, buf = cv2.imencode(".jpg", img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        return ""
    return base64.b64encode(buf.tobytes()).decode("ascii")

# ───────────────────────── Live Monitor ─────────────────────────
class LiveMonitorPage(tk.Frame):
    """
    Helmet, Vest, Gloves & Boots monitoring while workers are moving.

    Features:
      • Violation hold-time (self.violation_hold_s) before logging.
      • Async snapshot + Firestore write (no UI freeze).
      • Zone risk levels: high triggers looping alarm + blocking popup (until OK).
      • Any glove OR any boot counts as OK (same semantics as Entry).
      • If no person is in frame, the current hold-timer is cancelled.
      • After high-risk popup “OK”, detection is re-armed immediately (fresh 10s window).
    """

    # AddAdmin visual language (beige/tan theme)
    PAGE_BG = "#E6D8C3"
    TEXT_FG = "#000000"
    ENTRY_BG = "#F5EEDF"
    CARD_BG = "#EFE3D0"
    BORDER_COLOR = "#DCCEB5"
    ACCENT = "#0077b6"
    ACCENT_HOVER = "#00b4d8"
    BADGE_BG = "#5D866C"
    BADGE_FG = "#FFFFFF"

    def __init__(self, parent, controller, preloaded_detector: Optional[Any] = None, *_, **__):
        super().__init__(parent, bg=self.PAGE_BG)
        self.controller = controller
        apply_theme(self)

        # IDs / selection
        self.company_id: Optional[str] = None
        self.zones: List[Dict[str, Any]] = []
        self.zone_by_name: Dict[str, Any] = {}
        self.selected_zone = tk.StringVar(value="")
        self._destroyed = False  # safety flag for async callbacks

        # Streaming
        self._cap = None
        self._reader_thread = None
        self._last_frame = None
        self._stop_reader = threading.Event()
        self._online = False

        # Current zone/camera
        self._current_zone: Optional[Dict[str, Any]] = None
        self._current_camera: Optional[Dict[str, Any]] = None
        self._camera_src: Optional[str] = None

        # Violation logic
        self.violation_hold_s: float = 10.0
        self._viol_start_ts: float = 0.0
        self._viol_kind: Optional[str] = None
        self._viol_raised: bool = False
        self._violation_cooldown_s = 5.0
        self._last_violation_ts: float = 0.0

        # High-risk alert state
        self._alert_top: Optional[tk.Toplevel] = None
        self._alarm_thread: Optional[threading.Thread] = None
        self._alarm_stop = threading.Event()

        # Detector (shared with Entry)
        self.detector: Optional[PPEDetector] = preloaded_detector if preloaded_detector is not None else None

        # UI bits
        self._tprev = None
        self._fps_lbl = None
        self._status_chip = None
        self._zone_badge = None  # the colored pill label

        self._apply_page_theme_overrides()
        self._init_styles()

        self._build(self)
        self.after(60, self._init_data)

    # Theme overrides
    def _apply_page_theme_overrides(self):
        try: self.configure(bg=self.PAGE_BG)
        except Exception: pass
        self.option_add("*Background", self.PAGE_BG)
        self.option_add("*Foreground", self.TEXT_FG)
        self.option_add("*highlightBackground", self.PAGE_BG)
        self.option_add("*insertBackground", self.TEXT_FG)
        self.option_add("*troughColor", self.PAGE_BG)
        self.option_add("*selectBackground", "#2563eb")
        self.option_add("*selectForeground", "#FFFFFF")

    def _init_styles(self):
        style = ttk.Style(self)

        style.configure(
            "Modern.TButton",
            font=("Segoe UI Semibold", 10),
            background=self.ACCENT,
            foreground="white",
            padding=(14, 6),
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Modern.TButton",
            background=[("active", self.ACCENT_HOVER)],
            relief=[("pressed", "sunken")],
        )

        # Combobox on card background
        style.configure(
            "Admin.TCombobox",
            fieldbackground=self.CARD_BG,
            background=self.CARD_BG,
            foreground=self.TEXT_FG,
            padding=4,
        )
        style.map(
            "Admin.TCombobox",
            fieldbackground=[("readonly", self.ENTRY_BG)],
            foreground=[("readonly", self.TEXT_FG)],
        )

    # Small colored pill (badge) for status/selection
    def _pill(self, parent, text: str, fg=None, bg=None):
        fg = fg or self.BADGE_FG
        bg = bg or self.BADGE_BG
        wrap = tk.Frame(parent, bg=bg, highlightthickness=0)
        lbl = tk.Label(wrap, text=text, bg=bg, fg=fg, font=("Segoe UI", 9, "bold"))
        lbl.pack(padx=10, pady=4)
        wrap._lbl = lbl  # store for updates
        return wrap

    def _build(self, root):
        # Page title
        tk.Label(root, text="Live Monitor",
                 font=FONTS.get("h2", ("Segoe UI Semibold", 18)),
                 bg=self.PAGE_BG, fg="#222222").pack(anchor="w", padx=16, pady=(10, 2))

        # Main card
        outer, inner = card(root, fg=self.CARD_BG, border_color=self.BORDER_COLOR, border_width=2, pad=(16, 16))
        outer.pack(fill="both", expand=True, padx=16, pady=(6, 12))
        outer.configure(fg_color=self.CARD_BG)
        inner.grid_columnconfigure(0, weight=1)
        inner.grid_columnconfigure(1, weight=2)
        inner.grid_rowconfigure(1, weight=1)

        # Controls row
        controls = tk.Frame(inner, bg=self.CARD_BG)
        controls.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        controls.grid_columnconfigure(0, weight=1)

        left_controls = tk.Frame(controls, bg=self.CARD_BG); left_controls.pack(side="left")
        tk.Label(left_controls, text="Zone", font=("Segoe UI", 10, "bold"),
                 bg=self.CARD_BG, fg="#333333").pack(side="left", padx=(0, 8))

        # Combobox bound to selected_zone
        self.zone_menu = ttk.Combobox(
            left_controls,
            textvariable=self.selected_zone,
            values=[],
            state="readonly",
            style="Admin.TCombobox",
            width=28,
            takefocus=True,
        )
        self.zone_menu.pack(side="left", padx=(0, 8))
        self.zone_menu.bind("<<ComboboxSelected>>", self._on_zone_changed)
        # Prevent the grey highlight whenever the box gains focus
        self.zone_menu.bind("<FocusIn>", lambda e: self._defocus_zone_menu())

        # Zone badge (selected zone with colored background)
        self._zone_badge = self._pill(left_controls, "", fg=self.BADGE_FG, bg=self.BADGE_BG)
        self._zone_badge.pack(side="left")

        right_controls = tk.Frame(controls, bg=self.CARD_BG); right_controls.pack(side="right")
        self._status_chip = self._pill(right_controls, "Initializing…", fg="#6b7280", bg="#f3f4f6")
        self._status_chip.pack(side="left", padx=(0, 8))
        self._fps_lbl = tk.Label(right_controls, text="FPS —", bg=self.CARD_BG,
                                 fg="#555555", font=("Segoe UI", 9))
        self._fps_lbl.pack(side="left")

        # Left column (reserved area)
        left = tk.Frame(inner, bg=self.CARD_BG)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        tk.Label(left, text="Stream", font=FONTS.get("h3", ("Segoe UI Semibold", 14)),
                 bg=self.CARD_BG, fg="#222222").pack(anchor="w", pady=(4, 8))

        # Right column: video
        right = tk.Frame(inner, bg=self.CARD_BG)
        right.grid(row=1, column=1, sticky="nsew")
        self.video_label = tk.Label(right, text="", bg="#000000", fg="#ffffff")
        self.video_label.pack(fill="both", expand=True, padx=4, pady=4)

        self.status = tk.Label(right, text="Initializing…", anchor="w",
                               bg=self.CARD_BG, fg="#333333", font=("Segoe UI", 10))
        self.status.pack(fill="x", padx=6, pady=(0, 6))

        self.after(50, self._ui_update_loop)

    # Keep the combobox looking like image #3 (no selected text)
    def _defocus_zone_menu(self):
        try:
            self.zone_menu.selection_clear()
            # Move the text cursor to the end, then shift focus to video area.
            self.zone_menu.icursor(tk.END)
        except Exception:
            pass
        try:
            # put focus on a neutral widget so the combobox loses the grey selection
            if self.video_label and self.video_label.winfo_exists():
                self.video_label.focus_set()
            else:
                self.focus_set()
        except Exception:
            pass

    def _safe_widget(self, w) -> bool:
        return bool(w and hasattr(w, "winfo_exists") and w.winfo_exists() and not self._destroyed)

    def _set_zone_badge(self, text: str):
        if not self._safe_widget(self._zone_badge): return
        try:
            self._zone_badge._lbl.configure(text=text or "—")
        except Exception:
            pass

    def _set_chip(self, text: str, ok: Optional[bool] = None):
        if not self._safe_widget(self._status_chip): return
        try:
            for w in self._status_chip.winfo_children(): w.destroy()
        except Exception:
            return
        if ok is None:
            bg, fg = "#f3f4f6", "#6b7280"
        elif ok:
            bg, fg = "#e8f5e9", "#1b5e20"
        else:
            bg, fg = "#fee2e2", "#991b1b"
        try:
            self._status_chip.configure(bg=bg)
            tk.Label(self._status_chip, text=text, bg=bg, fg=fg,
                     font=("Segoe UI", 9, "bold")).pack(padx=10, pady=4)
        except Exception:
            pass

    # Data init
    def _init_data(self):
        if self._destroyed: return
        try: user = require_user(self.controller)
        except Exception: user = {}
        try: prof = get_profile() or {}
        except Exception: prof = {}
        self.user_email = _s(user.get("email") or prof.get("email") or "")
        self.company_id = _extract_company_id(user, prof)
        if not self.company_id:
            self.zone_menu["values"] = ["(No Company)"]; self.selected_zone.set("(No Company)")
            self._set_zone_badge("(No Company)")
            self._set_offline("No company."); 
            self.after(10, self._defocus_zone_menu)
            return

        try: zones = list_zones(self.company_id)
        except Exception: zones = _fs_fetch_zones(self.company_id)
        zones = [z for z in zones if _s(z.get("company_id")) == self.company_id]

        monitor_zones = []
        for z in zones:
            zid = _zone_id(z)
            try: cams = list_cameras_by_zone(zid)
            except Exception: cams = _fs_fetch_cameras(zid)
            if any(_pick_monitor_camera(c) for c in cams):
                monitor_zones.append(z)

        if not monitor_zones:
            self.zone_menu["values"] = ["(No Zones)"]; self.selected_zone.set("(No Zones)")
            self._set_zone_badge("(No Zones)")
            self._set_offline("No monitor cameras.")
            self.after(10, self._defocus_zone_menu)
            return

        self.zones = monitor_zones
        self.zone_by_name = { _zone_display_name(z): z for z in monitor_zones }
        names = list(self.zone_by_name.keys())
        self.zone_menu["values"] = names
        self.selected_zone.set(names[0])          # shows inside combobox
        self._set_zone_badge(names[0])            # and as a colored pill

        # Make sure it looks like image #3 on load
        self.after(10, self._defocus_zone_menu)

        self._load_detector()
        self._open_zone_stream(names[0])

    def _resolve_zone_camera(self, zone_doc):
        zid = _zone_id(zone_doc)
        try: cams = list_cameras_by_zone(zid)
        except Exception: cams = _fs_fetch_cameras(zid)
        for cam in cams:
            src = _pick_monitor_camera(cam)
            if src:
                return src, cam
        return None, None

    def _open_zone_stream(self, zone_name):
        if self._destroyed: return
        zone = self.zone_by_name.get(zone_name)
        if not zone:
            self._set_offline("No zone."); return
        src, cam = self._resolve_zone_camera(zone)
        if not src:
            self._set_offline("No monitor camera."); return

        self._current_zone = zone
        self._current_camera = cam
        self._camera_src = src

        # reset violation episode state when zone changes
        self._reset_violation_episode(reset_cooldown=True)

        self._stop_reader.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
        self._release_cap()
        cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
        if not cap or not cap.isOpened():
            self._set_offline("Camera Offline."); return
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)     # keep queue small
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)     # make sure we start 'now'
        except Exception:
            pass
        self._cap, self._online = cap, True
        if self._safe_widget(self.status):
            self.status.config(text=f"Streaming — {zone_name} ({_zone_level(zone) or 'n/a'} risk)")
        self._set_chip("Streaming", ok=True)
        self._stop_reader.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def _reader_loop(self):
        while not self._stop_reader.is_set() and not self._destroyed:
            cap = self._cap
            if cap is None:
                self._set_offline("Camera Offline."); return
            ok, frame = cap.read()
            if not ok:
                self._online = False
                time.sleep(0.01)  # smaller sleep to recover faster
                continue
            self._online = True
            self._last_frame = frame
        self._release_cap()

    def _release_cap(self):
        try:
            if self._cap is not None: self._cap.release()
        except Exception:
            pass
        self._cap = None

    # Async logging (no UI freeze)
    def _log_violation_async(self, full_bgr: np.ndarray, risk: str, zone_level: str):
        now = time.time()
        if (now - self._last_violation_ts) < self._violation_cooldown_s:
            return
        self._last_violation_ts = now

        zone = self._current_zone or {}
        cam = self._current_camera or {}
        company_id = self.company_id or ""
        user_email = self.user_email

        zone_id = _s(zone.get("id") or zone.get("zone_id") or zone.get("doc_id"))
        zone_name = _s(zone.get("name") or zone.get("display_name") or zone.get("code") or zone_id)
        camera_id = _s(cam.get("id") or cam.get("camera_id") or cam.get("doc_id"))
        camera_name = _s(cam.get("name") or cam.get("display_name") or cam.get("code") or camera_id)
        source = self._camera_src or ""

        def _worker():
            try:
                db = get_db()
                if not db:
                    return
                snap_b64 = _jpeg_b64(full_bgr, max_side=560)
                doc = {
                    "company_id": company_id,
                    "zone_id": zone_id,
                    "zone_name": zone_name,
                    "camera_id": camera_id,
                    "camera_name": camera_name,
                    "source": source,
                    "ts": int(time.time() * 1000),
                    "type": "ppe_violation",
                    "risk": risk,
                    "risk_level": {"low": "1", "medium": "2", "high": "3"}.get(zone_level, ""),
                    "user_email": user_email,
                    "offender_name": "",
                    "offender_id": "",
                    "has_snapshot": bool(snap_b64),
                    "snapshot_b64": snap_b64,
                    "note": f"Live monitor — {zone_level or 'unknown'} risk zone",
                }
                db.collection("violations").add(doc)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    # Alarm control (loop until OK)
    def _start_alarm_loop(self):
        if self._alarm_thread and self._alarm_thread.is_alive():
            return
        self._alarm_stop.clear()

        def _beep_loop():
            use_winsound = False
            try:
                if sys.platform.startswith("win"):
                    import winsound  # type: ignore
                    use_winsound = True
            except Exception:
                use_winsound = False

            while not self._alarm_stop.is_set():
                if use_winsound:
                    try:
                        import winsound  # type: ignore
                        winsound.Beep(880, 220); winsound.Beep(660, 180)
                    except Exception:
                        pass
                else:
                    try:
                        if self._safe_widget(self): self.after(0, self.bell)
                    except Exception:
                        pass
                    time.sleep(0.25)
                    try:
                        if self._safe_widget(self): self.after(0, self.bell)
                    except Exception:
                        pass
                time.sleep(0.35)

        self._alarm_thread = threading.Thread(target=_beep_loop, daemon=True)
        self._alarm_thread.start()

    def _stop_alarm_loop(self):
        self._alarm_stop.set()

    def _reset_violation_episode(self, reset_cooldown: bool = False):
        """Clear current hold timer and (optionally) cooldown so detection re-arms immediately."""
        self._viol_start_ts = 0.0
        self._viol_kind = None
        self._viol_raised = False
        if reset_cooldown:
            self._last_violation_ts = 0.0

    def _show_highrisk_popup(self, risk_text: str):
        if self._alert_top and tk.Toplevel.winfo_exists(self._alert_top):
            return
        self._start_alarm_loop()

        top = tk.Toplevel(self)
        self._alert_top = top
        top.title("High Risk Violation")
        top.configure(bg="#7f1d1d")
        try: top.attributes("-topmost", True)
        except Exception: pass

        top.grab_set()
        wrapper = tk.Frame(top, bg="#7f1d1d")
        wrapper.pack(padx=18, pady=16)
        tk.Label(wrapper, text="⚠  DANGER", bg="#7f1d1d", fg="#ffffff",
                 font=("Segoe UI", 20, "bold")).pack(pady=(2, 6))
        tk.Label(wrapper, text=risk_text, bg="#7f1d1d", fg="#fde68a",
                 font=("Segoe UI", 12)).pack(pady=(2, 12))

        def _on_ok():
            self._stop_alarm_loop()
            try: top.grab_release()
            except Exception: pass
            try: top.destroy()
            finally: self._alert_top = None
            self._reset_violation_episode(reset_cooldown=True)

        ok_btn = tk.Button(wrapper, text="OK", font=("Segoe UI", 11, "bold"),
                           fg="#ffffff", bg="#b91c1c", activebackground="#ef4444",
                           relief="flat", padx=18, pady=6, command=_on_ok)
        ok_btn.pack()
        try: ok_btn.focus_set()
        except Exception: pass

    # Risk code
    def _compute_risk_code(self, h_ok: bool, v_ok: bool, g_ok: bool, b_ok: bool) -> Optional[str]:
        missing = []
        if not h_ok: missing.append("helmet")
        if not v_ok: missing.append("vest")
        if not g_ok: missing.append("gloves")
        if not b_ok: missing.append("boots")
        if not missing:
            return None
        if missing == ["helmet", "vest"]:
            return "helmet_and_vest_missing"
        return f"{'_'.join(missing)}_missing"

    # Parse "P:.." from DetectorResult.counts_text
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

    # UI tick
    def _ui_update_loop(self):
        if self._destroyed or not self._safe_widget(self): return
        frame = self._last_frame
        if frame is not None and self._online:
            disp = frame
            fps_val = None
            if self.detector:
                try:
                    annotated, res = self.detector.infer(disp)

                    # If no persons in frame, cancel any ongoing violation episode.
                    person_count = self._parse_person_count(getattr(res, "counts_text", ""))
                    if person_count == 0:
                        self._reset_violation_episode()
                    else:
                        h_ok = bool(getattr(res, "any_helmet", False))
                        v_ok = bool(getattr(res, "any_vest", False))
                        g_ok = bool(getattr(res, "any_gloves", False))
                        b_ok = bool(getattr(res, "any_boots", False))
                        risk_now = self._compute_risk_code(h_ok, v_ok, g_ok, b_ok)

                        now = time.time()
                        if risk_now is None:
                            self._reset_violation_episode()
                        else:
                            if self._viol_kind != risk_now:
                                self._viol_kind = risk_now
                                self._viol_start_ts = now
                                self._viol_raised = False
                            held = (now - self._viol_start_ts) if self._viol_start_ts else 0.0
                            if (not self._viol_raised) and held >= float(self.violation_hold_s):
                                zlevel = _zone_level(self._current_zone or {})
                                self._log_violation_async(annotated, risk_now, zlevel)
                                self._viol_raised = True
                                if zlevel == "high":
                                    self.after(0, lambda: self._show_highrisk_popup(
                                        "Offender non-complying in a HIGH-RISK zone"
                                    ))

                    now = time.time()
                    fps_val = (1.0/(now-self._tprev)) if self._tprev else 0.0
                    self._tprev = now
                    tag = f"Live | {res.hud_text} | hold:{int(self.violation_hold_s)}s"
                    cv2.putText(annotated, tag, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (50, 220, 255), 2)
                    disp = annotated
                except Exception:
                    pass

            # draw to UI
            if self._safe_widget(self.video_label):
                h, w = max(1, self.video_label.winfo_height()), max(1, self.video_label.winfo_width())
                fh, fw = disp.shape[:2]; scale = min(w/max(1,fw), h/max(1,fh))
                resized = cv2.resize(disp, (max(1, int(fw*scale)), max(1, int(fh*scale))))
                rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                imgtk = ImageTk.PhotoImage(image=Image.fromarray(rgb))
                self.video_label.imgtk = imgtk
                self.video_label.config(image=imgtk, text="")

            self._set_chip("Streaming", ok=True)
            if self._fps_lbl is not None and self._safe_widget(self._fps_lbl):
                self._fps_lbl.config(text=f"FPS {fps_val:.1f}" if fps_val is not None else "FPS —")
        else:
            if not self._online:
                self._draw_offline_canvas("Camera Offline")
                self._set_chip("Offline", ok=False)

        if not self._destroyed and self._safe_widget(self):
            self.after(33, self._ui_update_loop)

    def _draw_offline_canvas(self, text):
        if not self._safe_widget(self.video_label): return
        w, h = max(320, self.video_label.winfo_width()), max(180, self.video_label.winfo_height())
        canvas = np.zeros((h, w, 3), dtype=np.uint8)
        cv2.putText(canvas, text, (20, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        imgtk = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)))
        self.video_label.imgtk = imgtk
        self.video_label.config(image=imgtk)

    def _on_zone_changed(self, _e=None):
        name = self.zone_menu.get() or self.selected_zone.get()
        self._set_zone_badge(name)
        if not name or name.startswith("("):
            self._set_offline("No zones.")
            self.after(10, self._defocus_zone_menu)
            return
        self._open_zone_stream(name)
        # Make it look like image #3 immediately after switching
        self.after(10, self._defocus_zone_menu)

    def destroy(self):
        self._destroyed = True
        self._stop_reader.set()
        try:
            if self._reader_thread and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=1.0)
        except Exception:
            pass
        self._release_cap()
        self._stop_alarm_loop()
        super().destroy()

    # Detector loader
    def _load_detector(self):
        if getattr(self, "detector", None) is not None:
            try:
                if self._safe_widget(self.status):
                    self.status.config(text="Model ready")
                self._set_chip("Model ready", ok=True)
            except Exception:
                pass
            return

        # primary PPE (helmet/vest)
        p1 = os.path.join("data", "model", "best.pt")
        p2 = os.path.join("data", "models", "best.pt")
        ppe_path = p1 if os.path.exists(p1) else (p2 if os.path.exists(p2) else None)

        # person model
        y1 = os.path.join("data", "model", "yolov8n.pt")
        y2 = os.path.join("data", "models", "yolov8n.pt")
        person_model = y1 if os.path.exists(y1) else (y2 if os.path.exists(y2) else "yolov8n.pt")

        # secondary gloves/boots
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

        if not ppe_path:
            if self._safe_widget(self.status):
                self.status.config(text="model not found")
            self._set_chip("Model not found", ok=False)
            return

        # prefer GPU if available; this is NOT a logic change, just device selection
        device = "cuda:0"
        try:
            import torch
            if not torch.cuda.is_available():
                device = "cpu"
        except Exception:
            device = "cpu"

        try:
            self.detector = PPEDetector(
                ppe_model=ppe_path,
                person_model=person_model,
                glove_boot_model=gb_model,
                device=device,
                imgsz=832,
                conf=0.30,
                iou=0.70,
                part_conf=0.55,
                relax=True,
                fix_label_shift=True,
                show_parts=True,
                person_conf=0.25,
                person_iou_nms=0.80,
                person_center_eps=0.08,
                prefer_person_from_parts=False,
                # smoothing / flicker resistance
                on_frames_helmet=3,
                off_frames_helmet=5,
                on_frames_other=2,
                off_frames_other=4,
                track_iou=0.30,
            )
            gb_name = os.path.basename(gb_model) if gb_model else "—"
            if self._safe_widget(self.status):
                self.status.config(text=f"Model loaded: PPE:{os.path.basename(ppe_path)} / GB:{gb_name}")
            self._set_chip("Model loaded", ok=True)
        except Exception as e:
            if self._safe_widget(self.status):
                self.status.config(text=f"Model load failed: {e}")
            self._set_chip("Model error", ok=False)

    def _set_offline(self, msg):
        self._online = False
        if self._safe_widget(self.status):
            self.status.config(text=msg)
        self._last_frame = None
        self._tprev = None
        self._set_chip("Offline", ok=False)
        self._set_zone_badge(self.selected_zone.get() or "—")
