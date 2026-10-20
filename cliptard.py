import tkinter as tk
import pyperclip
import keyboard
import threading
import time
import shutil
import json
import os
import sys
import subprocess
import ctypes
from pynput import mouse

import tkinter as tk
from tkinter import ttk
from tkinter.messagebox import askyesno

# path to whatever is actually running - the .py file normally,
# or the .exe itself once this is bundled with pyinstaller
if getattr(sys, "frozen", False):
    this_file = sys.executable
else:
    this_file = os.path.abspath(__file__)

# --- single instance stuff ---
# remember our own pid in a file - if we find someone else's pid
# already sitting there when we start, kill that process and stop
pidfile = os.path.join(os.path.expanduser("~"), "clipmgr.pid")

def pid_is_us(pid):
    # confirm the PID in the pidfile is actually another cliptard
    # instance (by image name) before we kill it - a stale pidfile
    # pointing at a reused PID could otherwise kill an unrelated process
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "PID eq " + str(pid), "/FO", "CSV", "/NH"],
            capture_output=True, text=True
        )
        name = os.path.basename(this_file).lower()
        return name in out.stdout.lower()
    except OSError:
        return False

if os.path.exists(pidfile):
    old_pid = None
    try:
        with open(pidfile, "r") as f:
            old_pid = int(f.read().strip())
    except (OSError, ValueError):
        old_pid = None

    if old_pid is not None and old_pid != os.getpid() and pid_is_us(old_pid):
        subprocess.run(["taskkill", "/F", "/PID", str(old_pid)],
                        capture_output=True)
        # something was already running - kill it and stop here,
        # don't start a new instance too
        try:
            os.remove(pidfile)
        except OSError:
            pass
        sys.exit()

f = open(pidfile, "w")
f.write(str(os.getpid()))
f.close()



startup_path = os.path.join(
    os.environ["APPDATA"],
    r"Microsoft\Windows\Start Menu\Programs\Startup",
    os.path.basename(this_file)
)

# only ask if it's not already in the startup folder
# (also covers the case where THIS run IS the startup copy)
if not os.path.exists(startup_path) and this_file != startup_path:
    answer = askyesno(title='autostart',
                        message='Auto start with Windows?')
    if answer:
        shutil.copyfile(this_file, startup_path)

HOTKEY = "alt+v+c"
MAX_ITEMS = 25
histfile = os.path.join(os.path.expanduser("~"), "cliphistory.json")

bg = "#1f1f1f"
bg2 = "#2b2b2b"
bg2hover = "#333"
border = "#3a3a3a"
fg = "#f2f2f2"
fg_dim = "#a0a0a0"
accent = "#4cc2ff"
danger = "#e06c6c"

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2

def round_corners(win):
    # windows 11 only - older windows just ignores this call
    try:
        hwnd = win.winfo_id()
        value = ctypes.c_int(DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(value), ctypes.sizeof(value)
        )
    except OSError:
        pass

hist = []

def load_hist():
    global hist
    if os.path.exists(histfile):
        try:
            with open(histfile, "r", encoding="utf-8") as f:
                hist = json.load(f)
        except (OSError, ValueError):
            hist = []

def save_hist():
    try:
        with open(histfile, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False)
    except OSError:
        pass

def add_to_hist(txt):
    txt = txt.strip()
    if txt == "":
        return
    for h in hist:
        if h == txt:
            hist.remove(h)
            break
    hist.insert(0, txt)
    while len(hist) > MAX_ITEMS:
        hist.pop()
    save_hist()

load_hist()

def clipboard_loop():
    last = ""
    try:
        last = pyperclip.paste()
    except pyperclip.PyperclipException:
        pass
    while True:
        try:
            cur = pyperclip.paste()
        except pyperclip.PyperclipException:
            cur = last
        if cur != last and cur.strip() != "":
            add_to_hist(cur)
            last = cur
        time.sleep(0.5)

popup_win = None
mouse_listener = None
row_widgets = []   # [{"frame", "label", "delbtn"}, ...] parallel to hist
selected_idx = -1

def close_popup():
    global popup_win, mouse_listener, row_widgets, selected_idx
    if mouse_listener:
        mouse_listener.stop()
        mouse_listener = None
    if popup_win:
        try:
            popup_win.destroy()
        except tk.TclError:
            pass
        popup_win = None
    row_widgets = []
    selected_idx = -1

def start_outside_click_watcher(win):
    # pynput runs this on its own thread, so we just check bounds
    # and hop back onto the tk thread to actually close
    global mouse_listener

    def on_click(x, y, button, pressed):
        if not pressed:
            return
        try:
            wx = win.winfo_rootx()
            wy = win.winfo_rooty()
            ww = win.winfo_width()
            wh = win.winfo_height()
        except tk.TclError:
            return  # window already gone
        if not (wx <= x <= wx + ww and wy <= y <= wy + wh):
            win.after(0, close_popup)

    mouse_listener = mouse.Listener(on_click=on_click)
    mouse_listener.start()

