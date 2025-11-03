# services/async_view.py
from __future__ import annotations

import threading
import tkinter as tk
from typing import Callable, Any, Optional

from services.ui_theme import PALETTE, FONTS


class LazyPage(tk.Frame):
    """
    LazyPage(parent, worker, render, title=None)

    I use this to render a fast skeleton immediately, then do heavy work off
    the main thread. Once the data is ready, I render the real UI on the Tk thread.

    Args:
      parent: Tk container.
      worker: () -> Any       # pure work; no Tk calls inside.
      render: (data, container) -> tk.Widget
              # must create widgets under 'container' and return the root widget.
      title: Optional page title for the skeleton header.
    """

    # Skeleton tick speed (ms). I keep it short for a snappy feel.
    _PULSE_MS = 300

    def __init__(
        self,
        parent: tk.Misc,
        worker: Callable[[], Any],
        render: Callable[[Any, tk.Frame], tk.Widget],
        title: Optional[str] = None,
    ):
        super().__init__(parent, bg=PALETTE.get("bg", "#0E1116"))
        self._worker: Callable[[], Any] = worker
        self._render: Callable[[Any, tk.Frame], tk.Widget] = render
        self._title: str = title or "Loading…"

        self._destroyed: bool = False
        self._pulse_job: Optional[str] = None
        self._tick: int = 0
        self._status: Optional[tk.Label] = None
        self._placeholder: Optional[tk.Frame] = None

        self._build_skeleton()
        self.bind("<Destroy>", self._on_destroy)

        # I run the worker in a daemon thread to avoid blocking app exit.
        t = threading.Thread(target=self._run_worker, daemon=True, name="LazyPageWorker")
        t.start()

    # ───────────────────────── UI skeleton ─────────────────────────
    def _build_skeleton(self) -> None:
        bg = PALETTE.get("bg", "#0E1116")
        card = PALETTE.get("card", "#161A22")
        border = PALETTE.get("border", "#222c3a")
        fg = PALETTE.get("fg", PALETTE.get("text", "#E5E7EB"))
        muted = PALETTE.get("muted", "#6b7280")

        # Header
        hdr = tk.Frame(self, bg=card, height=56, highlightthickness=1, highlightbackground=border)
        hdr.pack(fill="x")
        tk.Label(hdr, text=self._title, bg=card, fg=fg, font=FONTS.get("h2", ("Segoe UI", 16)), padx=16)\
            .pack(side="left")

        # Body placeholder
        body = tk.Frame(self, bg=bg)
        body.pack(fill="both", expand=True)
        self._placeholder = body

        # Card with shimmer bars (static bars + ticking status)
        cardf = tk.Frame(body, bg=card, highlightthickness=1, highlightbackground=border)
        cardf.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.7)

        pad = tk.Frame(cardf, bg=card)
        pad.pack(fill="x", padx=24, pady=18)

        tk.Label(pad, text="Preparing…", bg=card, fg=muted).pack(anchor="w", pady=(0, 12))
        # I keep 5 bars to imply layout; no animation to keep CPU low.
        for _ in range(5):
            bar = tk.Frame(pad, bg="#eef2ff", height=14)
            bar.pack(fill="x", pady=6)

        # Ticking status (Working…)
        self._status = tk.Label(
            pad,
            text="Starting",
            bg=card,
            fg=muted,
            font=FONTS.get("small", ("Segoe UI", 9)),
        )
        self._status.pack(anchor="w", pady=(10, 0))
        self._schedule_pulse()

    # ───────────────────────── Safe pulse ─────────────────────────
    def _schedule_pulse(self) -> None:
        """Start the status ticker safely."""
        if not self._destroyed:
            self._pulse_job = self.after(self._PULSE_MS, self._pulse)  # type: ignore[assignment]

    def _pulse(self) -> None:
        """Update the status text with safety checks."""
        if self._destroyed or not self.winfo_exists() or not self._status:
            return
        try:
            self._tick = (self._tick + 1) % 4
            self._status.config(text="Working" + "." * self._tick)
            self._pulse_job = self.after(self._PULSE_MS, self._pulse)  # type: ignore[assignment]
        except tk.TclError:
            # Widget likely destroyed during shutdown; stop ticking.
            self._pulse_job = None

    def _on_destroy(self, _event=None) -> None:
        """Stop scheduled callbacks when destroyed."""
        self._destroyed = True
        if self._pulse_job is not None:
            try:
                self.after_cancel(self._pulse_job)
            except Exception:
                pass
            self._pulse_job = None

    # ───────────────────────── Thread worker ─────────────────────────
    def _run_worker(self) -> None:
        """Run the blocking worker off-thread and switch back to Tk thread to finish."""
        data: Any = None
        err: Optional[BaseException] = None
        try:
            data = self._worker()
        except BaseException as e:
            # I capture BaseException so KeyboardInterrupt, etc., propagate to UI handler if needed.
            err = e
        # I always marshal back to the Tk thread for UI work.
        try:
            self.after(0, lambda: self._finish(data, err))
        except tk.TclError:
            # App may be shutting down; nothing else to do.
            pass

    def _finish(self, data: Any, err: Optional[BaseException]) -> None:
        """Replace the skeleton with either the rendered page or an error card."""
        if self._destroyed:
            return

        # Clear skeleton
        for w in self.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        if err:
            self._render_error(err)
            return

        # Mount real content
        container = tk.Frame(self, bg=PALETTE.get("bg", "#0E1116"))
        container.pack(fill="both", expand=True)

        root = self._render(data, container)
        # Some renderers may already pack/place/grid; I only pack if not mounted.
        if getattr(root, "_is_mounted", False) is False:
            try:
                root.pack(fill="both", expand=True)
            except tk.TclError:
                # If the renderer used grid/place, packing will fail; that's fine.
                pass

    def _render_error(self, err: BaseException) -> None:
        """Render a simple error card with the exception message."""
        card = PALETTE.get("card", "#161A22")
        border = PALETTE.get("border", "#222c3a")
        danger = PALETTE.get("danger", "#b91c1c")
        muted = PALETTE.get("muted", "#6b7280")

        err_card = tk.Frame(self, bg=card, highlightthickness=1, highlightbackground=border)
        err_card.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(
            err_card,
            text="Failed to load",
            font=FONTS.get("h2", ("Segoe UI", 16)),
            bg=card,
            fg=danger,
        ).pack(anchor="w", padx=16, pady=(16, 6))

        tk.Label(
            err_card,
            text=str(err),
            bg=card,
            fg=muted,
            wraplength=800,
            justify="left",
        ).pack(anchor="w", padx=16)
