# app.py
from __future__ import annotations

# ── load .env BEFORE any other imports that read env ──
try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(filename=".env", usecwd=True), override=True)
except Exception:
    pass

# (Optional) quiet noisy logs; comment out if not desired
import os as _os
_os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")   # TensorFlow: show errors only
_os.environ.setdefault("GRPC_VERBOSITY", "ERROR")     # gRPC: suppress info/warnings

import threading
import time
import traceback
import tkinter as tk
from tkinter import messagebox
from typing import Optional, Tuple

# Optional: OpenCV for RTSP probing
try:
    import cv2  # pip install opencv-python or opencv-python-headless
except Exception:
    cv2 = None  # We'll handle this gracefully

from firebase_admin import firestore  # for SERVER_TIMESTAMP

# UI / Pages
from services.ui_theme import apply_theme, PALETTE
from modules.login import LoginPage
from modules.dashboard import Dashboard
from pages.profile import ProfilePage
from pages.superadmin_companies import SuperadminCompaniesPage

from services.firebase_client import get_db
from services.zones import list_cameras_by_company

# Lazy loader + LiveMonitor page
from services.async_view import LazyPage
from pages.live_monitor import LiveMonitorPage

# Persistent shell for all non-dashboard pages
from services.ui_shell import PageShell

APP_TITLE = "CompliGuard"
HEARTBEAT_INTERVAL_SEC = 60
RTSP_OPEN_TIMEOUT_SEC = 6
RTSP_READ_TIMEOUT_SEC = 4
RTSP_READ_FRAMES = 1

