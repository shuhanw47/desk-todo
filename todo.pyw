# -*- coding: utf-8 -*-
"""Desk To-do —— 住在桌面小球里的 to-do list。

双击 todo.pyw 运行（依赖：Python 自带 tkinter + Pillow）。
  python todo.pyw --autostart      设为开机自启
  python todo.pyw --no-autostart   取消开机自启

用法
  单击小球              展开 / 收回（球里数字 = 剩余任务数）；拖动小球可换位置
                        小球展开时不动，靠近屏幕底部会往上展开
  底部输入框回车 / 点 +  添加；输入框左边的「inbox ▾」选分类 / 新建分类
                        也可以直接打 work: weekly report（冒号前是分类）
  按住任务拖到别的分类上松开 = 换分类；也可以右键任务 → 移到分类
  右键分类名 → 在此添加 / 重命名 / 删除
  点方框                完成 / 恢复；双击文字编辑；右键任务更多操作
  点分类名              折叠 / 展开该分类
  左下 glass 开关        半透明开 / 关；Ctrl + 滚轮 调透明度
  右键小球或顶部日期     设置：开机自启 / 清空已完成 / 退出
"""
import base64
import ctypes
import datetime
import json
import os
import re
import subprocess
import sys
import time
import uuid
import tkinter as tk
import tkinter.font as tkfont
from ctypes import c_int, c_int32, c_ssize_t, c_ubyte, c_uint, c_uint16, c_uint32, c_void_p

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageTk

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(APP_DIR, "todos.json")
STARTUP_LNK = os.path.join(
    os.environ.get("APPDATA", ""),
    r"Microsoft\Windows\Start Menu\Programs\Startup", "DeskTodo.lnk")
FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")

TABS = [("todo", "To-do"), ("pending", "Pending"),
        ("done", "Completed"), ("cancelled", "Cancelled")]
EMPTY = {"todo": "all clear", "pending": "nothing waiting",
         "done": "nothing done yet", "cancelled": "nothing cancelled"}
DEFAULT_CAT = "inbox"
DROP = "#E3EEFF"          # 拖拽时目标分类的高亮底色
DROP_FG = "#0A64D8"
# "work: xxx" / "工作：xxx"，但不把 "http://" 当分类
CAT_RE = re.compile(r"^\s*([^\s:：/]{1,20})\s*[:：](?!//)\s*(.+)$")
PLACEHOLDER = "Add a task…"

BG = "#F5F5F7"
TEXT = "#1D1D1F"
SUB = "#8E8E93"
BOX = "#AEAEB2"
HOVER = "#EBEBEF"
ACTIVE = "#FFFFFF"
TRACK = "#E5E5EA"
BORDER = "#D1D1D6"
GREEN = "#34C759"
F = "Garamond"
# 中文字体：方正静蕾简体 常规（未安装时自动回退到系统中文字体）
CN_NAMES = ("方正静蕾简体", "FZJingLeiS-R-GB", "FZJingLei-S-R-GB")
CJK_RE = re.compile(r"[⺀-鿿　-〿豈-﫿＀-￯]+")
GLASS_ALPHA = 0.72        # glass 模式面板透明度
BALL_GLASS = 150          # glass 模式小球底色不透明度（0-255）
SS = 4                    # 超采样倍数，保证圆角/圆形边缘平滑

SAMPLE = [("work", "weekly report"), ("work", "traffic analysis"),
          ("life", "get groceries"), ("life", "book flight ticket"),
          ("study", "ddl 10/31")]


# ---------------------------------------------------------------- 数据
def new_task(cat, text, status="todo"):
    return {"id": uuid.uuid4().hex[:10], "cat": cat, "text": text,
            "status": status, "created": time.time(), "updated": time.time()}


def load():
    if not os.path.exists(DATA_FILE):
        return {"tasks": [new_task(c, t) for c, t in SAMPLE],
                "categories": ["work", "life", "content", "study"],
                "settings": {}}
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d.setdefault("tasks", [])
    d.setdefault("categories", [])
    d.setdefault("settings", {})
    return d


def save(d):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DATA_FILE)


def parse(raw, default=DEFAULT_CAT):
    m = CAT_RE.match(raw)
    if m:
        return m.group(1).lower(), m.group(2).strip()
    return default, raw.strip()


def set_autostart(on):
    if not on:
        try:
            os.remove(STARTUP_LNK)
        except OSError:
            pass
        return
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    q = lambda s: s.replace("'", "''")
    script = (
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(STARTUP_LNK)}');"
        f"$s.TargetPath='{q(pyw)}';"
        f"$s.Arguments='\"{q(os.path.abspath(__file__))}\"';"
        f"$s.WorkingDirectory='{q(APP_DIR)}';$s.Save()")
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", enc],
                   creationflags=0x08000000)


# ---------------------------------------------------------------- 绘图
def rgba(h, a=255):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a


def finish(im, w, h):
    return im.resize((w, h), Image.LANCZOS)


def shadow_layer(size, box, radius, alpha, blur, dy):
    sh = Image.new("RGBA", size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + dy, x1, y1 + dy), radius,
                                         fill=(0, 0, 0, alpha))
    return sh.filter(ImageFilter.GaussianBlur(blur))


def ui_font(size, symbol=False):
    """苹果风数字：Win11 的 Segoe UI Variable（最接近 SF Pro）。"""
    names = ["seguisym.ttf"] if symbol else ["SegUIVar.ttf", "seguisb.ttf", "segoeui.ttf"]
    for name in names + ["arial.ttf"]:
        try:
            f = ImageFont.truetype(os.path.join(FONT_DIR, name), size)
        except OSError:
            continue
        if name == "SegUIVar.ttf":
            try:
                vs = f.get_variation_names()
                pick = next((v for v in vs if v in (b"Display Semibold", "Display Semibold")), None) \
                    or next((v for v in vs if b"Semibold" in (v if isinstance(v, bytes) else v.encode())), None)
                if pick:
                    f.set_variation_by_name(pick)
            except Exception:
                pass
        return f
    return ImageFont.load_default()


# ---- Windows 分层窗口：让小球拥有逐像素透明（抗锯齿边缘 + 柔和阴影）
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", c_uint32), ("biWidth", c_int32), ("biHeight", c_int32),
                ("biPlanes", c_uint16), ("biBitCount", c_uint16),
                ("biCompression", c_uint32), ("biSizeImage", c_uint32),
                ("biXPelsPerMeter", c_int32), ("biYPelsPerMeter", c_int32),
                ("biClrUsed", c_uint32), ("biClrImportant", c_uint32)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", c_ubyte), ("BlendFlags", c_ubyte),
                ("SourceConstantAlpha", c_ubyte), ("AlphaFormat", c_ubyte)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", c_int32), ("cy", c_int32)]


class POINT(ctypes.Structure):
    _fields_ = [("x", c_int32), ("y", c_int32)]


