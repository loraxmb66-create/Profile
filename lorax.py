#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IT Inspector – Desktop GUI PRO (PySide6)
Tính năng mới:
• Dark Mode (lưu trạng thái)
• System Tray (ẩn/hiện nhanh, Quit)
• Hộp thoại Chi tiết PID (cmdline, CPU/RAM, open files, connections)
• Kill cả cây tiến trình (process tree)
• Export JSON & CSV
• Lưu cấu hình (refresh interval, Geo/ISP, Auto refresh, Kill enable)
"""

from __future__ import annotations
import sys, os, time, json, socket, platform
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict, deque
from datetime import datetime

# ---- deps ----
try:
    import psutil
except Exception:
    print("psutil is required. pip install psutil")
    raise

try:
    import requests
except Exception:
    requests = None

from PySide6 import QtCore, QtGui, QtWidgets
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

APP_VERSION = "2.2.0 GUI-PRO"
BRAND_NAME  = "IT Inspector"

# ------------- utils / collectors -------------
def human(n: Optional[float]) -> str:
    if n is None: return "N/A"
    n = float(n)
    for u in ["B","KB","MB","GB","TB","PB"]:
        if n < 1024: return f"{n:,.1f}{u}"
        n /= 1024
    return f"{n:.1f}EB"

def is_private_ip(ip: str) -> bool:
    try:
        import ipaddress
        return ipaddress.ip_address(ip).is_private
    except Exception:
        return False

_geo_cache: Dict[str, Tuple[Dict[str, Any], float]] = {}
_GEO_TTL = 3600.0

def geoip(ip: str) -> Optional[Dict[str, Any]]:
    if not ip or ip=="127.0.0.1" or is_private_ip(ip) or requests is None:
        return None
    now = time.time()
    if ip in _geo_cache and now - _geo_cache[ip][1] < _GEO_TTL:
        return _geo_cache[ip][0]
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,regionName,city,isp,org,as,query", timeout=2.5)
        j = r.json()
        if j.get("status") == "success":
            d = {k:j.get(k) for k in ("country","regionName","city","isp","org","as","query")}
            _geo_cache[ip] = (d, now)
            return d
    except Exception:
        pass
    return None

def sys_info() -> Dict[str, Any]:
    return {
        "brand": BRAND_NAME,
        "version": APP_VERSION,
        "hostname": platform.node(),
        "platform": platform.system(),
        "release": platform.release(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "timestamp": datetime.utcnow().isoformat()+"Z",
    }

def res_usage() -> Dict[str, Any]:
    try: cpu_percent = psutil.cpu_percent(interval=0.2)
    except Exception: cpu_percent = 0.0
    try: per_core = psutil.cpu_percent(interval=0.1, percpu=True)
    except Exception: per_core = []
    try: vm = psutil.virtual_memory()
    except Exception: vm = None
    try: sw = psutil.swap_memory()
    except Exception: sw = None
    disks=[]
    try:
        for p in psutil.disk_partitions(all=False):
            try:
                u=psutil.disk_usage(p.mountpoint)
                disks.append({"device":p.device,"mountpoint":p.mountpoint,"total":u.total,"used":u.used,"free":u.free,"percent":u.percent})
            except Exception: pass
    except Exception: pass
    try:
        nio = psutil.net_io_counters(pernic=False)
        net_io={"bytes_sent":getattr(nio,"bytes_sent",0),"bytes_recv":getattr(nio,"bytes_recv",0)}
    except Exception:
        net_io={"bytes_sent":0,"bytes_recv":0}
    return {
        "cpu_percent":cpu_percent,"cpu_per_core":per_core,
        "memory_total":getattr(vm,"total",0),"memory_used":getattr(vm,"used",0),
        "memory_free":getattr(vm,"available",0),"memory_percent":getattr(vm,"percent",0),
        "swap_total":getattr(sw,"total",0),"swap_used":getattr(sw,"used",0),"swap_percent":getattr(sw,"percent",0),
        "disks":disks,"net_io":net_io
    }

def net_ifaces() -> List[Dict[str, Any]]:
    out=[]
    try:
        addrs=psutil.net_if_addrs(); stats=psutil.net_if_stats()
        for name,lst in addrs.items():
            ips=[]
            for a in lst:
                fam="IPv4" if a.family==socket.AF_INET else "IPv6" if a.family==socket.AF_INET6 else None
                if fam: ips.append({"family":fam,"address":a.address,"netmask":a.netmask})
            st=stats.get(name)
            out.append({"name":name,"is_up":bool(getattr(st,"isup",False)) if st else None,
                        "speed_mbps":getattr(st,"speed",None) if st else None,"ips":ips})
    except Exception: pass
    return out

def net_conns(do_geo=False) -> List[Dict[str, Any]]:
    out=[]
    try:
        for c in psutil.net_connections(kind="inet"):
            l = f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else ""
            r = f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else ""
            pid=c.pid
            try: proc=psutil.Process(pid).name() if pid else None
            except Exception: proc=None
            g=None
            if do_geo and r:
                host,_,_=r.rpartition(":")
                g = geoip(host)
            out.append({"proto":"tcp" if c.type==socket.SOCK_STREAM else "udp","local":l,"remote":r,
                        "state":getattr(c,"status",None),"pid":pid,"process":proc,"geo":g})
    except Exception: pass
    return out

def top_by_conns(limit=20) -> List[Dict[str, Any]]:
    res=[]
    try:
        counts=defaultdict(int)
        for c in psutil.net_connections(kind="inet"):
            if c.pid: counts[c.pid]+=1
        for pid,cnt in sorted(counts.items(), key=lambda kv:-kv[1])[:limit]:
            name=cmd=None
            try:
                p=psutil.Process(pid); name=p.name(); cmd=" ".join(p.cmdline())
            except Exception: pass
            res.append({"pid":pid,"name":name,"cmd":cmd,"conns":cnt})
    except Exception: pass
    return res

def snapshot(do_geo=False) -> Dict[str, Any]:
    return {"system":sys_info(),"resources":res_usage(),"interfaces":net_ifaces(),
            "connections":net_conns(do_geo=do_geo),"top":top_by_conns()}

# ------------- charts -------------
class MiniChart(FigureCanvas):
    def __init__(self, title:str, ylim:Tuple[float,float]|None=None):
        self.fig=Figure(figsize=(4,2), dpi=100)
        super().__init__(self.fig)
        self.ax=self.fig.add_subplot(111)
        self.ax.set_title(title, fontsize=9)
        self.ax.grid(True, alpha=0.25)
        if ylim: self.ax.set_ylim(*ylim)
        (self.line,) = self.ax.plot([], [], linewidth=1.6)
        self.y=deque(maxlen=60)

    def push(self, v:float):
        self.y.append(v)
        self.line.set_data(range(len(self.y)), list(self.y))
        self.ax.set_xlim(0, max(10,len(self.y)))
        self.draw_idle()

# ------------- dialogs -------------
class PidDetailDialog(QtWidgets.QDialog):
    def __init__(self, pid:int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"PID {pid} – detail")
        self.resize(800, 600)
        lay=QtWidgets.QVBoxLayout(self)
        self.txt = QtWidgets.QPlainTextEdit(readOnly=True)
        lay.addWidget(self.txt)
        btns=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self.load(pid)

    def load(self, pid:int):
        try:
            p=psutil.Process(pid)
            info={
                "pid": pid,
                "name": p.name(),
                "exe": p.exe() if p else "",
                "cmdline": " ".join(p.cmdline()),
                "cwd": p.cwd() if p else "",
                "username": p.username(),
                "cpu_percent": p.cpu_percent(interval=0.1),
                "memory_percent": round(p.memory_percent(),2),
                "create_time": datetime.fromtimestamp(p.create_time()).isoformat(),
                "status": p.status(),
                "ppid": p.ppid(),
            }
            # open files
            files=[]
            try:
                for f in p.open_files():
                    files.append(f.path)
            except Exception: pass
            # connections by PID
            conns=[]
            try:
                for c in p.connections(kind="inet"):
                    l=f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else ""
                    r=f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else ""
                    conns.append({"proto":"tcp" if c.type==socket.SOCK_STREAM else "udp","local":l,"remote":r,"state":getattr(c,"status","")})
            except Exception: pass

            dump={"process":info,"open_files":files,"connections":conns}
            self.txt.setPlainText(json.dumps(dump, ensure_ascii=False, indent=2))
        except Exception as e:
            self.txt.setPlainText(f"Error: {e}")

# ------------- main window -------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{BRAND_NAME} – {APP_VERSION}")
        self.resize(1280, 780)
        self.setWindowIcon(self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon))
        self.settings = QtCore.QSettings("it-inspector", "gui-pro")

        # Top bar
        top=QtWidgets.QWidget(); h=QtWidgets.QHBoxLayout(top); h.setContentsMargins(8,8,8,8); h.setSpacing(6)
        self.qSearch=QtWidgets.QLineEdit(placeholderText="Tìm (IP/PID/process/state)")
        self.qPort=QtWidgets.QLineEdit(placeholderText="Port (80 hoặc 1000-2000)")
        self.qState=QtWidgets.QComboBox(); self.qState.addItems(["","ESTABLISHED","LISTEN","TIME_WAIT","CLOSE_WAIT"])
        self.qProc=QtWidgets.QLineEdit(placeholderText="Process")
        self.chkAuto=QtWidgets.QCheckBox("Tự refresh")
        self.spinSec=QtWidgets.QSpinBox(); self.spinSec.setRange(1,60)
        self.chkGeo=QtWidgets.QCheckBox("Geo/ISP")
        self.chkKill=QtWidgets.QCheckBox("Enable Kill")
        self.btnExportJson=QtWidgets.QPushButton("Export JSON")
        self.btnExportCsv =QtWidgets.QPushButton("Export CSV")
        self.btnDark=QtWidgets.QPushButton("Dark")
        for w in [self.qSearch,self.qPort,self.qState,self.qProc,self.chkAuto,self.spinSec,self.chkGeo,self.chkKill,self.btnExportJson,self.btnExportCsv,self.btnDark]:
            h.addWidget(w)

        # Charts + Ifaces
        charts=QtWidgets.QWidget(); gl=QtWidgets.QGridLayout(charts); gl.setContentsMargins(8,8,8,8)
        self.cCpu=MiniChart("CPU %",(0,100)); self.cMem=MiniChart("RAM %",(0,100))
        self.cTx=MiniChart("NET TX bytes"); self.cRx=MiniChart("NET RX bytes")
        gl.addWidget(self.cCpu,0,0); gl.addWidget(self.cMem,0,1); gl.addWidget(self.cTx,1,0); gl.addWidget(self.cRx,1,1)

        self.ifaces=QtWidgets.QTextEdit(readOnly=True)
        self.ifaces.setMinimumWidth(380)
        spl=QtWidgets.QSplitter(); spl.addWidget(charts); spl.addWidget(self.ifaces); spl.setStretchFactor(0,3); spl.setStretchFactor(1,2)

        # Tables
        self.tblTop=QtWidgets.QTableWidget(0,6)
        self.tblTop.setHorizontalHeaderLabels(["PID","Process","Conns","Cmd","Action","Detail"])
        self.tblTop.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.tblTop.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

        self.tblConn=QtWidgets.QTableWidget(0,9)
        self.tblConn.setHorizontalHeaderLabels(["Proto","Local","Remote","State","Process","PID","Geo/ISP","Action","Detail"])
        self.tblConn.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.tblConn.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

        # Layout
        central=QtWidgets.QWidget(); v=QtWidgets.QVBoxLayout(central); v.setContentsMargins(0,0,0,0)
        v.addWidget(top); v.addWidget(spl,2)
        v.addWidget(QtWidgets.QLabel("Top processes by connections")); v.addWidget(self.tblTop,1)
        v.addWidget(QtWidgets.QLabel("Active Connections")); v.addWidget(self.tblConn,2)
        self.setCentralWidget(central)

        # Tray
        self.tray=QtWidgets.QSystemTrayIcon(self.windowIcon(), self)
        menu=QtWidgets.QMenu()
        actShow=menu.addAction("Show/Hide", self.toggle_visible)
        menu.addAction("Quit", QtWidgets.QApplication.quit)
        self.tray.setContextMenu(menu); self.tray.show()
        self.tray.activated.connect(lambda r: self.toggle_visible() if r==QtWidgets.QSystemTrayIcon.Trigger else None)

        # Timer + signals
        self.timer=QtCore.QTimer(self); self.timer.timeout.connect(self.refresh)
        self.btnExportJson.clicked.connect(self.export_json)
        self.btnExportCsv.clicked.connect(self.export_csv)
        self.btnDark.clicked.connect(self.toggle_dark)
        self.qSearch.textChanged.connect(self.refresh); self.qPort.textChanged.connect(self.refresh)
        self.qProc.textChanged.connect(self.refresh); self.qState.currentIndexChanged.connect(self.refresh)
        self.spinSec.valueChanged.connect(lambda v: self.timer.setInterval(v*1000))
        self.chkAuto.toggled.connect(lambda on: self.timer.start(self.spinSec.value()*1000) if on else self.timer.stop())

        # state
        self.last_tx=0; self.last_rx=0
        self.load_settings()
        QtCore.QTimer.singleShot(200, self.refresh)

    # ---------- settings / dark ----------
    def load_settings(self):
        self.chkAuto.setChecked(self.settings.value("auto", True, type=bool))
        self.spinSec.setValue(self.settings.value("interval", 3, type=int))
        self.chkGeo.setChecked(self.settings.value("geo", False, type=bool))
        self.chkKill.setChecked(self.settings.value("kill", False, type=bool))
        if self.settings.value("dark", False, type=bool):
            self.apply_dark(True)
        self.timer.setInterval(self.spinSec.value()*1000)
        if self.chkAuto.isChecked(): self.timer.start()

    def save_settings(self):
        self.settings.setValue("auto", self.chkAuto.isChecked())
        self.settings.setValue("interval", self.spinSec.value())
        self.settings.setValue("geo", self.chkGeo.isChecked())
        self.settings.setValue("kill", self.chkKill.isChecked())
        self.settings.setValue("dark", self._dark if hasattr(self, "_dark") else False)

    def closeEvent(self, e: QtGui.QCloseEvent) -> None:
        self.save_settings()
        super().closeEvent(e)

    def apply_dark(self, on: bool):
        self._dark = on
        app = QtWidgets.QApplication.instance()
        if on:
            palette = QtGui.QPalette()
            palette.setColor(QtGui.QPalette.Window, QtGui.QColor(33,33,33))
            palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
            palette.setColor(QtGui.QPalette.Base, QtGui.QColor(18,18,18))
            palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(33,33,33))
            palette.setColor(QtGui.QPalette.ToolTipBase, QtCore.Qt.white)
            palette.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.white)
            palette.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
            palette.setColor(QtGui.QPalette.Button, QtGui.QColor(45,45,45))
            palette.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
            palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(10,132,255))
            palette.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
            app.setPalette(palette)
        else:
            app.setPalette(app.style().standardPalette())

    def toggle_dark(self):
        self.apply_dark(not getattr(self, "_dark", False))
        self.save_settings()

    def toggle_visible(self):
        self.setVisible(not self.isVisible())

    # ---------- helpers ----------
    def set_table(self, tbl:QtWidgets.QTableWidget, rows:List[List[Any]]):
        tbl.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,val in enumerate(row):
                if isinstance(val, QtWidgets.QWidget):
                    tbl.setCellWidget(r,c,val)
                else:
                    it=QtWidgets.QTableWidgetItem(str(val))
                    if isinstance(val,(int,float)):
                        it.setTextAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignVCenter)
                    tbl.setItem(r,c,it)

    def iface_text(self, interfaces:List[Dict[str,Any]]) -> str:
        parts=[]
        for ifc in interfaces:
            line=f"• {ifc.get('name')}  [{'UP' if ifc.get('is_up') else 'DOWN'}]  {ifc.get('speed_mbps') or ''} Mbps"
            ips="\n".join([f"    - {ip['family']}: {ip['address']}  {ip.get('netmask','')}" for ip in (ifc.get('ips') or [])])
            parts.append(line + ("\n"+ips if ips else ""))
        return "\n".join(parts)

    def btn_kill(self, pid:int) -> QtWidgets.QWidget:
        btn=QtWidgets.QPushButton("Kill")
        btn.setEnabled(self.chkKill.isChecked() and pid is not None)
        btn.clicked.connect(lambda: self.kill_tree(pid))
        return btn

    def btn_detail(self, pid:int) -> QtWidgets.QWidget:
        b=QtWidgets.QPushButton("Detail")
        b.clicked.connect(lambda: PidDetailDialog(pid, self).exec())
        return b

    def kill_tree(self, pid:int):
        if not self.chkKill.isChecked() or not pid: return
        ret=QtWidgets.QMessageBox.question(self,"Confirm",f"Kill cây tiến trình PID {pid} ?",QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.No)
        if ret != QtWidgets.QMessageBox.Yes: return
        try:
            p=psutil.Process(pid)
            # kill children first
            for ch in p.children(recursive=True):
                try:
                    ch.terminate()
                except Exception: pass
            gone, alive = psutil.wait_procs(p.children(recursive=True), timeout=2)
            try:
                p.terminate()
                p.wait(timeout=2)
            except psutil.TimeoutExpired:
                p.kill()
            QtWidgets.QMessageBox.information(self,"Killed",f"Đã kill cây PID {pid}")
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            QtWidgets.QMessageBox.warning(self, "Error", str(e))
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
        self.refresh()

    # ---------- export ----------
    def export_json(self):
        snap=snapshot(do_geo=self.chkGeo.isChecked())
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,"Export JSON",f"snapshot_{int(time.time())}.json","JSON (*.json)")
        if not path: return
        try:
            with open(path,"w",encoding="utf-8") as f:
                json.dump(snap,f,ensure_ascii=False,indent=2)
            QtWidgets.QMessageBox.information(self,"Export",f"Saved: {path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self,"Export error",str(e))

    def export_csv(self):
        snap=snapshot(do_geo=self.chkGeo.isChecked()); conns=snap.get("connections",[])
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,"Export CSV",f"connections_{int(time.time())}.csv","CSV (*.csv)")
        if not path: return
        try:
            import csv
            with open(path,"w",newline="",encoding="utf-8") as f:
                w=csv.writer(f); w.writerow(["proto","local","remote","state","process","pid"])
                for c in conns: w.writerow([c.get("proto"),c.get("local"),c.get("remote"),c.get("state"),c.get("process"),c.get("pid")])
            QtWidgets.QMessageBox.information(self,"Export",f"Saved: {path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self,"Export error",str(e))

    # ---------- main refresh ----------
    def refresh(self):
        snap=snapshot(do_geo=self.chkGeo.isChecked())
        r=snap["resources"]
        # charts
        self.cCpu.push(r.get("cpu_percent") or 0.0)
        self.cMem.push(r.get("memory_percent") or 0.0)
        tx=((r.get("net_io") or {}).get("bytes_sent") or 0)
        rx=((r.get("net_io") or {}).get("bytes_recv") or 0)
        self.cTx.push(max(0, tx - getattr(self,"last_tx",0)))
        self.cRx.push(max(0, rx - getattr(self,"last_rx",0)))
        self.last_tx, self.last_rx = tx, rx
        # ifaces
        self.ifaces.setPlainText(self.iface_text(snap["interfaces"]))

        # filters
        q=(self.qSearch.text() or "").lower()
        st=self.qState.currentText().strip()
        proc_q=(self.qProc.text() or "").lower()
        port_q=(self.qPort.text() or "").strip()

        def port_match(s:str)->bool:
            if not port_q: return True
            if not s: return False
            m=s.rsplit(":",1)
            if len(m)!=2: return False
            try: v=int(m[1])
            except Exception: return False
            if "-" in port_q:
                try:
                    a,b=map(int, port_q.split("-",1))
                    return a<=v<=b
                except Exception: return False
            try: return v==int(port_q)
            except Exception: return False

        # top
        rows=[]
        for p in snap["top"]:
            rows.append([p.get("pid"),p.get("name") or "",p.get("conns") or 0,(p.get("cmd") or "")[:160], self.btn_kill(p.get("pid")), self.btn_detail(p.get("pid"))])
        self.set_table(self.tblTop, rows)

        # connections
        rows=[]
        for c in snap["connections"]:
            if st and c.get("state")!=st: continue
            if proc_q and proc_q not in (c.get("process") or "").lower(): continue
            if port_q and not (port_match(c.get("local","")) or port_match(c.get("remote",""))): continue
            sline=f"{c.get('proto')} {c.get('local')} {c.get('remote') or ''} {c.get('state') or ''} {c.get('pid') or ''} {(c.get('process') or '').lower()}"
            if q and q not in sline.lower(): continue
            geo=""
            g=c.get("geo")
            if g: geo=f"{g.get('city') or ''} {g.get('regionName') or ''} {g.get('country') or ''} • {g.get('isp') or g.get('org') or ''}".strip()
            rows.append([c.get("proto"),c.get("local"),c.get("remote") or "",c.get("state") or "",c.get("process") or "",c.get("pid") or "",geo,self.btn_kill(c.get("pid") or 0), self.btn_detail(c.get("pid") or 0)])
        self.set_table(self.tblConn, rows)

# ------------- entry -------------
def main():
    app=QtWidgets.QApplication(sys.argv)
    app.setApplicationName(BRAND_NAME)
    w=MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__=="__main__":
    main()
