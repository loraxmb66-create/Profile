#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Manager – Mở/Kill nhiều Telegram theo thư mục (Windows) – bản tối ưu + tuỳ biến

Tính năng:
• Alias: đặt tên profile theo ý (cột “Alias”, nút Rename / Set Alias)
• Restart Selected (Terminate → Open lại)
• Giới hạn số tiến trình mở song song (Max parallel) khi Open All
• Identify Accounts: cố gắng lấy tên từ window title (cần pywin32), nếu không rõ thì hỏi nhập tay rồi lưu alias
• Quét psutil 1 lần/chu kỳ + update incremental → mượt
• Chỉnh Interval 0.5–10s, Auto refresh

Cài đặt:
  pip install psutil
  # tự động nhận tên (không bắt buộc):
  pip install pywin32

Chạy:  py telegram_manager.py
"""
from __future__ import annotations
import os, json, time, threading, subprocess, queue, re
from dataclasses import dataclass
from typing import List, Optional, Dict

try:
    import psutil  # type: ignore
except Exception:
    psutil = None

# PyWin32 (tùy chọn để đọc window title theo PID)
try:
    import win32gui, win32process  # type: ignore
except Exception:
    win32gui = None
    win32process = None

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

APP_TITLE   = "Telegram Manager – Optimized + Custom"
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "telegram_manager.json")
EXECUTABLE_CANDIDATES = ["Telegram.exe", "Telegram Desktop.exe", "TelegramPortable.exe"]

@dataclass
class Profile:
    name: str
    folder: str
    exe: str
    pid: Optional[int] = None

# ─────────────────────────── Helpers ───────────────────────────

def normpath(p: str) -> str:
    return os.path.normcase(os.path.abspath(p))

def load_config() -> dict:
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def ask_base_folder() -> Optional[str]:
    return filedialog.askdirectory(title="Chọn thư mục gốc chứa 'Telegram 1', 'Telegram 2', ...") or None

def find_exe_in_folder(folder: str) -> Optional[str]:
    for name in EXECUTABLE_CANDIDATES:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    # tìm 1 cấp con
    try:
        for root, _, files in os.walk(folder):
            for fn in files:
                if fn.lower().startswith("telegram") and fn.lower().endswith(".exe"):
                    return os.path.join(root, fn)
            break
    except Exception:
        pass
    return None

def scan_profiles(base_folder: str) -> List[Profile]:
    profiles: List[Profile] = []
    try:
        def sort_key(s: str):
            m = re.search(r"(\d+)$", s)
            return (int(m.group(1)) if m else 999999, s)
        for name in sorted(os.listdir(base_folder), key=sort_key):
            p = os.path.join(base_folder, name)
            if not os.path.isdir(p):
                continue
            exe = find_exe_in_folder(p)
            if exe:
                profiles.append(Profile(name=name, folder=p, exe=exe, pid=None))
    except Exception:
        pass
    return profiles

# ─────────────────────────── Process Snapshot (1 lần/chu kỳ) ───────────────────────────

def build_pid_snapshot(profiles: List[Profile]) -> Dict[str, Optional[int]]:
    result: Dict[str, Optional[int]] = {p.name: None for p in profiles}
    if psutil is None:
        return result
    by_exe: Dict[str, List[Profile]] = {}
    by_cwd: Dict[str, List[Profile]] = {}
    for p in profiles:
        by_exe.setdefault(normpath(p.exe), []).append(p)
        by_cwd.setdefault(normpath(p.folder), []).append(p)
    try:
        for proc in psutil.process_iter(["pid","name","exe","cwd"]):
            info = proc.info
            name = (info.get("name") or "").lower()
            if "telegram" not in name:
                continue
            exen = normpath(info.get("exe") or ".") if info.get("exe") else ""
            cwdn = normpath(info.get("cwd") or ".") if info.get("cwd") else ""
            pid = int(info["pid"]) if info.get("pid") else None
            if exen and exen in by_exe:
                for prof in by_exe[exen]:
                    if result[prof.name] is None:
                        result[prof.name] = pid
            if cwdn and cwdn in by_cwd:
                for prof in by_cwd[cwdn]:
                    if result[prof.name] is None:
                        result[prof.name] = pid
            if exen:
                for prof in profiles:
                    if result[prof.name] is None and exen.startswith(normpath(prof.folder)):
                        result[prof.name] = pid
                        break
    except Exception:
        pass
    return result

# ─────────────────────────── Open/Kill/Restart ───────────────────────────

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

def open_profile(profile: Profile) -> tuple[bool, str]:
    if not os.path.isfile(profile.exe):
        return False, f"Không thấy exe: {profile.exe}"
    try:
        subprocess.Popen(
            [profile.exe], cwd=profile.folder, close_fds=True,
            creationflags=(DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
        )
        return True, "Đã mở"
    except Exception as e:
        return False, f"Lỗi mở: {e}"

def kill_profile_by_pid(pid: int, force: bool=False) -> tuple[bool, str]:
    if psutil is None:
        try:
            subprocess.run(["taskkill","/PID", str(pid), "/F" if force else "/T"], capture_output=True)
            return True, "Đã taskkill"
        except Exception as e:
            return False, f"Kill lỗi: {e}"
    try:
        p = psutil.Process(pid)
        if force:
            p.kill(); p.wait(timeout=5)
            return True, f"Killed {pid}"
        p.terminate()
        try:
            p.wait(timeout=4)
            return True, f"Terminated {pid}"
        except psutil.TimeoutExpired:
            p.kill(); p.wait(timeout=5)
            return True, f"Force killed {pid}"
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        return False, f"Kill lỗi: {e}"

def restart_profile(profile: Profile) -> str:
    if profile.pid:
        kill_profile_by_pid(profile.pid)
        time.sleep(0.6)
    ok, msg = open_profile(profile)
    return msg

# ─────────────────────────── Identify account (pywin32) ───────────────────────────

def get_window_titles_by_pid(pid: int) -> List[str]:
    titles: List[str] = []
    if not (win32gui and win32process):
        return titles
    def cb(hwnd, _):
        try:
            _, p = win32process.GetWindowThreadProcessId(hwnd)
            if p == pid and win32gui.IsWindowVisible(hwnd):
                t = win32gui.GetWindowText(hwnd)
                if t: titles.append(t)
        except Exception:
            pass
        return True
    try:
        win32gui.EnumWindows(cb, None)
    except Exception:
        pass
    return titles

ALIAS_HINT_RE = re.compile(r"@\w+|\b\+?\d{6,}\b", re.I)

# ─────────────────────────── GUI ───────────────────────────

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1080x600")

        self.cfg = load_config()
        self.aliases: Dict[str, str] = self.cfg.get("aliases", {})  # key = normpath(folder)
        base = self.cfg.get("base_dir")
        if not base or not os.path.isdir(base):
            base = ask_base_folder()
            if not base:
                messagebox.showerror("Thiếu đường dẫn", "Bạn cần chọn thư mục gốc chứa các thư mục Telegram.")
                self.root.destroy(); return
            self.cfg["base_dir"] = base; save_config(self.cfg)
        self.base_dir = base

        # Top bar
        frm_top = ttk.Frame(root) ; frm_top.pack(fill=tk.X, padx=10, pady=6)
        ttk.Label(frm_top, text="Base:").pack(side=tk.LEFT)
        self.base_lbl = ttk.Label(frm_top, text=self.base_dir, foreground="#0c4a6e")
        self.base_lbl.pack(side=tk.LEFT, padx=6)
        ttk.Button(frm_top, text="Đổi...", command=self.change_base).pack(side=tk.LEFT, padx=4)
        ttk.Button(frm_top, text="Rescan", command=self.rescan_profiles).pack(side=tk.LEFT, padx=4)
        ttk.Button(frm_top, text="Open All", command=self.open_all).pack(side=tk.LEFT, padx=8)
        ttk.Button(frm_top, text="Kill All", command=self.kill_all).pack(side=tk.LEFT)
        ttk.Button(frm_top, text="Restart Selected", command=self.restart_selected).pack(side=tk.LEFT, padx=8)
        ttk.Button(frm_top, text="Rename / Set Alias", command=self.rename_selected).pack(side=tk.LEFT)
        ttk.Button(frm_top, text="Identify Accounts", command=self.identify_selected).pack(side=tk.LEFT, padx=8)

        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm_top, text="Auto refresh", variable=self.auto_var).pack(side=tk.RIGHT)
        ttk.Label(frm_top, text="Interval(s)").pack(side=tk.RIGHT, padx=(0,4))
        self.interval = tk.DoubleVar(value=2.0)
        ttk.Spinbox(frm_top, from_=0.5, to=10.0, increment=0.5, textvariable=self.interval, width=5).pack(side=tk.RIGHT)
        ttk.Label(frm_top, text="Max parallel").pack(side=tk.RIGHT, padx=(12,4))
        self.max_parallel = tk.IntVar(value=3)
        ttk.Spinbox(frm_top, from_=1, to=20, textvariable=self.max_parallel, width=4).pack(side=tk.RIGHT)

        # Table
        cols = ("alias","name","status","pid","exe","folder")
        self.tree = ttk.Treeview(root, columns=cols, show="headings", height=20)
        for c, w in [("alias",160),("name",120),("status",110),("pid",70),("exe",360),("folder",380)]:
            self.tree.heading(c, text=c.capitalize())
            self.tree.column(c, width=w, anchor=(tk.CENTER if c in ("status","pid") else tk.W))
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10)
        self.tree.bind("<Double-1>", self.toggle_selected)

        # Bottom log
        self.log = tk.Text(root, height=5, wrap="word"); self.log.pack(fill=tk.BOTH, expand=False, padx=10, pady=(0,10))

        # Data
        self.profiles: List[Profile] = scan_profiles(self.base_dir)
        self.populate_table_first_time()

        # Background scanner
        self.q: "queue.Queue[Dict[str, Optional[int]]]" = queue.Queue()
        self.stop_flag = False
        threading.Thread(target=self.scanner_loop, daemon=True).start()
        self.root.after(150, self.consume_queue)

    # ----- UI helpers -----
    def key_for(self, p: Profile) -> str:
        return normpath(p.folder)

    def get_alias(self, p: Profile) -> str:
        return self.aliases.get(self.key_for(p), "")

    def set_alias(self, p: Profile, alias: str):
        self.aliases[self.key_for(p)] = alias
        self.cfg["aliases"] = self.aliases
        save_config(self.cfg)

    def populate_table_first_time(self):
        for p in self.profiles:
            self.tree.insert("", tk.END, iid=p.name, values=(self.get_alias(p), p.name, "?", "", p.exe, p.folder))

    def log_write(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log.insert(tk.END, f"[{ts}] {msg}\n")
        self.log.see(tk.END)

    def change_base(self):
        new = ask_base_folder()
        if new:
            self.base_dir = new
            self.base_lbl.config(text=new)
            self.cfg["base_dir"] = new; save_config(self.cfg)
            self.rescan_profiles()

    def rescan_profiles(self):
        self.profiles = scan_profiles(self.base_dir)
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.populate_table_first_time()
        self.log_write(f"Đã quét {len(self.profiles)} profile.")

    # ----- selections -----
    def get_selected(self) -> List[Profile]:
        sels = self.tree.selection()
        name2p = {p.name: p for p in self.profiles}
        return [name2p[iid] for iid in sels if iid in name2p]

    # ----- actions -----
    def open_selected(self):
        for p in self.get_selected():
            ok, msg = open_profile(p)
            self.log_write(f"[{p.name}] {msg}")

    def kill_selected(self):
        items = self.get_selected()
        if not items:
            messagebox.showinfo("Kill", "Chọn ít nhất 1 profile")
            return
        if not messagebox.askyesno("Xác nhận", f"Kill {len(items)} profile?"):
            return
        for p in items:
            if p.pid:
                ok, msg = kill_profile_by_pid(p.pid)
                self.log_write(f"[{p.name}] {msg}")

    def restart_selected(self):
        items = self.get_selected()
        if not items:
            messagebox.showinfo("Restart", "Chọn ít nhất 1 profile")
            return
        for p in items:
            msg = restart_profile(p)
            self.log_write(f"[{p.name}] {msg}")

    def open_all(self):
        if not self.profiles:
            return
        from concurrent.futures import ThreadPoolExecutor, as_completed
        max_workers = max(1, int(self.max_parallel.get()))
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(open_profile, p): p for p in self.profiles}
            for fut in as_completed(futs):
                p = futs[fut]
                ok, msg = fut.result()
                self.log_write(f"[{p.name}] {msg}")

    def kill_all(self):
        if not self.profiles:
            return
        if not messagebox.askyesno("Xác nhận", f"Kill tất cả {len(self.profiles)} profile?"):
            return
        for p in self.profiles:
            if p.pid:
                ok, msg = kill_profile_by_pid(p.pid)
                self.log_write(f"[{p.name}] {msg}")

    def toggle_selected(self, event=None):
        item = self.tree.identify_row(event.y) if event else None
        if not item:
            return
        p = next((x for x in self.profiles if x.name == item), None)
        if not p:
            return
        if p.pid:
            ok, msg = kill_profile_by_pid(p.pid)
        else:
            ok, msg = open_profile(p)
        self.log_write(f"[{p.name}] {msg}")

    def rename_selected(self):
        items = self.get_selected()
        if not items:
            messagebox.showinfo("Alias", "Chọn ít nhất 1 profile")
            return
        for p in items:
            cur = self.get_alias(p) or p.name
            alias = simpledialog.askstring("Set Alias", f"Đặt tên cho {p.name}", initialvalue=cur)
            if alias is not None:
                self.set_alias(p, alias.strip())
                self.tree.set(p.name, "alias", self.get_alias(p))

    def identify_selected(self):
        items = self.get_selected() or self.profiles
        if not items:
            return
        if not (win32gui and win32process):
            messagebox.showwarning("Thiếu pywin32", "Tự động nhận tên cần 'pip install pywin32'. Sẽ hỏi nhập tay.")
        for p in items:
            suggested = None
            if p.pid:
                titles = get_window_titles_by_pid(p.pid)
                suggested = next((t for t in titles if ALIAS_HINT_RE.search(t)), None) or (titles[0] if titles else None)
            if not suggested:
                if not p.pid:
                    open_profile(p); time.sleep(1.2)
                    snap = build_pid_snapshot([p]); p.pid = snap.get(p.name)
                    titles = get_window_titles_by_pid(p.pid) if p.pid else []
                    suggested = next((t for t in titles if ALIAS_HINT_RE.search(t)), None) or (titles[0] if titles else None)
            if not suggested:
                suggested = self.get_alias(p) or p.name
            alias = simpledialog.askstring("Identify", f"Tên tài khoản cho {p.name}", initialvalue=suggested)
            if alias:
                self.set_alias(p, alias.strip())
                self.tree.set(p.name, "alias", self.get_alias(p))
                self.log_write(f"[{p.name}] alias = {alias.strip()}")

    # ----- background scanner -----
    def scanner_loop(self):
        while not self.stop_flag:
            if self.auto_var.get():
                snap = build_pid_snapshot(self.profiles)
                try:
                    self.q.put_nowait(snap)
                except queue.Full:
                    pass
            time.sleep(max(0.2, float(self.interval.get())))

    def consume_queue(self):
        try:
            while True:
                snap = self.q.get_nowait()
                for p in self.profiles:
                    new_pid = snap.get(p.name)
                    if p.pid != new_pid:
                        p.pid = new_pid
                        self.tree.set(p.name, "pid", p.pid or "")
                        self.tree.set(p.name, "status", "RUNNING" if p.pid else "STOPPED")
                        self.tree.set(p.name, "alias", self.get_alias(p))
        except queue.Empty:
            pass
        self.root.after(150, self.consume_queue)

    def on_close(self):
        self.stop_flag = True
        self.root.destroy()

# ─────────────────────────── main ───────────────────────────

def main():
    if psutil is None:
        messagebox.showwarning("Thiếu psutil", "Bạn chưa cài psutil. Mở CMD và chạy: pip install psutil")
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