def _win32():
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    u.GetDC.restype = c_void_p
    u.GetDC.argtypes = [c_void_p]
    u.ReleaseDC.argtypes = [c_void_p, c_void_p]
    u.GetParent.restype = c_void_p
    u.GetParent.argtypes = [c_void_p]
    u.GetWindowLongPtrW.restype = c_ssize_t
    u.GetWindowLongPtrW.argtypes = [c_void_p, c_int]
    u.SetWindowLongPtrW.argtypes = [c_void_p, c_int, c_ssize_t]
    u.UpdateLayeredWindow.argtypes = [c_void_p, c_void_p, c_void_p, c_void_p, c_void_p,
                                      c_void_p, c_uint32, c_void_p, c_uint32]
    g.CreateCompatibleDC.restype = c_void_p
    g.CreateCompatibleDC.argtypes = [c_void_p]
    g.CreateDIBSection.restype = c_void_p
    g.CreateDIBSection.argtypes = [c_void_p, c_void_p, c_uint, ctypes.POINTER(c_void_p),
                                   c_void_p, c_uint32]
    g.SelectObject.restype = c_void_p
    g.SelectObject.argtypes = [c_void_p, c_void_p]
    g.DeleteObject.argtypes = [c_void_p]
    g.DeleteDC.argtypes = [c_void_p]
    return u, g


def make_layered(hwnd):
    u, _ = _win32()
    ex = u.GetWindowLongPtrW(hwnd, -20)
    u.SetWindowLongPtrW(hwnd, -20, ex | 0x80000 | 0x80)  # WS_EX_LAYERED | WS_EX_TOOLWINDOW
    # 改了扩展样式要 SWP_FRAMECHANGED 才真正生效，否则刚启动时鼠标点击会被吞
    u.SetWindowPos.argtypes = [c_void_p, c_void_p, c_int, c_int, c_int, c_int, c_uint]
    u.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x37)  # NOMOVE|NOSIZE|NOZORDER|NOACTIVATE|FRAMECHANGED