def select_row(idx, e=None):
    global selected_idx
    for i, rw in enumerate(row_widgets):
        on = (i == idx)
        color = bg2hover if on else bg2
        rw["frame"].configure(bg=color)
        rw["label"].configure(bg=color)
        rw["delbtn"].configure(bg=color)
    selected_idx = idx

def move_selection(delta):
    if not row_widgets:
        return
    new_idx = selected_idx + delta
    new_idx = max(0, min(len(row_widgets) - 1, new_idx))
    select_row(new_idx)

def activate_selected(e=None):
    if 0 <= selected_idx < len(hist):
        pyperclip.copy(hist[selected_idx])
        close_popup()

def delete_selected(e=None):
    if 0 <= selected_idx < len(hist):
        hist.pop(selected_idx)
        save_hist()
        refresh()

def open_popup():
    global popup_win

    # toggle - if its already open just close it
    if popup_win:
        close_popup()
        return

    w = 320
    h = 460
    win = tk.Toplevel()
    popup_win = win
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg=border)

    x = win.winfo_pointerx() - w // 2
    y = win.winfo_pointery() - h - 10
    if x < 10:
        x = 10
    if y < 10:
        y = 10
    win.geometry(str(w) + "x" + str(h) + "+" + str(x) + "+" + str(y))

    inner = tk.Frame(win, bg=bg)
    inner.pack(fill="both", expand=True, padx=1, pady=1)

    top = tk.Frame(inner, bg=bg)
    top.pack(fill="x", padx=12, pady=10)
    tk.Label(top, text="Clipboard", bg=bg, fg=fg, font=("Segoe UI", 11, "bold")).pack(side="left")
    clearbtn = tk.Label(top, text="Clear all", bg=bg, fg=accent, font=("Segoe UI", 9), cursor="hand2")
    clearbtn.pack(side="right")

    def clear_all(e=None):
        hist.clear()
        save_hist()
        refresh()
    clearbtn.bind("<Button-1>", clear_all)

    body = tk.Frame(inner, bg=bg)
    body.pack(fill="both", expand=True, padx=8, pady=(0,8))

    canvas = tk.Canvas(body, bg=bg, highlightthickness=0)
    scroll = tk.Scrollbar(body, orient="vertical", command=canvas.yview)
    list_frame = tk.Frame(canvas, bg=bg)

    list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0,0), window=list_frame, anchor="nw", width=290)
    canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta/120), "units"))

    if len(hist) == 0:
        tk.Label(list_frame, text="Items you copy will show up here", bg=bg, fg=fg_dim,
                  font=("Segoe UI", 10), wraplength=260, justify="left").pack(pady=20)

    for i, item in enumerate(hist):
        make_row(list_frame, item, i)

    if hist:
        select_row(0)

    win.bind("<Escape>", lambda e: close_popup())
    win.bind("<FocusOut>", lambda e: close_popup())
    win.bind("<Up>", lambda e: move_selection(-1))
    win.bind("<Down>", lambda e: move_selection(1))
    win.bind("<Return>", activate_selected)
    win.bind("<Delete>", delete_selected)
    win.focus_force()

    round_corners(win)

    # give the window a beat to actually get its final geometry
    # before we start checking clicks against its bounds
    win.after(150, lambda: start_outside_click_watcher(win))

def make_row(parent, text, idx):
    shown = text
    if len(shown) > 160:
        shown = shown[:160] + "..."

    row = tk.Frame(parent, bg=bg2, cursor="hand2")
    row.pack(fill="x", pady=3)
    lbl = tk.Label(row, text=shown, bg=bg2, fg=fg, font=("Segoe UI", 10),
                    wraplength=225, justify="left", anchor="w")
    lbl.pack(side="left", fill="both", expand=True, padx=(10,0), pady=8)

    delbtn = tk.Label(row, text="x", bg=bg2, fg=fg_dim, font=("Segoe UI", 10, "bold"), cursor="hand2")
    delbtn.pack(side="right", padx=10, pady=8)

    row_widgets.append({"frame": row, "label": lbl, "delbtn": delbtn})

    def do_copy(e=None):
        pyperclip.copy(text)
        close_popup()

    def do_delete(e=None):
        hist.pop(idx)
        save_hist()
        refresh()

    def hover_in(e=None):
        delbtn.configure(fg=danger)
        select_row(idx)

    def hover_out(e=None):
        delbtn.configure(fg=fg_dim)

    row.bind("<Button-1>", do_copy)
    lbl.bind("<Button-1>", do_copy)
    delbtn.bind("<Button-1>", do_delete)
    row.bind("<Enter>", hover_in)
    lbl.bind("<Enter>", hover_in)
    row.bind("<Leave>", hover_out)
    lbl.bind("<Leave>", hover_out)

def refresh():
    close_popup()
    open_popup()

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()

    t = threading.Thread(target=clipboard_loop)
    t.daemon = True
    t.start()

    keyboard.add_hotkey(HOTKEY, lambda: root.after(0, open_popup))

    print("running." , HOTKEY , "to open")

    root.mainloop()
    