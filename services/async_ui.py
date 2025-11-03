# services/async_ui.py
from __future__ import annotations

import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Any, Optional

# I keep a small global pool for background work (Firestore, HTTP, file I/O, etc.).
# 4 workers are plenty for my UI so I don't overwhelm the system.
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bg")


def _widget_alive(w: Optional[tk.Misc]) -> bool:
    """Return True if the widget still exists (not destroyed)."""
    try:
        return bool(w) and w.winfo_exists()
    except Exception:
        return False


def run_async(
    func: Callable[[], Any],
    ui_call: Callable[[Any], None],
    tk_widget: tk.Misc,
) -> Future:
    """
    Run `func` in a background thread and deliver its result back on the Tk main thread.

    Design notes (how I use it):
      • I pass pure work in `func` (no Tk calls). It returns a value or raises.
      • When the future completes, I schedule `ui_call(value)` on the main thread.
      • If `func` raised, I call `ui_call(Exception)` instead so the UI layer can decide.
      • I only post back if `tk_widget` is still alive to avoid touching dead widgets.

    Returns:
      concurrent.futures.Future — I can cancel it or inspect exceptions if needed.
    """
    fut: Future = _EXECUTOR.submit(func)

    def _deliver(f: Future) -> None:
        # Collect either the result or the exception
        try:
            res = f.result()
            err: Optional[BaseException] = None
        except BaseException as e:  # catch BaseException so KeyboardError etc. also propagate
            res, err = None, e

        def _call_ui() -> None:
            if not _widget_alive(tk_widget):
                return
            try:
                # My convention: pass the Exception object if there was an error,
                # otherwise pass the successful result.
                ui_call(err if err is not None else res)
            except tk.TclError:
                # Widget died right before the call; nothing to do.
                pass
            except Exception:
                # I don't let a UI exception kill the Tk loop.
                pass

        if _widget_alive(tk_widget):
            try:
                tk_widget.after(0, _call_ui)
            except tk.TclError:
                # Main loop may be shutting down; ignore.
                pass

    fut.add_done_callback(_deliver)
    return fut


# Backward-compatible alias (older code imports `run`)
def run(
    worker: Callable[[], Any],
    ui_call: Callable[[Any], None],
    tk_widget: tk.Misc,
) -> Future:
    """Alias to keep older imports working."""
    return run_async(worker, ui_call, tk_widget)