USE_CUDA = False
CUDA_DEVICE = "cuda:0"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)

        # Window + theme
        self.geometry("1100x700")
        try:
            apply_theme(self, appearance="dark")
        except Exception:
            pass
        try:
            self.configure(bg=PALETTE.get("bg", "#0E1116"))
        except Exception:
            self.configure(bg="#0E1116")

        # Surfacing Tk exceptions
        self.report_callback_exception = self._report_exc  # type: ignore

        # Session/context fields
        self.current_user: Optional[dict] = None
        self.current_user_email = ""
        self.current_user_role = ""
        self.current_company_id: Optional[object] = None
        self.current_company_name = ""

        # Heartbeat thread control
        self._hb_thread: Optional[threading.Thread] = None
        self._hb_stop = threading.Event()

        # UI container
        self.container = tk.Frame(self, bg=PALETTE.get("bg", "#0E1116"))
        self.container.pack(fill="both", expand=True)

        # Clean shutdown
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Start on login
        self._show_login()

        # Full screen helpers
        self.after(50, self._apply_fullscreen)
        self.bind("<F11>", lambda _e: self._toggle_fullscreen())
        self.bind("<Escape>", lambda _e: self._exit_fullscreen())

    # ------ full screen helpers ------
    def _apply_fullscreen(self):
        try:
            self.state("zoomed")
            self.update_idletasks()
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            if self.winfo_width() < sw - 10 or self.winfo_height() < sh - 70:
                self.geometry(f"{sw}x{sh}+0+0")
        except Exception:
            try:
                sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
                self.geometry(f"{sw}x{sh}+0+0")
            except Exception:
                pass

    def _toggle_fullscreen(self):
        try:
            cur = bool(self.attributes("-fullscreen"))
            self.attributes("-fullscreen", not cur)
        except Exception:
            try:
                if self.state() == "zoomed":
                    self.state("normal")
                else:
                    self.state("zoomed")
            except Exception:
                pass

    def _exit_fullscreen(self):
        try:
            self.attributes("-fullscreen", False)
        except Exception:
            pass
        try:
            self.state("zoomed")
        except Exception:
            pass

    # ------ global Tk error surfacer ------
    def _report_exc(self, exc, val, tb):
        msg = "".join(traceback.format_exception(exc, val, tb))
        print(msg)
        try:
            messagebox.showerror("Unexpected Error", msg)
        except Exception:
            pass

    # ------ swapping helpers (keeps sidebar persistent) ------
    def _clear_container(self):
        for w in self.container.winfo_children():
            w.destroy()

    def _swap_to(self, frame_cls, *, active_key: str = "home", title: str = "CompliGuard", **kwargs):
        """
        If the page is NOT a PageShell subclass, mount a PageShell and place the page
        inside shell.content so the sidebar/header persist.
        """
        self._clear_container()
        try:
            if issubclass(frame_cls, PageShell):
                frame = frame_cls(self.container, controller=self, **kwargs)
                frame.pack(fill="both", expand=True)
            else:
                shell = PageShell(self.container, controller=self, title=title, active_key=active_key)
                shell.pack(fill="both", expand=True)
                try:
                    inner = frame_cls(shell.content, controller=self, **kwargs)
                except TypeError:
                    inner = frame_cls(shell.content, controller=self)
                inner.pack(fill="both", expand=True)
        except Exception as e:
            tb = traceback.format_exc()
            print(tb)
            try:
                messagebox.showerror("UI error", f"{e}\n\n{tb}")
            finally:
                ph = tk.Frame(self.container, bg=PALETTE.get("card", "#161A22"))
                ph.pack(fill="both", expand=True)

    def _show_login(self):
        self._clear_container()
        try:
            frame = LoginPage(self.container, controller=self)
            frame.pack(fill="both", expand=True)
        except Exception as e:
            messagebox.showerror("UI error", str(e))

    # ------ central navigation ------
    def navigate(self, key: str):
        role = (self.current_user_role or "").strip().lower()

        # Superadmin routes → SuperadminCompaniesPage
        if role == "superadmin":
            if key == "companies":
                self._swap_to(
                    SuperadminCompaniesPage,
                    active_key="companies",
                    title="Companies (Superadmin)",
                    user=self.current_user,
                )
            elif key == "profile":
                self._swap_to(ProfilePage, active_key="profile", title="Profile", user=self.current_user)
            else:
                self._swap_to(
                    SuperadminCompaniesPage,
                    active_key="companies",
                    title="Companies (Superadmin)",
                    user=self.current_user,
                )
            return

        # Company/normal admin routing
        if key == "home":
            self._swap_to(Dashboard, user=self.current_user)
        elif key == "zones":
            from pages.zones import ZonesPage
            self._swap_to(ZonesPage, active_key="zones", title="Zone Management", user=self.current_user)
        elif key == "entry":
            from pages.entry import EntryPage
            self._swap_to(EntryPage, active_key="entry", title="Entry Verification", user=self.current_user)
        elif key == "live":
            self.open_live_monitor_lazy()
        elif key == "logs":
            from pages.logs import LogsPage
            self._swap_to(LogsPage, active_key="logs", title="Logs", user=self.current_user)
        elif key == "reports":
            from pages.reports import ReportsPage
            self._swap_to(ReportsPage, active_key="reports", title="Reports", user=self.current_user)
        elif key in ("add admin", "add_admin", "settings"):
            from pages.add_admin import AddAdminPage
            self._swap_to(AddAdminPage, active_key="add admin", title="Add Admin", user=self.current_user)
        elif key == "workers":
            from pages.workers import WorkersPage
            self._swap_to(WorkersPage, active_key="workers", title="Workers", user=self.current_user)
        elif key == "profile":
            self._swap_to(ProfilePage, active_key="profile", title="Profile", user=self.current_user)
        elif key == "companies":
            self._swap_to(Dashboard, user=self.current_user)
        else:
            self._swap_to(Dashboard, user=self.current_user)

    # ------ Lazy Live Monitor ------
    def open_live_monitor_lazy(self):
        def worker():
            return {"detector": None}

        def render(res, container):
            shell = PageShell(container, controller=self, title="Live Monitor", active_key="live")
            shell.pack(fill="both", expand=True)
            page = LiveMonitorPage(shell.content, controller=self, preloaded_detector=res.get("detector"))
            page.pack(fill="both", expand=True)
            return shell

        self._clear_container()
        lazy = LazyPage(self.container, worker, render, title="Live Monitor")
        lazy.pack(fill="both", expand=True)

    # ------ login success ------
    def show_dashboard(self, user: dict):
        self.current_user = user or {}
        self.current_user_email = (self.current_user.get("email") or "").lower()
        self.current_user_role = self.current_user.get("role", "")
        self.current_company_id = self.current_user.get("company_id")
        self.current_company_name = self.current_user.get("company_name", "")

        if (self.current_user_role or "").strip().lower() == "superadmin":
            self._stop_health_loop()
            self._swap_to(SuperadminCompaniesPage, active_key="companies", title="Companies (Superadmin)", user=self.current_user)
        else:
            self._start_health_loop()
            self._swap_to(Dashboard, user=self.current_user)

    def logout(self):
        self._stop_health_loop()
        self.current_user = None
        self.current_user_email = ""
        self.current_user_role = ""
        self.current_company_id = None
        self.current_company_name = ""
        self._show_login()

    # ------ RTSP probe helpers ------
    @staticmethod
    def _probe_rtsp(rtsp_url: str) -> Tuple[bool, str]:
        if not rtsp_url:
            return False, "missing rtsp_url"
        if cv2 is None:
            return False, "opencv not installed"

        cap = None
        try:
            cap = cv2.VideoCapture(rtsp_url)
            t0 = time.time()
            while time.time() - t0 < RTSP_OPEN_TIMEOUT_SEC and not cap.isOpened():
                time.sleep(0.2)
            if not cap.isOpened():
                return False, "open timeout"

            read_ok = False
            t1 = time.time()
            frames = 0
            while frames < RTSP_READ_FRAMES and time.time() - t1 < RTSP_READ_TIMEOUT_SEC:
                ok, _ = cap.read()
                if ok:
                    read_ok = True
                    break
                time.sleep(0.1)
            if not read_ok:
                return False, "read timeout"

            return True, ""
        except Exception as e:
            return False, str(e)
        finally:
            try:
                if cap is not None:
                    cap.release()
            except Exception:
                pass

    # ------ background loop ------
    def _start_health_loop(self):
        if (self.current_user_role or "").strip().lower() == "superadmin":
            return

        self._stop_health_loop()
        self._hb_stop.clear()

        def _loop():
            db = get_db()
            while not self._hb_stop.is_set():
                try:
                    company_id = self.current_company_id
                    if not company_id:
                        time.sleep(2)
                        continue

                    cameras = list_cameras_by_company(company_id)
                    for cam in cameras:
                        cam_id = cam["id"]
                        rtsp = (cam.get("rtsp_url") or "").strip()
                        ok, err = self._probe_rtsp(rtsp)

                        payload = {
                            "online": ok,
                            "status": "online" if ok else "offline",
                            "last_heartbeat": firestore.SERVER_TIMESTAMP if ok else None,
                            "last_probe_ok": ok,
                            "last_probe_error": "" if ok else err[:200],
                            "last_probe_at": firestore.SERVER_TIMESTAMP,
                            "updated_at": firestore.SERVER_TIMESTAMP,
                        }
                        try:
                            db.collection("cameras").document(cam_id).update(payload)
                        except Exception as e2:
                            print(f"[health] update fail {cam_id}: {e2}")

                except Exception as e:
                    print(f"[health] loop error: {e}")

                for _ in range(HEARTBEAT_INTERVAL_SEC):
                    if self._hb_stop.is_set():
                        break
                    time.sleep(1)

        self._hb_thread = threading.Thread(target=_loop, name="RTSPHealthLoop", daemon=True)
        self._hb_thread.start()

    def _stop_health_loop(self):
        if self._hb_thread and self._hb_thread.is_alive():
            self._hb_stop.set()
            self._hb_thread.join(timeout=3.0)
        self._hb_thread = None
        self._hb_stop.clear()

    def _on_close(self):
        self._stop_health_loop()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
