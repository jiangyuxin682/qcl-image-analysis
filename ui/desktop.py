"""Desktop launcher for the self-contained QCL Processing application.

The browser is the analysis window. This small native window owns the local
server, lets the user reopen the browser, and provides a visible Quit action.
"""
from __future__ import annotations

import argparse
import errno
import json
import logging
from logging.handlers import RotatingFileHandler
import multiprocessing
import os
from pathlib import Path
import queue
import sys
import threading
import traceback
import webbrowser

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def configure_runtime():
    """Write caches and logs to a per-user folder, never into the app bundle."""
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    folder = base / "QCL Processing"
    folder.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(folder / "matplotlib")
    os.environ["MPLBACKEND"] = "Agg"
    logfile = folder / "app.log"
    logging.basicConfig(
        level=logging.INFO,
        handlers=[RotatingFileHandler(logfile, maxBytes=2_000_000, backupCount=2, encoding="utf-8")],
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )
    # Windowed Windows programs have no stdout/stderr. Some libraries need them.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(logfile, "a", encoding="utf-8", buffering=1)
    return logfile


def create_server(port=8766):
    from http.server import ThreadingHTTPServer
    from ui.app_processing import Handler

    try:
        return ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        if port == 0 or (exc.errno != errno.EADDRINUSE and getattr(exc, "winerror", None) != 10048):
            raise
        # Another copy or program is using the default port; keep its session.
        return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def run_window(logfile):
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("QCL Processing")
    root.geometry("540x260")
    root.minsize(490, 240)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="QCL Processing Workbench", font=("Segoe UI", 16, "bold")).pack(anchor="w")
    status = tk.StringVar(value="Starting the analysis engine…")
    ttk.Label(frame, textvariable=status, wraplength=475).pack(anchor="w", pady=(18, 8))
    address = tk.StringVar()
    ttk.Entry(frame, textvariable=address, state="readonly").pack(fill="x")
    ttk.Label(frame, text="Keep this window open while using the browser.").pack(anchor="w", pady=10)
    actions = ttk.Frame(frame)
    actions.pack(fill="x")
    server = None
    messages = queue.Queue()

    def open_browser():
        if address.get() and not webbrowser.open(address.get()):
            status.set("Copy the address above into your web browser.")

    open_button = ttk.Button(actions, text="Open analysis UI", command=open_browser, state="disabled")
    open_button.pack(side="left")

    def quit_app():
        if server and not messagebox.askokcancel(
            "Quit QCL Processing?",
            "Export your results before quitting. The current analysis session will be closed.",
            parent=root,
        ):
            return
        if server:
            server.shutdown()
            server.server_close()
        root.destroy()

    ttk.Button(actions, text="Quit", command=quit_app).pack(side="right")
    root.protocol("WM_DELETE_WINDOW", quit_app)

    def start():
        try:
            instance = create_server()
            threading.Thread(target=instance.serve_forever, daemon=True).start()
            messages.put((instance, None))
        except Exception:
            logging.exception("Application startup failed")
            messages.put((None, traceback.format_exc()))

    def poll():
        nonlocal server
        try:
            instance, error = messages.get_nowait()
        except queue.Empty:
            root.after(100, poll)
            return
        if error:
            status.set(f"Could not start. See the log: {logfile}")
            messagebox.showerror("QCL Processing", f"Startup failed.\n\n{error.splitlines()[-1]}\n\nLog: {logfile}", parent=root)
            return
        server = instance
        address.set(f"http://127.0.0.1:{server.server_port}")
        status.set("Ready. Your data is processed on this computer.")
        open_button.configure(state="normal")
        logging.info("Serving %s", address.get())
        open_browser()

    threading.Thread(target=start, daemon=True).start()
    root.after(100, poll)
    root.mainloop()


def main():
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="QCL Processing desktop application")
    parser.add_argument("--self-test", type=Path, metavar="REPORT_JSON")
    args = parser.parse_args()
    try:
        logfile = configure_runtime()
        if args.self_test:
            from ui.desktop_check import run_checks
            report = run_checks(check_window=sys.platform == "win32")
            args.self_test.write_text(json.dumps(report, indent=2), encoding="utf-8")
        else:
            run_window(logfile)
        return 0
    except Exception:
        details = traceback.format_exc()
        logging.exception("Desktop application failed")
        if args.self_test:
            args.self_test.write_text(json.dumps({"ok": False, "error": details}), encoding="utf-8")
        elif sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, details, "QCL Processing could not start", 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