def paint_layered(hwnd, img, pos=None):
    """把 RGBA 图像整张贴到分层窗口上（alpha 预乘）；pos 给定时同时移动窗口。"""
    u, g = _win32()
    r, gr, b, a = img.split()
    pm = Image.merge("RGBA", (ImageChops.multiply(r, a), ImageChops.multiply(gr, a),
                              ImageChops.multiply(b, a), a))
    w, h = img.size
    data = pm.tobytes("raw", "BGRA")
    bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    screen = u.GetDC(None)
    mem = g.CreateCompatibleDC(screen)
    bits = c_void_p()
    bmp = g.CreateDIBSection(screen, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    ctypes.memmove(bits, data, len(data))
    old = g.SelectObject(mem, bmp)
    size, src = SIZE(w, h), POINT(0, 0)
    blend = BLENDFUNCTION(0, 0, 255, 1)
    dst = ctypes.byref(POINT(*pos)) if pos else None
    u.UpdateLayeredWindow(hwnd, screen, dst, ctypes.byref(size), mem,
                          ctypes.byref(src), 0, ctypes.byref(blend), 2)
    g.SelectObject(mem, old)
    g.DeleteObject(bmp)
    g.DeleteDC(mem)
    u.ReleaseDC(None, screen)


# ---- 多屏幕
class RECT(ctypes.Structure):
    _fields_ = [("left", c_int32), ("top", c_int32), ("right", c_int32), ("bottom", c_int32)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", c_uint32), ("rcMonitor", RECT), ("rcWork", RECT),
                ("dwFlags", c_uint32)]


def _mon_info(hmon):
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    ctypes.windll.user32.GetMonitorInfoW(c_void_p(hmon), ctypes.byref(mi))
    w, r = mi.rcWork, mi.rcMonitor
    return {"work": (w.left, w.top, w.right, w.bottom),
            "size": (r.right - r.left, r.bottom - r.top),
            "primary": bool(mi.dwFlags & 1)}


def monitors():
    """所有屏幕（主屏在前，其余按从左到右）。"""
    found = []
    proc = ctypes.WINFUNCTYPE(c_int, c_void_p, c_void_p, ctypes.POINTER(RECT), c_void_p)
    cb = proc(lambda h, dc, rc, lp: found.append(_mon_info(h)) or 1)
    ctypes.windll.user32.EnumDisplayMonitors(None, None, cb, None)
    return sorted(found, key=lambda m: (not m["primary"], m["work"][0], m["work"][1]))


def monitor_at(x, y):
    """离点 (x, y) 最近的屏幕。"""
    u = ctypes.windll.user32
    u.MonitorFromPoint.restype = c_void_p
    u.MonitorFromPoint.argtypes = [POINT, c_uint32]
    return _mon_info(u.MonitorFromPoint(POINT(int(x), int(y)), 2))


# ---------------------------------------------------------------- 界面
class App:
    def __init__(self):
        try:  # 高分屏不发糊
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        self.d = load()
        st = self.st = self.d["settings"]
        for k in ("x", "y", "w", "h", "collapsed"):  # 旧版本的设置
            st.pop(k, None)
        if st.get("v", 1) < 2:                       # 旧版透明度偏不透，升级时调透
            st["alpha"] = GLASS_ALPHA
            st["v"] = 2
        st.setdefault("alpha", GLASS_ALPHA)
        st.setdefault("glass", True)
        st.setdefault("folded", [])
        st.setdefault("add_cat", DEFAULT_CAT)   # 新任务默认放进的分类
        self.tab = "todo"
        self.mode = "ball"          # ball / pinned
        self.editing = None
        self.menu_open = False
        self._out = None
        self._ball_key = None
        self.rows = {}
        self.emode = None           # 输入框临时用途：("newcat", 任务或None) / ("rename", 分类)
        self.imgs = {}              # PhotoImage 缓存（防止被回收）

        self.root = root = tk.Tk()
        root.withdraw()
        root.title("Desk To-do")
        self.s = S = root.winfo_fpixels("1i") / 96
        self.D = int(48 * S)        # 小球直径
        self.P = int(10 * S)        # 小球阴影留白
        self.BW = self.D + 2 * self.P
        self.M = int(10 * S)
        self.R = int(6 * S)         # 窗口边缘可拖拽缩放的宽度
        self.fn = {k: tkfont.Font(root, family=F, size=size, **opt) for k, (size, opt) in {
            "date": (11, {"slant": "italic"}), "small": (10, {"slant": "italic"}),
            "tab": (11, {}), "tab_on": (11, {"weight": "bold"}),
            "cat": (12, {"weight": "bold"}), "task": (12, {}),
            "task_x": (12, {"overstrike": 1}), "empty": (12, {"slant": "italic"}),
            "plus": (15, {})}.items()}
        fams = set(tkfont.families(root))
        self.CN = next((c for c in CN_NAMES if c in fams), None) or \
            next((f for f in fams if "静蕾" in f or "jinglei" in f.lower()), None)
        cn = self.CN or "Microsoft YaHei"
        self.fn["cn"] = tkfont.Font(root, family=cn, size=12)
        self.fn["cn_x"] = tkfont.Font(root, family=cn, size=12, overstrike=1)
        self.fn["cn_cat"] = tkfont.Font(root, family=cn, size=12)
        self.base_sizes = {k: f.cget("size") for k, f in self.fn.items()}
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=BORDER)
        st.setdefault("pw", int(320 * S))
        st.setdefault("ph", int(470 * S))
        if "bx" not in st:
            l, t, r, b = monitors()[0]["work"]
            st["bx"], st["by"] = r - self.BW - int(20 * S), t + int(60 * S)
        st["bx"], st["by"] = self.clamp_ball(st["bx"], st["by"])

        self.apply_zoom(build=True)
        self.build_panel()
        self.build_ball()
        self.apply_glass()
        self.tick()
        self.render()
        # 小球刚映射到屏幕时第一次贴图可能不接收鼠标，映射后再贴一次
        root.after(300, self.repaint_ball)

    def repaint_ball(self):
        self._ball_key = None
        self.draw_ball()

    # ---------------------------------------------------- 缩放字号
    def zoom(self):
        """窗口越大字越大一点：按面积的 0.3 次方，限制在 0.9–1.5 倍。"""
        S = self.s
        area = self.st["pw"] * self.st["ph"] / (320 * 470 * S * S)
        return min(1.5, max(0.9, area ** 0.3))

    def apply_zoom(self, build=False):
        z = self.zoom()
        if not build and abs(z - getattr(self, "_z", 0)) < 0.02:
            return
        self._z = z
        for k, f in self.fn.items():
            f.configure(size=max(8, round(self.base_sizes[k] * z)))
        self.TH = int(30 * self.s * z)
        self.EH = int(30 * self.s * z)
        self.CB = int(15 * self.s * z)
        if not build:
            self.tabs_c.config(height=self.TH)
            self.ec.config(height=self.EH)
            self.draw_tabs()
            self.draw_entry()

    # ---------------------------------------------------- 搭界面
    def build_panel(self):
        root, S = self.root, self.s
        # 外圈 R 像素是缩放边框：像 Windows 窗口一样拖任意边/角改变大小
        self.edge = edge = tk.Frame(root, bg=BG)
        edge.pack(fill="both", expand=True, padx=1, pady=1)
        edge.bind("<Motion>", self.edge_cursor)
        edge.bind("<ButtonPress-1>", self.resize_start)
        edge.bind("<B1-Motion>", self.resize_move)
        edge.bind("<ButtonRelease-1>", self.resize_end)
        box = tk.Frame(edge, bg=BG)
        box.pack(fill="both", expand=True, padx=self.R, pady=self.R)

        self.head = head = tk.Frame(box, bg=BG, height=self.M + self.D + self.M // 2 - self.R)
        head.pack_propagate(False)
        self.date = tk.Label(head, bg=BG, fg=SUB, font=self.fn["date"])
        self.date.place(relx=0.5, y=self.M + self.D // 2 - self.R, anchor="center")
        for w in (head, self.date):
            w.bind("<ButtonPress-1>", self.drag_start)
            w.bind("<B1-Motion>", self.drag_move)
            w.bind("<ButtonRelease-1>", lambda e: save(self.d))
            w.bind("<Button-3>", self.settings_menu)

        # 圆润的分段选择器
        self.tabs_c = tk.Canvas(box, height=self.TH, bg=BG, highlightthickness=0,
                                cursor="hand2")
        self.tabs_c.bind("<Configure>", lambda e: self.draw_tabs())
        self.tabs_c.bind("<Button-1>", self.tab_click)

        self.body = tk.Frame(box, bg=BG)
        self.canvas = tk.Canvas(self.body, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", self.on_resize)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        root.bind_all("<MouseWheel>", self.on_wheel)

        self.bottom = bottom = tk.Frame(box, bg=BG)
        self.switch_l = tk.Label(bottom, bg=BG, cursor="hand2", bd=0)
        self.switch_l.pack(side="left")
        glass = tk.Label(bottom, text="glass", font=self.fn["small"], fg=SUB,
                         bg=BG, cursor="hand2")
        glass.pack(side="left", padx=(4, 8))
        for w in (self.switch_l, glass):
            w.bind("<Button-1>", lambda e: self.toggle_glass())

        # 胶囊形输入框
        self.ec = tk.Canvas(bottom, height=self.EH, bg=BG, highlightthickness=0)
        self.ec.pack(side="left", fill="x", expand=True)
        self.entry = tk.Entry(self.ec, font=self.fn["task"], bg=ACTIVE, fg=TEXT, relief="flat",
                              bd=0, insertbackground=TEXT)
        self.ec_bg = self.ec.create_image(0, 0, anchor="nw")
        self.ec_entry = self.ec.create_window(self.EH // 2, self.EH // 2, anchor="w",
                                              window=self.entry)
        self.ec_chip = self.ec.create_text(0, self.EH // 2, anchor="w", fill=SUB,
                                           tags="chip")
        self.ec_div = self.ec.create_line(0, 0, 0, 0, fill=BORDER)
        self.ec.tag_bind("chip", "<Button-1>", self.cat_menu)
        self.ec.tag_bind("chip", "<Enter>", lambda e: self.ec.config(cursor="hand2"))
        self.ec.tag_bind("chip", "<Leave>", lambda e: self.ec.config(cursor=""))
        self.ec_plus = self.ec.create_text(0, self.EH // 2 - 1, text="+", font=self.fn["plus"],
                                           fill=SUB, tags="plus")
        self.ec.tag_bind("plus", "<Button-1>", self.add)
        self.ec.bind("<Configure>", lambda e: self.draw_entry())
        self.placeholder(True)
        self.entry.bind("<Button-1>", self.focus_entry)
        self.entry.bind("<FocusIn>", lambda e: self.placeholder(False))
        self.entry.bind("<FocusOut>", lambda e: (self.end_emode(), self.placeholder(True)))
        self.entry.bind("<Return>", self.add)
        self.entry.bind("<KeyRelease>", lambda e: self.cn_font_for(self.entry))
        self.entry.bind("<Escape>", lambda e: self.root.focus() if self.emode else self.hide())

        # 展开时的小球画在面板里面，和面板是同一个窗口 → 永远不会错位
        self.ball_in = tk.Label(root, bd=0, highlightthickness=0, bg=BG, cursor="hand2")
        self.ball_in.bind("<ButtonPress-1>", self.ball_press)
        self.ball_in.bind("<B1-Motion>", self.ball_move)
        self.ball_in.bind("<ButtonRelease-1>", self.ball_release)
        self.ball_in.bind("<Button-3>", self.settings_menu)

    def build_ball(self):
        b = self.ball = tk.Toplevel(self.root)
        b.overrideredirect(True)
        b.attributes("-topmost", True)
        self.bc = tk.Canvas(b, width=self.BW, height=self.BW, highlightthickness=0,
                            cursor="hand2")
        self.bc.pack()
        b.geometry(f"{self.BW}x{self.BW}+{self.st['bx']}+{self.st['by']}")
        b.update()
        self.ball_hwnd = ctypes.windll.user32.GetParent(b.winfo_id())
        make_layered(self.ball_hwnd)
        self.bc.bind("<ButtonPress-1>", self.ball_press)
        self.bc.bind("<B1-Motion>", self.ball_move)
        self.bc.bind("<ButtonRelease-1>", self.ball_release)
        self.bc.bind("<Button-3>", self.settings_menu)

    # ---------------------------------------------------- 绘制
    def remaining(self):
        return sum(1 for t in self.d["tasks"] if t["status"] in ("todo", "pending"))

    def draw_ball(self):
        n, pinned, glass = self.remaining(), self.mode == "pinned", self.st["glass"]
        key = (n, pinned, glass, self.mode == "ball", getattr(self, "right", True),
               getattr(self, "up", False))
        if key == self._ball_key:
            return
        self._ball_key = key
        D, P, W = self.D * SS, self.P * SS, self.BW * SS
        im = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        im.alpha_composite(shadow_layer(im.size, (P, P, P + D, P + D), D // 2,
                                        90, P * 0.45, int(2 * self.s * SS)))
        # 主体：竖向渐变 + 圆形遮罩
        top, bot = ((72, 72, 76), (28, 28, 30)) if pinned else ((255, 255, 255), (232, 232, 237))
        grad = Image.linear_gradient("L").resize((D, D))
        body = Image.composite(Image.new("RGB", (D, D), bot), Image.new("RGB", (D, D), top), grad)
        mask = Image.new("L", (D, D), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, D - 1, D - 1),
                                     fill=BALL_GLASS + 40 if glass and pinned else
                                     BALL_GLASS if glass else 250)
        body.putalpha(mask)
        im.alpha_composite(body, (P, P))
        d = ImageDraw.Draw(im)
        hair = max(SS, int(0.8 * self.s * SS))
        d.ellipse((P, P, P + D - 1, P + D - 1), width=hair,
                  outline=(255, 255, 255, 60) if pinned else (0, 0, 0, 34))
        # 顶部高光
        hl = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(hl).ellipse((P + hair * 2, P + hair, P + D - hair * 2, P + D * 0.55),
                                   fill=(255, 255, 255, 40 if pinned else 70))
        im.alpha_composite(hl.filter(ImageFilter.GaussianBlur(D * 0.05)))
        # 数字
        txt = str(n) if n else "✓"
        size = D * (0.46 if len(txt) == 1 else 0.40 if len(txt) == 2 else 0.30)
        font = ui_font(int(size), symbol=not n)
        tl = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(tl).text((W / 2, W / 2), txt, font=font, anchor="mm",
                                fill=(255, 255, 255, 255) if pinned else rgba(TEXT))
        im.alpha_composite(tl)
        im = finish(im, self.BW, self.BW)
        self._ball_im = im
        self.paint_ball_window()
        if self.mode == "ball":
            return
        # 嵌入面板：铺在面板底色上，裁掉贴着面板边框的 2px，避免盖住边框线
        flat = Image.new("RGBA", im.size, rgba(BG))
        flat.alpha_composite(im)
        c = 2
        up = getattr(self, "up", False)
        y0, y1 = (0, self.BW - c) if up else (c, self.BW)
        flat = flat.crop((0, y0, self.BW - c, y1) if self.right else (c, y0, self.BW, y1))
        self.imgs["ball_in"] = ImageTk.PhotoImage(flat)
        self.ball_in.config(image=self.imgs["ball_in"])

    def paint_ball_window(self):
        """收起时贴小球；展开时贴全透明图（鼠标穿透到面板里的小球）。位置一并更新。"""
        im = self._ball_im if self.mode == "ball" else             Image.new("RGBA", (self.BW, self.BW), (0, 0, 0, 0))
        paint_layered(self.ball_hwnd, im, (self.st["bx"], self.st["by"]))

    def draw_tabs(self):
        c, S = self.tabs_c, self.s
        w, h = c.winfo_width(), self.TH
        if w < 20:
            return
        n, idx = len(TABS), [k for k, _ in TABS].index(self.tab)
        W, H = w * SS, h * SS
        im = Image.new("RGBA", (W, H), rgba(BG))
        ImageDraw.Draw(im).rounded_rectangle((0, 0, W - 1, H - 1), H // 2, fill=rgba(TRACK))
        pad = int(2.5 * S * SS)
        seg = (W - 2 * pad) / n
        box = (pad + idx * seg, pad, pad + (idx + 1) * seg, H - pad)
        r = (H - 2 * pad) // 2
        im.alpha_composite(shadow_layer(im.size, box, r, 45, 2.5 * S * SS, int(S * SS)))
        ImageDraw.Draw(im).rounded_rectangle(box, r, fill=rgba(ACTIVE))
        self.imgs["tabs"] = ImageTk.PhotoImage(finish(im, w, h))
        c.delete("all")
        c.create_image(0, 0, image=self.imgs["tabs"], anchor="nw")
        for i, (key, label) in enumerate(TABS):
            on = i == idx
            c.create_text((i + 0.5) * w / n, h / 2, text=label, fill=TEXT if on else SUB,
                          font=self.fn["tab_on" if on else "tab"])

    def tab_click(self, e):
        i = int(e.x / max(1, self.tabs_c.winfo_width()) * len(TABS))
        self.switch(TABS[min(max(i, 0), len(TABS) - 1)][0])

    def draw_entry(self):
        w, h = self.ec.winfo_width(), self.EH
        if w < 20:
            return
        W, H = w * SS, h * SS
        im = Image.new("RGBA", (W, H), rgba(BG))
        ImageDraw.Draw(im).rounded_rectangle((0, 0, W - 1, H - 1), H // 2, fill=rgba(ACTIVE),
                                             outline=rgba(BORDER), width=SS)
        self.imgs["entry"] = ImageTk.PhotoImage(finish(im, w, h))
        self.ec.itemconfigure(self.ec_bg, image=self.imgs["entry"])
        # [分类 ▾] | 输入框 … +
        chip = self.chip_text()
        f = self.fn["cn"] if self.CN and CJK_RE.search(chip) else self.fn["tab"]
        x0 = h * 0.5
        self.ec.itemconfigure(self.ec_chip, text=chip, font=f,
                              fill=TEXT if self.emode else SUB)
        self.ec.coords(self.ec_chip, x0, h / 2)
        xd = x0 + f.measure(chip) + 7 * self.s
        self.ec.coords(self.ec_div, xd, h * 0.28, xd, h * 0.72)
        xe = xd + 7 * self.s
        self.ec.coords(self.ec_entry, xe, h // 2)
        self.ec.itemconfigure(self.ec_entry, width=max(20, int(w - xe - h * 0.9)))
        self.ec.coords(self.ec_plus, w - h * 0.55, h / 2 - 1)

    def switch_img(self, on):
        key = ("switch", on)
        if key not in self.imgs:
            S = self.s
            w, h = int(32 * S), int(19 * S)
            W, H = w * SS, h * SS
            im = Image.new("RGBA", (W, H), rgba(BG))
            ImageDraw.Draw(im).rounded_rectangle((0, 0, W - 1, H - 1), H // 2,
                                                 fill=rgba(GREEN if on else TRACK))
            k = int(2 * S * SS)
            x0 = W - H + k if on else k
            knob = (x0, k, x0 + H - 2 * k, H - k)
            im.alpha_composite(shadow_layer(im.size, knob, H, 60, S * SS, int(S * SS)))
            ImageDraw.Draw(im).ellipse(knob, fill=rgba(ACTIVE))
            self.imgs[key] = ImageTk.PhotoImage(finish(im, w, h))
        return self.imgs[key]

    def cb_img(self, status, bg):
        key = ("cb", status, bg, self.CB)
        if key not in self.imgs:
            n, N = self.CB, self.CB * SS
            im = Image.new("RGBA", (N, N), rgba(bg))
            d = ImageDraw.Draw(im)
            r, lw = int(N * 0.26), max(SS, int(1.3 * self.s * SS))
            box = (lw // 2, lw // 2, N - 1 - lw // 2, N - 1 - lw // 2)
            if status == "done":
                d.rounded_rectangle(box, r, fill=rgba(TEXT))
                d.line([(N * .27, N * .53), (N * .44, N * .69), (N * .74, N * .33)],
                       fill=rgba(ACTIVE), width=int(lw * 1.4), joint="curve")
            else:
                d.rounded_rectangle(box, r, outline=rgba(BOX), width=lw)
                if status == "pending":
                    d.line([(N * .3, N / 2), (N * .7, N / 2)], fill=rgba(SUB), width=lw)
                elif status == "cancelled":
                    d.line([(N * .32, N * .32), (N * .68, N * .68)], fill=rgba(BOX), width=lw)
                    d.line([(N * .68, N * .32), (N * .32, N * .68)], fill=rgba(BOX), width=lw)
            self.imgs[key] = ImageTk.PhotoImage(finish(im, n, n))
        return self.imgs[key]

    # ---------------------------------------------------- 显示 / 隐藏
    def place_panel(self):
        st = self.st
        pw, ph, bx, by = st["pw"], st["ph"], st["bx"], st["by"]
        P, D, M = self.P, self.D, self.M
        l, t, r, b = monitor_at(bx + self.BW / 2, by + self.BW / 2)["work"]
        # 小球永远不动：球在右半屏 → 面板往左展开；下方放不下 → 往上展开
        self.right = bx + self.BW / 2 > (l + r) / 2
        down_top, up_bottom = by + P - M, by + P + D + M
        room_down, room_up = b - down_top, up_bottom - t
        self.up = room_down < ph and room_up > room_down
        ph = min(ph, room_up if self.up else room_down)   # 两边都放不下时临时变矮
        x = bx + P + D + M - pw if self.right else bx + P - M
        y = up_bottom - ph if self.up else down_top
        self.root.geometry(f"{pw}x{ph}+{x}+{y}")
        self.relayout()
        c = 2
        bx_in = -(M + D + P) if self.right else M - P + c
        if self.up:
            self.ball_in.place(relx=0 if not self.right else 1, rely=1, x=bx_in,
                               y=-(M + D + P), anchor="nw")
        else:
            self.ball_in.place(relx=0 if not self.right else 1, rely=0, x=bx_in,
                               y=M - P + c, anchor="nw")
        self.ball_in.lift()
        self._ball_key = None

    def relayout(self):
        """往下展开：日期栏在顶；往上展开：整个布局倒过来，日期栏和小球在底。"""
        if getattr(self, "_layout", None) == self.up:
            return
        self._layout = self.up
        for w in (self.head, self.tabs_c, self.body, self.bottom):
            w.pack_forget()
        if self.up:
            self.tabs_c.pack(fill="x", padx=12, pady=(10, 8))
            self.body.pack(fill="both", expand=True)
            self.bottom.pack(fill="x", padx=12, pady=(4, 2))
            self.head.pack(fill="x")
            self.date.place_configure(y=(self.M + self.D) // 2)
        else:
            self.head.pack(fill="x")
            self.tabs_c.pack(fill="x", padx=12, pady=(0, 8))
            self.body.pack(fill="both", expand=True)
            self.bottom.pack(fill="x", padx=12, pady=(4, 14))
            self.date.place_configure(y=self.M + self.D // 2 - self.R)

    def show(self, mode):
        was_hidden = self.mode == "ball"
        self.mode = mode
        if was_hidden:
            self.place_panel()
            self.draw_ball()
            self.root.deiconify()
            self.round_corners()
            self.render()
            self.root.update_idletasks()
        self._ball_key = None
        self.draw_ball()

    def hide(self):
        self.mode = "ball"
        self.editing = None
        self.ball.geometry(f"+{self.st['bx']}+{self.st['by']}")
        self.ball.lift()
        self.repaint_ball()
        self.root.withdraw()
        # 小球重新映射后第一次贴图可能不接收鼠标，稍后再贴一次（同启动时）
        self.root.after(150, self.repaint_ball)

    def round_corners(self):
        try:  # Win11 圆角
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            pref = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                c_void_p(hwnd), 33, ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            pass

    def apply_glass(self):
        on = self.st["glass"]
        self.root.attributes("-alpha", self.st["alpha"] if on else 1.0)
        self.switch_l.config(image=self.switch_img(on))
        self.draw_ball()

    def toggle_glass(self):
        self.st["glass"] = not self.st["glass"]
        self.apply_glass()
        save(self.d)

    def set_alpha(self, a):
        self.st["alpha"] = round(min(1.0, max(0.3, a)), 2)
        self.st["glass"] = True
        self.apply_glass()
        save(self.d)

    # ---------------------------------------------------- 渲染
    def tick(self):
        now = datetime.datetime.now()
        self.date.config(text=f"{now:%B} {now.day}, {now:%A}")
        self.root.after(30_000, self.tick)

    def render(self):
        self.editing = None
        self.rows = {}
        self.headers = {}           # 分类 → 标题行里的控件（拖拽时高亮、定位）
        for w in self.inner.winfo_children():
            w.destroy()
        tasks = [t for t in self.d["tasks"] if t["status"] == self.tab]
        wrap = max(self.canvas.winfo_width() - int(70 * self.s), 120)
        if not tasks:
            tk.Label(self.inner, text=EMPTY[self.tab], bg=BG, fg=SUB,
                     font=self.fn["empty"]).pack(anchor="w", padx=18, pady=14)
        groups = {}
        for t in tasks:
            groups.setdefault(t["cat"], []).append(t)
        cats = self.d["categories"]
        order = [c for c in cats if c in groups] + [c for c in groups if c not in cats]
        if self.tab == "todo":      # 空分类也显示，方便直接拖任务进去
            order += [c for c in cats if c not in groups and c != DEFAULT_CAT]
        for cat in order:
            folded = cat in self.st["folded"]
            hrow = tk.Frame(self.inner, bg=BG, cursor="hand2")
            hrow.pack(fill="x", padx=14, pady=(8, 2))
            arrow = tk.Label(hrow, text="▸" if folded else "▾", bg=BG, fg=SUB,
                             font=("Segoe UI Symbol", 8))
            arrow.pack(side="left")
            n = len(groups.get(cat, []))
            name, name_t = self.mixed(hrow, cat + (f"  {n}" if folded and n else ""),
                                      "cat", TEXT if n else SUB, BG, wrap=False)
            name.pack(side="left", padx=(4, 0))
            self.headers[cat] = (hrow, arrow, name, name_t)
            for w in (hrow, arrow, name, name_t):
                w.bind("<Button-1>", lambda e, c=cat: self.toggle_fold(c))
                w.bind("<Button-3>", lambda e, c=cat: self.cat_header_menu(e, c))
            if not folded:
                for t in groups.get(cat, []):
                    self.task_row(t, wrap)
        tk.Frame(self.inner, bg=BG, height=8).pack()
        self.draw_tabs()
        self.inner.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.draw_ball()

    def task_row(self, t, wrap):
        closed = t["status"] in ("done", "cancelled")
        row = tk.Frame(self.inner, bg=BG)
        row.pack(fill="x", padx=(int(20 * self.s), 10), pady=1)
        cb = tk.Label(row, image=self.cb_img(t["status"], BG), bg=BG, bd=0, cursor="hand2")
        cb.pack(side="left", anchor="n", pady=int(5 * self.s))
        lbl, txt = self.mixed(row, t["text"], "task_x" if closed else "task",
                              SUB if closed else TEXT, BG)
        lbl.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.rows[t["id"]] = (row, lbl)

        def paint(bg):
            for w in (row, lbl):
                w.config(bg=bg)
            txt.config(bg=bg, selectbackground=bg, inactiveselectbackground=bg)
            cb.config(bg=bg, image=self.cb_img(t["status"], bg))
        for w in (row, cb, lbl, txt):
            w.bind("<Enter>", lambda e: paint(HOVER))
            w.bind("<Leave>", lambda e: paint(BG))
            w.bind("<Button-3>", lambda e: self.task_menu(e, t))
        cb.bind("<Button-1>", lambda e: self.set_status(t, "todo" if closed else "done"))
        for w in (lbl, txt):
            w.bind("<Double-Button-1>", lambda e: self.edit(t))
        for w in (row, lbl, txt):   # 按住任务拖到别的分类上松开 = 换分类
            w.bind("<ButtonPress-1>", lambda e: self.drag_task_start(e, t))
            w.bind("<B1-Motion>", self.drag_task_move)
            w.bind("<ButtonRelease-1>", self.drag_task_end)

    # ---------------------------------------------------- 拖拽换分类
    def drag_task_start(self, e, t):
        self._drag = {"t": t, "x": e.x_root, "y": e.y_root, "on": False, "target": None}

    def drag_task_move(self, e):
        """超过 6px 才算拖拽；之后改为轮询鼠标位置和左键状态
        （拖拽中弹出的小标签窗口会打断 Tk 的鼠标捕获，B1-Motion 不可靠）。"""
        d = getattr(self, "_drag", None)
        if not d or d["on"]:
            return
        if abs(e.x_root - d["x"]) + abs(e.y_root - d["y"]) < 6:
            return
        d["on"] = True
        g = self.ghost = tk.Toplevel(self.root)
        g.overrideredirect(True)
        g.attributes("-topmost", True)
        g.attributes("-alpha", 0.92)
        text = d["t"]["text"]
        text = text if len(text) <= 36 else text[:35] + "…"
        tk.Label(g, text=text, bg=ACTIVE, fg=TEXT, padx=10, pady=3,
                 font=self.fn["cn" if self.CN and CJK_RE.search(text) else "task"],
                 highlightthickness=1, highlightbackground=BORDER).pack()
        self.root.config(cursor="fleur")
        self.drag_poll()

    def drag_poll(self):
        d = getattr(self, "_drag", None)
        if not d or not d["on"]:
            return
        x, y = self.root.winfo_pointerxy()
        if not ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000:   # 左键已松开
            return self.drag_task_end()
        self.ghost.geometry(f"+{x + 14}+{y + 8}")
        # 拖到列表上下边缘时自动滚动
        cy, ch = self.canvas.winfo_rooty(), self.canvas.winfo_height()
        if self.inner.winfo_height() > ch:
            if cy <= y < cy + 24:
                self.canvas.yview_scroll(-1, "units")
            elif cy + ch - 24 < y <= cy + ch:
                self.canvas.yview_scroll(1, "units")
        self.set_drop_target(self.cat_at(x, y))
        self.root.after(16, self.drag_poll)

    def drag_task_end(self, e=None):
        d = getattr(self, "_drag", None)
        if not d or not d["on"]:
            self._drag = None
            return
        x, y = self.root.winfo_pointerxy()
        self.set_drop_target(self.cat_at(x, y))
        target = d["target"]
        self._drag = None
        self.ghost.destroy()
        self.root.config(cursor="")
        self.set_drop_target(None)
        if target and target != d["t"]["cat"]:
            self.move_to_cat(d["t"], target)

    def cat_at(self, x, y):
        """指针所在的分类：落在哪个分类标题以下、下一个标题以上，就算哪个分类。"""
        c = self.canvas
        if not (c.winfo_rootx() <= x < c.winfo_rootx() + c.winfo_width() and
                c.winfo_rooty() <= y < c.winfo_rooty() + c.winfo_height()):
            return None
        best = None
        for cat, ws in sorted(self.headers.items(), key=lambda kv: kv[1][0].winfo_rooty()):
            if ws[0].winfo_rooty() - 6 <= y:
                best = cat
        return best or next(iter(self.headers), None)

    def set_drop_target(self, cat):
        d = getattr(self, "_drag", None)
        old = getattr(self, "_drop_old", None)
        if old == cat:
            return
        for c, on in ((old, False), (cat, True)):
            if c in self.headers:
                hrow, arrow, name, name_t = self.headers[c]
                bg = DROP if on else BG
                for w in (hrow, arrow, name):
                    w.config(bg=bg)
                name_t.config(bg=bg, selectbackground=bg, inactiveselectbackground=bg,
                              fg=DROP_FG if on else TEXT)
        if d:
            d["target"] = cat
        self._drop_old = cat

    def mixed(self, parent, text, key, fg, bg, wrap=True):
        """中英混排：英文用 Garamond，中文段落打 cn 标签用方正静蕾。
        返回 (外框, Text)；外框按像素高度自适应，wrap=False 时宽度贴合文字。"""
        cn_key = {"task_x": "cn_x", "cat": "cn_cat"}.get(key, "cn")
        runs, pos = [], 0
        for m in CJK_RE.finditer(text):
            runs += [(text[pos:m.start()], False), (m.group(), True)]
            pos = m.end()
        runs.append((text[pos:], False))
        runs = [r for r in runs if r[0]]
        lat, cjk = self.fn[key], self.fn[cn_key]
        line_h = max(lat.metrics("linespace"), cjk.metrics("linespace"))
        box = tk.Frame(parent, bg=bg, height=line_h)
        if not wrap:
            box.config(width=sum((cjk if c else lat).measure(r) for r, c in runs) + 2)
        box.pack_propagate(False)
        t = tk.Text(box, width=1, height=1, bd=0, highlightthickness=0, padx=0, pady=0,
                    bg=bg, fg=fg, font=lat, wrap="word" if wrap else "none",
                    cursor="arrow", selectbackground=bg, selectforeground=fg,
                    inactiveselectbackground=bg, exportselection=False, takefocus=0)
        t.tag_configure("cn", font=cjk)
        for r, c in runs:
            t.insert("end", r, "cn" if c else ())
        t.config(state="disabled")
        t.bindtags((str(t), "all"))          # 去掉 Text 自带的选中/编辑行为
        t.pack(fill="both", expand=True)

        def fit(e=None):
            h = int(t.tk.call(t._w, "count", "-update", "-ypixels", "1.0", "end") or 0)
            h = max(line_h, h + 2)
            if int(box.cget("height")) != h:
                box.config(height=h)
        if wrap:
            t.bind("<Configure>", fit)
        return box, t

    def cn_font_for(self, ent):
        """输入框里出现中文就切到中文字体（Entry 只能用一种字体）。"""
        if ent.cget("fg") == TEXT:
            ent.config(font=self.fn["cn" if self.CN and CJK_RE.search(ent.get()) else "task"])

    # ---------------------------------------------------- 操作
    def commit(self):
        self.d["tasks"].sort(key=lambda t: t["created"])
        for t in self.d["tasks"]:
            if t["cat"] not in self.d["categories"]:
                self.d["categories"].append(t["cat"])
        save(self.d)
        self.render()

    def placeholder(self, show):
        if show and not self.entry.get():
            self.entry.insert(0, PLACEHOLDER if not self.emode else
                              "category name…" if self.emode[0] == "newcat" else "new name…")
            self.entry.config(fg=SUB, font=self.fn["task"])
        elif not show and self.entry.cget("fg") == SUB:
            self.entry.delete(0, "end")
            self.entry.config(fg=TEXT)

    def focus_entry(self, e=None):
        # 无边框窗口在 Windows 上需要强制拿焦点才能打字
        self.root.focus_force()
        self.entry.focus_set()

    def add(self, e=None):
        raw = self.entry.get().strip()
        if not raw or self.entry.cget("fg") == SUB:
            return self.focus_entry()
        if self.emode:
            kind, arg = self.emode
            name = raw.strip().strip(":：").strip().lower()[:20]
            self.emode = None
            self.entry.delete(0, "end")
            if kind == "newcat":
                self.ensure_cat(name)
                if arg is None:          # 从输入框的分类菜单新建 → 之后的新任务都放这里
                    self.st["add_cat"] = name
                else:                    # 从任务右键新建 → 只移动这一条
                    arg["cat"] = name
            else:
                self.rename_cat(arg, name)
            self.draw_entry()
            return self.commit()
        cat, text = parse(raw, self.st["add_cat"])
        if text:
            status = self.tab if self.tab in ("todo", "pending") else "todo"
            self.d["tasks"].append(new_task(cat, text, status))
            self.tab = status
            if cat in self.st["folded"]:
                self.st["folded"].remove(cat)
        self.entry.delete(0, "end")
        self.commit()

    def set_status(self, t, status):
        t["status"] = status
        t["updated"] = time.time()
        self.commit()

    def delete(self, t):
        self.d["tasks"].remove(t)
        self.commit()

    def toggle_fold(self, cat):
        f = self.st["folded"]
        f.remove(cat) if cat in f else f.append(cat)
        save(self.d)
        self.render()

    def edit(self, t):
        if self.editing or t["id"] not in self.rows:
            return
        row, lbl = self.rows[t["id"]]
        self.editing = t["id"]
        lbl.pack_forget()
        ent = tk.Entry(row, font=self.fn["task"], bg=ACTIVE, fg=TEXT, relief="flat",
                       highlightthickness=1, highlightbackground=BORDER,
                       highlightcolor=SUB)
        ent.insert(0, t["text"] if t["cat"] == DEFAULT_CAT else f"{t['cat']}: {t['text']}")
        ent.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.cn_font_for(ent)
        ent.bind("<KeyRelease>", lambda e: self.cn_font_for(ent))
        self.root.focus_force()
        ent.focus_set()
        ent.select_range(0, "end")

        def done(keep):
            if self.editing != t["id"]:
                return
            self.editing = None
            if keep and ent.get().strip():
                t["cat"], t["text"] = parse(ent.get())
                t["updated"] = time.time()
                self.commit()
            else:
                self.render()
        ent.bind("<Return>", lambda e: done(True))
        ent.bind("<Escape>", lambda e: done(False))
        ent.bind("<FocusOut>", lambda e: done(True))

    # ---------------------------------------------------- 分类
    def all_cats(self):
        cats = [DEFAULT_CAT] + [c for c in self.d["categories"] if c != DEFAULT_CAT]
        if self.st["add_cat"] not in cats:
            cats.append(self.st["add_cat"])
        return cats

    def chip_text(self):
        if self.emode:
            return "new ›" if self.emode[0] == "newcat" else "rename ›"
        return f"{self.st['add_cat']} ▾"

    def ensure_cat(self, name):
        if name and name not in self.d["categories"]:
            self.d["categories"].append(name)

    def set_add_cat(self, c):
        self.st["add_cat"] = c
        save(self.d)
        self.draw_entry()

    def cat_menu(self, e):
        """点输入框左侧的分类：选新任务放进哪个分类，或新建分类。"""
        m = tk.Menu(self.root, tearoff=0)
        for c in self.all_cats():
            m.add_command(label=("✓  " if c == self.st["add_cat"] else "     ") + c,
                          command=lambda c=c: (self.set_add_cat(c), self.focus_entry()))
        m.add_separator()
        m.add_command(label="＋ 新分类…", command=lambda: self.start_emode(("newcat", None)))
        self.popup(m, e)

    def cat_header_menu(self, e, cat):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="在这个分类里添加",
                      command=lambda: (self.set_add_cat(cat), self.focus_entry()))
        m.add_command(label="重命名…", command=lambda: self.start_emode(("rename", cat)))
        m.add_command(label="删除分类（任务移到 inbox）", command=lambda: self.delete_cat(cat),
                      state="disabled" if cat == DEFAULT_CAT else "normal")
        self.popup(m, e)

    def start_emode(self, mode):
        """借用底部输入框输入分类名（新建 / 重命名）。"""
        if self.mode == "ball":
            self.show("pinned")
        self.emode = mode
        self.entry.delete(0, "end")
        self.entry.config(fg=TEXT, font=self.fn["task"])
        if mode[0] == "rename":
            self.entry.insert(0, mode[1])
            self.entry.select_range(0, "end")
        self.draw_entry()
        self.focus_entry()

    def end_emode(self):
        if self.emode:
            self.emode = None
            self.entry.delete(0, "end")
            self.draw_entry()

    def move_to_cat(self, t, c):
        t["cat"] = c
        t["updated"] = time.time()
        if c in self.st["folded"]:
            self.st["folded"].remove(c)
        self.commit()

    def rename_cat(self, old, new):
        if not new or new == old:
            return
        for t in self.d["tasks"]:
            if t["cat"] == old:
                t["cat"] = new
        cats = self.d["categories"]
        if old in cats:
            if new in cats:
                cats.remove(old)
            else:
                cats[cats.index(old)] = new
        self.ensure_cat(new)
        f = self.st["folded"]
        if old in f:
            f.remove(old)
            if new not in f:
                f.append(new)
        if self.st["add_cat"] == old:
            self.st["add_cat"] = new

    def delete_cat(self, cat):
        for t in self.d["tasks"]:
            if t["cat"] == cat:
                t["cat"] = DEFAULT_CAT
        if cat in self.d["categories"]:
            self.d["categories"].remove(cat)
        if cat in self.st["folded"]:
            self.st["folded"].remove(cat)
        if self.st["add_cat"] == cat:
            self.st["add_cat"] = DEFAULT_CAT
        self.draw_entry()
        self.commit()

    def switch(self, key):
        self.tab = key
        self.canvas.yview_moveto(0)
        self.render()

    def popup(self, m, e):
        self.menu_open = True
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()
            self.root.after(300, lambda: setattr(self, "menu_open", False))

    def task_menu(self, e, t):
        m = tk.Menu(self.root, tearoff=0)
        for key, label in TABS:
            if key != t["status"]:
                m.add_command(label=f"→ {label}",
                              command=lambda k=key: self.set_status(t, k))
        cm = tk.Menu(m, tearoff=0)
        for c in self.all_cats():
            cm.add_command(label=("✓  " if c == t["cat"] else "     ") + c,
                           command=lambda c=c: self.move_to_cat(t, c))
        cm.add_separator()
        cm.add_command(label="＋ 新分类…", command=lambda: self.start_emode(("newcat", t)))
        m.add_separator()
        m.add_cascade(label="移到分类", menu=cm)
        m.add_command(label="编辑", command=lambda: self.edit(t))
        m.add_command(label="删除", command=lambda: self.delete(t))
        self.popup(m, e)

    def settings_menu(self, e):
        m = tk.Menu(self.root, tearoff=0)
        glass = tk.BooleanVar(value=self.st["glass"])
        m.add_checkbutton(label="半透明", variable=glass, command=self.toggle_glass)
        alpha = tk.Menu(m, tearoff=0)
        for a in (0.9, 0.8, 0.72, 0.65, 0.55, 0.45):
            alpha.add_command(label=f"{int(a * 100)}%", command=lambda a=a: self.set_alpha(a))
        m.add_cascade(label="透明度", menu=alpha)
        screens = tk.Menu(m, tearoff=0)
        mons = monitors()
        here = monitor_at(self.st["bx"] + self.BW / 2, self.st["by"] + self.BW / 2)["work"]
        for i, mon in enumerate(mons, 1):
            w, h = mon["size"]
            label = f"屏幕 {i}{'（主）' if mon['primary'] else ''}  {w}×{h}"
            if mon["work"] == here:
                label += "  ← 当前"
            screens.add_command(label=label, command=lambda mon=mon: self.move_to_monitor(mon))
        if len(mons) == 1:
            screens.add_command(label="只检测到 1 个屏幕", state="disabled")
        m.add_cascade(label="移到屏幕", menu=screens)
        auto = tk.BooleanVar(value=os.path.exists(STARTUP_LNK))
        m.add_checkbutton(label="开机自启", variable=auto,
                          command=lambda: set_autostart(auto.get()))
        m.add_command(label="清空 Completed / Cancelled", command=self.clear_closed)
        m.add_separator()
        m.add_command(label="退出", command=self.quit)
        self.popup(m, e)

    def clear_closed(self):
        self.d["tasks"] = [t for t in self.d["tasks"]
                           if t["status"] not in ("done", "cancelled")]
        self.commit()

    # ---------------------------------------------------- 拖动 / 缩放 / 滚动
    def move_ball(self, bx, by):
        self.st["bx"], self.st["by"] = self.clamp_ball(bx, by)
        self.ball.geometry(f"+{self.st['bx']}+{self.st['by']}")
        if self.mode != "ball":
            self.place_panel()
        self.paint_ball_window()

    def clamp_ball(self, bx, by):
        l, t, r, b = monitor_at(bx + self.BW / 2, by + self.BW / 2)["work"]
        return min(max(l, int(bx)), r - self.BW), min(max(t, int(by)), b - self.BW)

    def move_to_monitor(self, mon):
        """把小球放到指定屏幕的右上角（面板若展开会跟过去）。"""
        l, t, r, b = mon["work"]
        self.move_ball(r - self.BW - int(20 * self.s), t + int(60 * self.s))
        save(self.d)

    def ball_press(self, e):
        self._bp = (e.x_root, e.y_root, self.st["bx"], self.st["by"])
        self._dragged = False

    def ball_move(self, e):
        x0, y0, bx, by = self._bp
        if abs(e.x_root - x0) + abs(e.y_root - y0) > 4:
            self._dragged = True
        if self._dragged:
            self.move_ball(bx + e.x_root - x0, by + e.y_root - y0)

    def ball_release(self, e):
        if self._dragged:
            save(self.d)
        elif self.mode == "pinned":
            self.hide()
        else:
            self.show("pinned")

    def drag_start(self, e):
        self._bp = (e.x_root, e.y_root, self.st["bx"], self.st["by"])

    def drag_move(self, e):
        x0, y0, bx, by = self._bp
        self.move_ball(bx + e.x_root - x0, by + e.y_root - y0)

    CURSORS = {"n": "sb_v_double_arrow", "s": "sb_v_double_arrow",
               "e": "sb_h_double_arrow", "w": "sb_h_double_arrow",
               "nw": "size_nw_se", "se": "size_nw_se",
               "ne": "size_ne_sw", "sw": "size_ne_sw"}

    def edge_side(self, e):
        w, h, k = self.edge.winfo_width(), self.edge.winfo_height(), self.R * 2
        side = ("n" if e.y < k else "s" if e.y > h - k else "") +                ("w" if e.x < k else "e" if e.x > w - k else "")
        locked = ("s" if self.up else "n") + ("e" if self.right else "w")
        return "".join(c for c in side if c not in locked)   # 小球所在的边不能拖

    def edge_cursor(self, e):
        self.edge.config(cursor=self.CURSORS.get(self.edge_side(e), ""))

    def resize_start(self, e):
        r = self.root
        self._rs = (self.edge_side(e), e.x_root, e.y_root,
                    r.winfo_x(), r.winfo_y(), r.winfo_width(), r.winfo_height())

    def resize_move(self, e):
        side, x0, y0, x, y, w, h = self._rs
        if not side:
            return
        dx, dy = e.x_root - x0, e.y_root - y0
        mw, mh = int(260 * self.s), int(260 * self.s)
        if "e" in side:
            w = max(mw, w + dx)
        if "w" in side:
            nw = max(mw, w - dx)
            x, w = x + w - nw, nw
        if "s" in side:
            h = max(mh, h + dy)
        if "n" in side:
            nh = max(mh, h - dy)
            y, h = y + h - nh, nh
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        # 收起后小球的位置 = 面板顶角（place_panel 的逆运算）
        P, D, M = self.P, self.D, self.M
        self.st["pw"], self.st["ph"] = w, h
        self.st["bx"] = x + w - P - D - M if self.right else x - P + M
        self.st["by"] = y + h - P - D - M if self.up else y - P + M
        self.apply_zoom()

    def resize_end(self, e):
        save(self.d)
        self.render()

    def on_resize(self, e):
        self.canvas.itemconfigure(self.win, width=e.width)
        if e.width != getattr(self, "_last_w", None) and not self.editing:
            self._last_w = e.width
            self.root.after_idle(self.render)

    def on_wheel(self, e):
        if e.state & 0x4:  # Ctrl + 滚轮 调透明度
            self.set_alpha(self.st["alpha"] + (0.05 if e.delta > 0 else -0.05))
        elif self.inner.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-e.delta / 120), "units")

    def quit(self):
        save(self.d)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if "--autostart" in sys.argv:
        set_autostart(True)
    elif "--no-autostart" in sys.argv:
        set_autostart(False)
    else:
        App().run()
