# pages/cameras.py
import tkinter as tk
from tkinter import ttk, messagebox
from typing import List, Dict, Any, Optional

from services.ui_theme import apply_theme, card, FONTS, PALETTE
from services.session import require_user
from services.zones import (
    list_cameras_by_company,
    create_camera,
    update_camera,
    delete_camera,
    assign_camera_to_zone,
    unassign_camera,
)

AUTO_REFRESH_MS = 10_000


class CamerasPage(tk.Frame):
    """
    Standalone camera management page.
    Not linked in dashboard — but you can embed or reuse it.
    """

    def __init__(self, parent, controller):
        super().__init__(parent, bg=PALETTE["bg"])
        self.controller = controller
        apply_theme(self)

        self.company_id: Optional[str] = None
        self._cameras: List[Dict[str, Any]] = []
        self._auto_refresh_var = tk.IntVar(value=0)
        self._refresh_job: Optional[str] = None
        self._actions_col_index = 5

        self._build()
        self._refresh_all()

    # ─────────────────────────────────────────────────────────────

    def _build(self):
        page = tk.Frame(self, bg=PALETTE["bg"])
        page.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(page, text="Camera Management", font=FONTS["h2"], bg=PALETTE["bg"]).pack(anchor="w")

        tbar = tk.Frame(page, bg=PALETTE["bg"]); tbar.pack(fill="x", pady=(8, 12))
        ttk.Button(tbar, text="Refresh", command=self._refresh_all).pack(side="left")
        ttk.Button(tbar, text="New Camera", style="Primary.TButton", command=self._open_new).pack(side="left", padx=6)
        ttk.Checkbutton(tbar, text="Auto-refresh (10s)", variable=self._auto_refresh_var,
                        command=self._toggle_auto_refresh).pack(side="left", padx=(18, 0))

        c_card, inner = card(page); c_card.pack(fill="both", expand=True)
        ttk.Label(inner, text="Cameras", font=FONTS["h3"]).pack(anchor="w", pady=(0, 6))

        self.tree = ttk.Treeview(
            inner,
            columns=("id", "name", "rtsp", "zone_id", "actions"),
            show="headings", height=20
        )
        self.tree.heading("name", text="Camera Name")
        self.tree.heading("rtsp", text="RTSP / Source")
        self.tree.heading("zone_id", text="Assigned Zone")
        self.tree.heading("actions", text="Actions")

        self.tree.column("id", width=1, stretch=False)
        self.tree.column("name", width=200, anchor="w")
        self.tree.column("rtsp", width=300, anchor="w")
        self.tree.column("zone_id", width=140, anchor="center")
        self.tree.column("actions", width=160, anchor="center")

        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Button-1>", self._on_tree_click)

    # ─────────────────────────────────────────────────────────────

    def _refresh_all(self):
        try:
            user = require_user()
        except Exception as e:
            messagebox.showerror("Cameras", f"No session: {e}")
            return
        self.company_id = str(user.get("company_id") or "").strip()
        if not self.company_id:
            return
        try:
            self._cameras = list_cameras_by_company(self.company_id)
        except Exception as e:
            messagebox.showerror("Cameras", f"Failed to load: {e}")
            return
        self._fill_table()
        if self._auto_refresh_var.get():
            self._schedule_next_refresh()

    def _fill_table(self):
        for r in self.tree.get_children():
            self.tree.delete(r)
        for cam in self._cameras:
            vals = (
                cam["id"],
                cam.get("name", ""),
                cam.get("rtsp_url", ""),
                cam.get("zone_id", "—"),
                "Edit    Delete"
            )
            self.tree.insert("", "end", values=vals)

    # ─────────────────────────────────────────────────────────────

    def _on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not item or col != f"#{self._actions_col_index}":
            return
        bbox = self.tree.bbox(item, col)
        if not bbox: return
        x, _, w, _ = bbox
        relx = event.x - x
        if relx < w / 2:
            self._edit_camera(item)
        else:
            self._delete_camera(item)

    # ─────────────────────────────────────────────────────────────

    def _open_new(self):
        dlg = tk.Toplevel(self); dlg.title("New Camera")
        frm = tk.Frame(dlg, bg=PALETTE["card"]); frm.pack(padx=16, pady=16)
        ttk.Label(frm, text="Name").grid(row=0,column=0); nm=ttk.Entry(frm); nm.grid(row=0,column=1)
        ttk.Label(frm, text="RTSP / Source").grid(row=1,column=0); rt=ttk.Entry(frm); rt.grid(row=1,column=1)
        ttk.Button(frm, text="Save", command=lambda: self._save_new(nm.get(),rt.get(),dlg)).grid(row=2,column=1)

    def _save_new(self, name, rtsp, dlg):
        if not name: messagebox.showerror("Camera","Name required"); return
        try:
            create_camera(company_id=self.company_id, name=name, rtsp_url=rtsp)
            dlg.destroy(); self._refresh_all()
        except Exception as e: messagebox.showerror("Camera",str(e))

    def _edit_camera(self, item_id):
        vals = self.tree.item(item_id,"values")
        if not vals: return
        cam_id, cur_name, cur_rtsp, cur_zone, _ = vals

        dlg = tk.Toplevel(self); dlg.title("Edit Camera")
        frm = tk.Frame(dlg, bg=PALETTE["card"]); frm.pack(padx=16, pady=16)
        ttk.Label(frm, text="Name").grid(row=0,column=0); nm=ttk.Entry(frm); nm.insert(0,cur_name); nm.grid(row=0,column=1)
        ttk.Label(frm, text="RTSP / Source").grid(row=1,column=0); rt=ttk.Entry(frm); rt.insert(0,cur_rtsp); rt.grid(row=1,column=1)
        ttk.Button(frm, text="Save", command=lambda: self._save_edit(cam_id,nm.get(),rt.get(),dlg)).grid(row=2,column=1)

    def _save_edit(self, cam_id,name,rtsp,dlg):
        try:
            update_camera(cam_id, name=name, rtsp_url=rtsp)
            dlg.destroy(); self._refresh_all()
        except Exception as e: messagebox.showerror("Edit",str(e))

    def _delete_camera(self,item_id):
        vals=self.tree.item(item_id,"values")
        if not vals: return
        cam_id=vals[0]
        if not messagebox.askyesno("Delete","Delete this camera?"): return
        try:
            delete_camera(cam_id)
            self._refresh_all()
        except Exception as e: messagebox.showerror("Delete",str(e))

    # ─────────────────────────────────────────────────────────────

    def _toggle_auto_refresh(self):
        if self._auto_refresh_var.get():
            self._refresh_all(); self._schedule_next_refresh()
        else:
            if self._refresh_job:
                try:self.after_cancel(self._refresh_job)
                except:pass; self._refresh_job=None
    def _schedule_next_refresh(self):
        if self._refresh_job:
            try:self.after_cancel(self._refresh_job)
            except:pass
        self._refresh_job = self.after(AUTO_REFRESH_MS,self._refresh_all)
