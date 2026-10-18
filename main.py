# -*- coding: utf-8 -*-
"""
Rắn Săn Đáp Án AI - máy chủ game online.

- Flask + Flask-SocketIO (async_mode="threading"), giữ khung giống main.py cũ.
- Máy chủ là "trọng tài": mọi di chuyển, ăn đáp án, cắn nhau, tính điểm, tính tim
  đều do server quyết định, client chỉ gửi hướng đi.
- Có sẵn Cloudflare Tunnel (cloudflared) để đưa server ra domain
  https://snake-ai.huskydg.io.vn
- CORS mở cho trang tĩnh (vd snake-ai-mocha.vercel.app).
- Có thể tự phục vụ luôn index.html (+ sw.js, question.json, ...) để chạy nội bộ,
  không cần Vercel: mở http://<IP-máy>:<PORT>/ (đặt HOST=0.0.0.0 để cả lớp cùng vào).
- Chống lag: mỗi người chỉ nhận phần bản đồ quanh mình, có điều tiết theo tốc độ mạng
  (client báo "ack"), tắt Nagle (TCP_NODELAY). Có chế độ khán giả (xem không chơi).
"""
import io
import os
import re
import sys
import json
import time
import random
import shutil
import sqlite3
import tarfile
import platform
import threading
import socket
import mimetypes
import importlib
import subprocess
import traceback
import unicodedata
import urllib.request
from types import SimpleNamespace



def ensure_requirements():
    """Chạy luôn từ requirements.txt: thiếu thư viện thì tự pip install."""
    req = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
    try:
        import flask, flask_socketio, dotenv, simple_websocket  # noqa: F401
        return
    except ImportError:
        pass
    if not os.path.exists(req):
        return
    print("[*] Đang cài thư viện từ requirements.txt ...")
    cmd = [sys.executable, "-m", "pip", "install", "-r", req]
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        subprocess.check_call(cmd + ["--break-system-packages"])


ensure_requirements()

from flask import Flask, jsonify, request, send_from_directory, abort
from flask_socketio import SocketIO, join_room, leave_room
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.serving import WSGIRequestHandler

load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def env_int(key, default):
    try:
        return int(os.getenv(key, str(default)).strip())
    except ValueError:
        return default


def env_float(key, default):
    try:
        return float(os.getenv(key, str(default)).strip())
    except ValueError:
        return default


def env_bool(key, default=False):
    return os.getenv(key, str(default)).strip().lower() in ("1", "true", "yes")


# =========================================
# Cấu hình server
# =========================================
HOST = os.getenv("HOST", "127.0.0.1")
PORT = env_int("PORT", 8888)
ALLOWED_ORIGINS_RAW = os.getenv("ALLOWED_ORIGINS", "*").strip()
ALLOW_ALL = ALLOWED_ORIGINS_RAW in ("", "*")
ALLOWED_LIST = [o.strip().rstrip("/") for o in ALLOWED_ORIGINS_RAW.split(",") if o.strip()]
# Chỉ chấp nhận request có header Host nằm trong danh sách (cách nhau dấu phẩy, bỏ qua cổng).
# Hỗ trợ "*.ten-mien.com". Để trống hoặc "*" = chấp nhận mọi Host (như cũ).
ALLOWED_HOSTS_RAW = os.getenv("ALLOWED_HOSTS", "*").strip()
ALLOWED_HOSTS = [h.strip().lower() for h in ALLOWED_HOSTS_RAW.split(",") if h.strip()]
ALLOW_ANY_HOST = not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS

# Tự phục vụ giao diện web (index.html...) để chạy nội bộ. Chỉ các file trong danh sách trắng
# bên dưới mới được trả ra, nên .env, snake.db, main.py... không bao giờ bị lộ.
SERVE_WEB = env_bool("SERVE_WEB", True)
WEB_DIR = os.getenv("WEB_DIR", BASE_DIR)
WEB_FILES = {"index.html", "sw.js", "manifest.webmanifest", "question.json", "socket_io_min.js",
             "icon-192.png", "icon-512.png"}
WEB_FILES |= {x.strip() for x in os.getenv("WEB_EXTRA_FILES", "").split(",") if x.strip() and "/" not in x and "\\" not in x}
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")

DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "snake.db"))
QUESTION_FILE = os.getenv("QUESTION_FILE", os.path.join(BASE_DIR, "question.json"))

# =========================================
# Cloudflare Tunnel (cloudflared)
# =========================================
TUNNEL_ENABLED = env_bool("TUNNEL", False)
TUNNEL_HOST = os.getenv("TUNNEL_HOST", "snake-ai.huskydg.io.vn").strip()
TUNNEL_TOKEN = os.getenv("TUNNEL_TOKEN", "").strip()

_cloudflared_proc = None
_cloudflared_url = None

# =========================================
# Cấu hình game (có thể chỉnh trong .env)
# =========================================
GAME_SIZE = env_int("GAME_SIZE", 100)            # bản đồ GAME_SIZE x GAME_SIZE, đi xuyên tường
TICK_MS = env_int("TICK_MS", 150)               # mỗi bước đi (ms), mọi người cùng tốc độ
MAX_PLAYERS = env_int("MAX_PLAYERS", 24)
HEARTS_START = env_int("HEARTS_START", 5)
HEARTS_MAX = env_int("HEARTS_MAX", 10)
POINTS_CORRECT = env_int("POINTS_CORRECT", 10)
STREAK_BONUS = env_int("STREAK_BONUS", 2)
STREAK_BONUS_MAX = env_int("STREAK_BONUS_MAX", 5)
BITE_PENALTY = env_int("BITE_PENALTY", 5)       # điểm bị trừ khi cắn trúng người khác
HEART_FULL_BONUS = env_int("HEART_FULL_BONUS", 3)  # điểm thưởng khi nhặt tim lúc đã đầy tim
ROUND_SECONDS = env_int("ROUND_SECONDS", 45)    # thời gian tối đa cho mỗi câu hỏi
INTERMISSION_SECONDS = env_float("INTERMISSION_SECONDS", 5)  # nghỉ giữa các câu để đọc đáp án
HEART_EVERY = env_int("HEART_EVERY", 25)        # trung bình bao nhiêu giây có 1 trái tim mới
HEART_LIFETIME = env_int("HEART_LIFETIME", 30)
HEART_MAX_ON_MAP = env_int("HEART_MAX_ON_MAP", 3)
GROW = env_int("GROW", 2)
MAX_LEN = env_int("MAX_LEN", 40)
SPAWN_PROTECT = env_float("SPAWN_PROTECT", 2.5)  # giây "bất tử" sau khi xuất hiện lại
AFK_SECONDS = env_int("AFK_SECONDS", 90)
RECONNECT_GRACE = env_int("RECONNECT_GRACE", 20)  # giữ tên bao lâu sau khi mất kết nối
ITEM_SPACING = env_int("ITEM_SPACING", 10)       # khoảng cách tối thiểu giữa các ô đáp án
INTEREST_R = env_int("INTEREST_R", 14)           # chỉ gửi rắn nằm trong bán kính này quanh đầu rắn của người chơi
MAX_SPECTATORS = env_int("MAX_SPECTATORS", 200)  # số khán giả tối đa
LAG_SOFT_MS = env_int("LAG_SOFT_MS", 1500)       # client chậm hơn mức này thì giảm tần suất gửi state cho riêng client đó

W = GAME_SIZE
TICK = TICK_MS / 1000.0
ROOM = "arena"
DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]
NUM_COLORS = 8

# ---------- Bản đồ: đất nhà, nhà, tường, cây ----------

def build_map(size, seed):
    """Bản đồ cố định theo seed. Ký tự: '.' cỏ, 'Y' đất nhà, 'H' mái nhà, 'D' cửa nhà, 'W' tường, 'T' cây."""
    rnd = random.Random(seed)
    g = [["."] * size for _ in range(size)]

    def get(x, y):
        return g[y % size][x % size]

    def put(x, y, ch):
        g[y % size][x % size] = ch

    def box(x, y, w, h, ch):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                put(xx, yy, ch)

    # 1) thửa đất nhà: lưới 3x3, bỏ ô giữa làm quảng trường
    for gy in range(3):
        for gx in range(3):
            if gx == 1 and gy == 1:
                continue
            pw, ph = rnd.randint(14, 17), rnd.randint(12, 15)
            px = 8 + gx * 34 + rnd.randint(-2, 2)
            py = 8 + gy * 34 + rnd.randint(-2, 2)
            box(px, py, pw, ph, "Y")
            hw, hh = rnd.randint(5, 7), rnd.randint(4, 5)
            hx = px + rnd.randint(2, pw - hw - 2)
            hy = py + rnd.randint(2, ph - hh - 2)
            box(hx, hy, hw, hh, "H")
            put(hx + hw // 2, hy + hh - 1, "D")
            for _ in range(rnd.randint(3, 5)):  # cây trong vườn
                tx, ty = rnd.randint(px + 1, px + pw - 2), rnd.randint(py + 1, py + ph - 2)
                if all(get(tx + a, ty + b) == "Y" for a in (-1, 0, 1) for b in (-1, 0, 1)):
                    put(tx, ty, "T")

    # 2) quảng trường giữa bản đồ: vòng tường có 4 cổng
    c0 = size // 2
    box(c0 - 7, c0 - 7, 15, 15, "Y")
    for k in range(-6, 7):
        if abs(k) > 1:
            for x, y in ((c0 + k, c0 - 6), (c0 + k, c0 + 6), (c0 - 6, c0 + k), (c0 + 6, c0 + k)):
                put(x, y, "W")
    for a in (-3, 3):
        for b in (-3, 3):
            put(c0 + a, c0 + b, "T")

    # 3) vài bức tường lẻ ngoài đường (mỗi bức chừa một khe 3 ô)
    made = tries = 0
    while made < 12 and tries < 600:
        tries += 1
        n = rnd.randint(9, 18)
        horiz = rnd.random() < 0.5
        x, y = rnd.randrange(size), rnd.randrange(size)
        gap = rnd.randint(3, n - 5)
        full = [((x + i, y) if horiz else (x, y + i)) for i in range(n)]
        if all(get(a + dx, b + dy) == "." for a, b in full for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
            for i, (a, b) in enumerate(full):
                if not gap <= i < gap + 3:
                    put(a, b, "W")
            made += 1

    # 4) cây: vài khu rừng nhỏ + cây lẻ
    for _ in range(7):
        cx, cy, r = rnd.randrange(size), rnd.randrange(size), rnd.randint(4, 7)
        for yy in range(cy - r, cy + r + 1):
            for xx in range(cx - r, cx + r + 1):
                if (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r and rnd.random() < 0.55 and get(xx, yy) == ".":
                    put(xx, yy, "T")
    for _ in range(110):
        x, y = rnd.randrange(size), rnd.randrange(size)
        if get(x, y) == ".":
            put(x, y, "T")

    # 5) dọn bản đồ: lấp ngõ cụt (rắn không quay đầu được) và các ô bị cô lập
    def free(ch):
        return ch in ".Y"

    N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
    changed = True
    while changed:
        changed = False
        for y in range(size):
            for x in range(size):
                if free(g[y][x]) and sum(not free(get(x + a, y + b)) for a, b in N4) >= 3:
                    g[y][x] = "T"
                    changed = True
    seen, best = set(), []
    for y in range(size):
        for x in range(size):
            if free(g[y][x]) and (x, y) not in seen:
                comp, st = [], [(x, y)]
                seen.add((x, y))
                while st:
                    px_, py_ = st.pop()
                    comp.append((px_, py_))
                    for a, b in N4:
                        q = ((px_ + a) % size, (py_ + b) % size)
                        if q not in seen and free(g[q[1]][q[0]]):
                            seen.add(q)
                            st.append(q)
                if len(comp) > len(best):
                    best = comp
    keep = set(best)
    for y in range(size):
        for x in range(size):
            if free(g[y][x]) and (x, y) not in keep:
                g[y][x] = "T"

    rows = ["".join(r) for r in g]
    blocked = {(x, y): ch for y, r in enumerate(rows) for x, ch in enumerate(r) if ch in "WTHD"}
    return rows, blocked


MAP_SEED = env_int("MAP_SEED", 7)
MAP_ROWS, BLOCKED = build_map(W, MAP_SEED) if W >= 80 else ([], {})   # GAME_SIZE < 80: không có vật cản
MAP_NAMES = {"W": "tường", "T": "cây", "H": "nhà", "D": "nhà"}

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", os.urandom(16).hex())
socketio = SocketIO(
    app,
    cors_allowed_origins="*" if ALLOW_ALL else ALLOWED_LIST,
    async_mode="threading",
    ping_interval=10,
    ping_timeout=30,
)


def _strip_port(h):
    h = (h or "").strip().lower()
    if h.startswith("["):  # IPv6: [::1]:8888
        end = h.find("]")
        return h[: end + 1] if end != -1 else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def host_allowed(host):
    if ALLOW_ANY_HOST:
        return True
    h = _strip_port(host).rstrip(".")
    if not h:
        return False
    for pat in ALLOWED_HOSTS:
        pat = _strip_port(pat).rstrip(".")
        if pat == h:
            return True
        if pat.startswith("*.") and h.endswith(pat[1:]) and len(h) > len(pat) - 1:
            return True
    return False


class HostGuard:
    """Chặn mọi request (cả Socket.IO) có Host không nằm trong ALLOWED_HOSTS."""

    def __init__(self, wsgi):
        self.wsgi = wsgi

    def __call__(self, environ, start_response):
        if not host_allowed(environ.get("HTTP_HOST", "")):
            body = b"Host not allowed"
            start_response("421 Misdirected Request",
                           [("Content-Type", "text/plain; charset=utf-8"),
                            ("Content-Length", str(len(body)))])
            return [body]
        return self.wsgi(environ, start_response)


if not ALLOW_ANY_HOST:
    app.wsgi_app = HostGuard(app.wsgi_app)


@app.after_request
def add_cors_headers(resp):
    origin = (request.headers.get("Origin") or "").rstrip("/")
    if ALLOW_ALL:
        resp.headers["Access-Control-Allow-Origin"] = "*"
    elif origin and origin in ALLOWED_LIST:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


def now_ts():
    return time.time()


# =========================================
# Ngân hàng câu hỏi (đọc từ question.json, tự nạp lại khi file đổi)
# =========================================
FALLBACK_QUESTIONS = [
    {"question": "AI là viết tắt của cụm từ nào?",
     "correct": "Artificial Intelligence (Trí tuệ nhân tạo)",
     "wrong": ["Automatic Internet (Mạng tự động)", "Awesome Idea (Ý tưởng tuyệt vời)", "Animal Index (Chỉ số động vật)"],
     "explanation": "AI là Artificial Intelligence: trí tuệ nhân tạo."},
    {"question": "Dữ liệu (data) là gì?",
     "correct": "Thông tin như chữ, ảnh, âm thanh, con số",
     "wrong": ["Một loại nhạc cụ", "Một loại đồ ăn vặt", "Một loại cây"],
     "explanation": "AI học từ dữ liệu."},
    {"question": "AI có thể trả lời sai không?",
     "correct": "Có, AI đôi khi trả lời sai",
     "wrong": ["Không, AI luôn đúng 100%", "Không, AI không bao giờ sai"],
     "explanation": "Hãy kiểm tra lại thông tin quan trọng."},
]

_QUESTIONS = []
_QMTIME = None
_DECK = []


def _s(v):
    return str(v).strip() if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def normalize_questions(data):
    arr = data if isinstance(data, list) else (data.get("questions") if isinstance(data, dict) else None)
    if not isinstance(arr, list):
        return []
    out = []
    for it in arr:
        if not isinstance(it, dict):
            continue
        question = _s(it.get("question", it.get("q")))
        correct = _s(it.get("correct", it.get("answer")))
        w = it.get("wrong", it.get("wrongs", it.get("incorrect", [])))
        wrong = [x for x in (_s(v) for v in (w if isinstance(w, list) else [w])) if x]
        explanation = _s(it.get("explanation", it.get("explain")))
        if question and correct and wrong:
            out.append({"question": question, "correct": correct, "wrong": wrong, "explanation": explanation})
    return out


def load_questions(force=False):
    global _QUESTIONS, _QMTIME, _DECK
    try:
        mtime = os.path.getmtime(QUESTION_FILE)
    except OSError:
        mtime = None
    if not force and _QUESTIONS and mtime == _QMTIME:
        return
    items = []
    if mtime is not None:
        try:
            with open(QUESTION_FILE, "r", encoding="utf-8") as f:
                items = normalize_questions(json.load(f))
            print(f"[*] Đã nạp {len(items)} câu hỏi từ {QUESTION_FILE}")
        except Exception as e:
            print(f"[!] Không đọc được {QUESTION_FILE}: {e}")
    if not items:
        print("[!] Dùng câu hỏi mẫu dự phòng (không có question.json hợp lệ).")
        items = normalize_questions(FALLBACK_QUESTIONS)
    _QUESTIONS, _QMTIME, _DECK = items, mtime, []


def next_question():
    global _DECK
    load_questions()
    if not _DECK:
        _DECK = list(range(len(_QUESTIONS)))
        random.shuffle(_DECK)
    q = _QUESTIONS[_DECK.pop()]
    wrong = random.sample(q["wrong"], min(3, len(q["wrong"])))
    options = [{"text": q["correct"], "ok": True}] + [{"text": t, "ok": False} for t in wrong]
    random.shuffle(options)
    correct = next(i for i, o in enumerate(options) if o["ok"])
    return {"question": q["question"], "explanation": q["explanation"], "options": options, "correct": correct}


# =========================================
# Điểm cao nhất mọi thời đại (lưu SQLite)
# =========================================
db_lock = threading.Lock()
best_all = {}  # key -> [name, score]


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_lock:
        conn = get_db()
        conn.execute("""CREATE TABLE IF NOT EXISTS best (
            key TEXT PRIMARY KEY, name TEXT NOT NULL, score INTEGER NOT NULL, updated REAL NOT NULL)""")
        conn.commit()
        for r in conn.execute("SELECT key, name, score FROM best"):
            best_all[r["key"]] = [r["name"], r["score"]]
        conn.close()


def flush_best():
    with db_lock:
        conn = get_db()
        conn.executemany(
            "INSERT INTO best (key, name, score, updated) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET name=excluded.name, score=excluded.score, updated=excluded.updated",
            [(k, v[0], v[1], now_ts()) for k, v in list(best_all.items())],
        )
        conn.commit()
        conn.close()


def top_best(n=10):
    return sorted(([v[0], v[1]] for v in best_all.values()), key=lambda x: -x[1])[:n]


# =========================================
# Trạng thái game
# =========================================
G = threading.RLock()
S = SimpleNamespace(tick=0, next_id=1, next_heart=0.0, best_dirty=False, last_flush=0.0, hearts=[])
players = {}   # id -> Player
by_key = {}    # khoá tên (không dấu, không phân biệt hoa thường) -> id
by_sid = {}    # sid -> id
specs = {}     # sid -> Spec (khán giả)
R = {"id": 0, "st": "between", "ends": 0.0, "between_until": 0.0, "q": None, "items": [], "last_end": None}


class Player:
    __slots__ = ("id", "sid", "name", "key", "token", "color", "snake", "dir", "queue", "grow", "hearts",
                 "score", "streak", "alive", "dead", "connected", "expire", "protect_until", "last_input",
                 "acked", "ack_seen", "last_sent", "cam", "ep", "pend", "trail")

    def __init__(self, pid, sid, name, key, token, color):
        self.id = pid
        self.sid = sid
        self.name = name
        self.key = key
        self.token = token
        self.color = color
        self.snake = []
        self.dir = (1, 0)
        self.queue = []
        self.grow = 0
        self.hearts = HEARTS_START
        self.score = 0
        self.streak = 0
        self.alive = False      # đang có rắn trên bản đồ
        self.dead = False       # hết tim, đang chờ bấm "Chơi lại"
        self.connected = True
        self.expire = None
        self.protect_until = 0.0
        self.last_input = now_ts()
        self.acked = 0          # tick mới nhất mà client báo đã nhận
        self.ack_seen = False   # client cũ không gửi ack thì không điều tiết
        self.last_sent = 0
        self.ep = 0             # đời rắn: lệnh đi của đời cũ bị bỏ qua
        self.pend = []          # các ô đầu rắn client báo, chờ server xử lý
        self.trail = []         # các ô đầu rắn đi qua trong tick này
        self.cam = None         # vị trí đầu rắn gần nhất, dùng để cắt vùng gửi


class Spec:
    """Khán giả: chỉ xem, không có rắn, nhận toàn bộ bản đồ."""
    __slots__ = ("sid", "acked", "ack_seen", "last_sent")

    def __init__(self, sid):
        self.sid = sid
        self.acked = S.tick
        self.ack_seen = False
        self.last_sent = 0


def name_key(name):
    s = unicodedata.normalize("NFD", name)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.casefold().replace("đ", "d")
    return re.sub(r"[^a-z0-9]", "", s)


def clean_name(raw):
    if not isinstance(raw, str):
        return None, "Tên không hợp lệ"
    name = re.sub(r"\s+", " ", unicodedata.normalize("NFC", raw)).strip()
    if len(name) < 2:
        return None, "Tên quá ngắn (tối thiểu 2 ký tự)"
    if len(name) > 16:
        return None, "Tên quá dài (tối đa 16 ký tự)"
    if not re.fullmatch(r"[\w .\-]+", name):
        return None, "Tên chỉ gồm chữ, số, dấu cách, dấu gạch ngang hoặc gạch dưới"
    if len(name_key(name)) < 2:
        return None, "Tên cần có ít nhất 2 chữ hoặc số"
    return name, None


def emit_to(p, event, data):
    if p.sid and p.connected:
        socketio.emit(event, data, to=p.sid)


def feed(msg, kind=""):
    socketio.emit("feed", {"m": msg, "k": kind}, to=ROOM)


def tdist(a, b):
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    return min(dx, W - dx) + min(dy, W - dy)


ITEM_SIZE = max(1, min(6, env_int("ITEM_SIZE", 1)))    # ô đáp án rộng ITEM_SIZE x ITEM_SIZE ô (mặc định 1x1)
HEART_SIZE = max(1, min(4, env_int("HEART_SIZE", 1)))  # trái tim rộng HEART_SIZE x HEART_SIZE ô (mặc định 1x1)


def block(x, y, n):
    """Các ô mà vật cỡ n x n, góc trên trái ở (x, y), chiếm."""
    return {((x + i) % W, (y + j) % W) for i in range(n) for j in range(n)}


def occupied():
    s = set(BLOCKED)
    for p in players.values():
        if p.alive:
            s.update(p.snake)
    for it in R["items"]:
        s.update(block(it["x"], it["y"], ITEM_SIZE))
    for h in S.hearts:
        s.update(block(h["x"], h["y"], HEART_SIZE))
    return s


def note_score(p):
    cur = best_all.get(p.key)
    if p.score > 0 and (cur is None or p.score > cur[1]):
        best_all[p.key] = [p.name, p.score]
        S.best_dirty = True


def send_snake(p):
    """Báo cho client vị trí rắn do server quyết định (hồi sinh / ép đồng bộ lại)."""
    emit_to(p, "snk", {"c": [v for c in p.snake for v in c], "d": [p.dir[0], p.dir[1]], "ep": p.ep})


# ---------- sinh rắn / ô đáp án / tim ----------
def spawn_snake(p, now):
    heads = [q.snake[0] for q in players.values() if q.alive and q.snake and q.id != p.id]
    occ = occupied()
    chosen = None
    for _ in range(400):
        x, y = random.randrange(W), random.randrange(W)
        d = random.choice(DIRS)
        cells = [((x - d[0] * k) % W, (y - d[1] * k) % W) for k in range(3)]
        if any(c in occ for c in cells):
            continue
        if any(((cells[0][0] + d[0] * k) % W, (cells[0][1] + d[1] * k) % W) in BLOCKED for k in range(1, 9)):
            continue   # trước mũi rắn phải thoáng ít nhất 8 ô
        if any(tdist(cells[0], h) < 6 for h in heads):
            continue
        chosen = (cells, d)
        break
    if chosen is None:
        for _ in range(3000):
            x, y = random.randrange(W), random.randrange(W)
            d = random.choice(DIRS)
            cells = [((x - d[0] * k) % W, (y - d[1] * k) % W) for k in range(3)]
            if not any(c in BLOCKED for c in cells):
                break
        chosen = (cells, d)
    p.snake, p.dir = chosen
    p.queue = []
    p.grow = 0
    p.alive = True
    p.protect_until = now + SPAWN_PROTECT
    p.ep += 1
    p.pend = []
    p.trail = []
    send_snake(p)


def place_cells(n):
    occ = occupied()
    heads = [p.snake[0] for p in players.values() if p.alive and p.snake]
    placed = []
    for _ in range(n):
        found = None
        for _try in range(300):
            c = (random.randrange(W), random.randrange(W))
            if not block(c[0], c[1], ITEM_SIZE).isdisjoint(occ) or any(tdist(c, q) < max(ITEM_SPACING, ITEM_SIZE + 1) for q in placed):
                continue
            if any(tdist(c, h) < 4 for h in heads):
                continue
            found = c
            break
        if found is None:
            for _try in range(500):
                c = (random.randrange(W), random.randrange(W))
                if block(c[0], c[1], ITEM_SIZE).isdisjoint(occ):
                    found = c
                    break
        if found is None:
            found = (random.randrange(W), random.randrange(W))
        placed.append(found)
        occ.update(block(found[0], found[1], ITEM_SIZE))
    return placed


def question_payload():
    q = R["q"]
    return {"id": R["id"], "question": q["question"], "options": [o["text"] for o in q["options"]],
            "total": ROUND_SECONDS}


def new_round(now):
    q = next_question()
    cells = place_cells(len(q["options"]))
    R["id"] += 1
    R["st"] = "active"
    R["q"] = q
    R["ends"] = now + ROUND_SECONDS
    R["last_end"] = None
    R["items"] = [{"i": i, "x": c[0], "y": c[1], "ok": q["options"][i]["ok"]} for i, c in enumerate(cells)]
    socketio.emit("question", question_payload(), to=ROOM)


def end_round(winner, gain, now):
    q = R["q"]
    R["st"] = "between"
    R["between_until"] = now + INTERMISSION_SECONDS
    R["items"] = []
    payload = {
        "id": R["id"], "correct": q["correct"], "text": q["options"][q["correct"]]["text"],
        "explanation": q["explanation"], "winner": winner.name if winner else None,
        "gain": gain, "left": INTERMISSION_SECONDS,
    }
    R["last_end"] = payload
    socketio.emit("round_end", payload, to=ROOM)


def maintain_round(now, idle=False):
    if R["q"] is None:
        new_round(now)
        return
    if R["st"] == "active":
        if idle:
            R["ends"] = now + ROUND_SECONDS      # không ai chơi thì đừng đếm giờ
        elif now >= R["ends"]:
            end_round(None, 0, now)
    elif now >= R["between_until"]:
        new_round(now)


def maintain_hearts(now):
    S.hearts[:] = [h for h in S.hearts if h["until"] > now]
    if now < S.next_heart:
        return
    S.next_heart = now + HEART_EVERY * random.uniform(0.7, 1.3)
    if len(S.hearts) >= HEART_MAX_ON_MAP:
        return
    if not any(p.alive and p.hearts < HEARTS_MAX for p in players.values()):
        return
    occ = occupied()
    for _ in range(200):
        c = (random.randrange(W), random.randrange(W))
        if block(c[0], c[1], HEART_SIZE).isdisjoint(occ):
            S.hearts.append({"x": c[0], "y": c[1], "until": now + HEART_LIFETIME})
            return


# ---------- vòng đời người chơi ----------
def kill(p):
    p.alive = False
    p.dead = True
    p.snake = []
    note_score(p)
    emit_to(p, "ev", {"t": "dead", "score": p.score, "best": best_all.get(p.key, [p.name, 0])[1]})
    feed(f"{p.name} hết tim", "bad")


def drop_snake(p):
    """Rời bản đồ nhưng vẫn giữ tên, điểm và tim (mất kết nối, thoát tab, nghỉ)."""
    p.alive = False
    p.snake = []
    p.queue = []


def remove_player(p):
    note_score(p)
    by_key.pop(p.key, None)
    if p.sid:
        by_sid.pop(p.sid, None)
    players.pop(p.id, None)
    feed(f"{p.name} rời phòng")


def cleanup(now):
    for p in list(players.values()):
        if not p.connected:
            if p.expire is not None and now > p.expire:
                remove_player(p)
        elif p.alive and now - p.last_input > AFK_SECONDS:
            drop_snake(p)
            emit_to(p, "afk", {})
    if S.best_dirty and now - S.last_flush > 20:
        S.best_dirty = False
        S.last_flush = now
        try:
            flush_best()
        except Exception:
            traceback.print_exc()


# =========================================
# Một bước của trò chơi
# =========================================
def apply_hit(p, victims, now, wall=None):
    p.streak = 0
    if wall:
        emit_to(p, "ev", {"t": "wall", "what": wall})
        feed(f"{p.name} đụng {MAP_NAMES.get(wall, 'vật cản')}: -1 tim", "bad")
    elif victims:
        pen = min(p.score, BITE_PENALTY)
        p.score -= pen
        names = ", ".join(sorted({players[v].name for v in victims if v in players}))
        emit_to(p, "ev", {"t": "bite", "who": names, "pts": pen})
        feed(f"{p.name} cắn trúng {names}: -{pen} điểm, -1 tim", "bad")
    else:
        emit_to(p, "ev", {"t": "self"})
    p.hearts -= 1
    if p.hearts <= 0:
        kill(p)
    else:
        spawn_snake(p, now)


def game_tick(now, idle=False):
    S.tick += 1
    maintain_round(now, idle)
    maintain_hearts(now)
    cleanup(now)

    alive = [p for p in players.values() if p.alive and p.snake]

    # 1) tất cả rắn tiến một bước
    # Rắn do CLIENT tự chạy ngay theo phím (không phụ thuộc ping) và báo từng ô đầu rắn lên.
    # Server kiểm tra ô đó có kề đầu rắn không rồi mới nhận; chạy chậm thì chờ, chạy dồn thì bắt kịp.
    for p in alive:
        p.trail = []
        for _ in range(1 + (len(p.pend) > 3) + (len(p.pend) > 7)):
            if not p.pend:
                break
            nx, ny = p.pend.pop(0)
            hx, hy = p.snake[0]
            dx, dy = (nx - hx) % W, (ny - hy) % W
            dx, dy = (dx if dx <= 1 else dx - W), (dy if dy <= 1 else dy - W)
            if abs(dx) + abs(dy) != 1 or (len(p.snake) > 1 and (nx, ny) == p.snake[1]):
                p.ep += 1          # đi sai luật: ép client đồng bộ lại theo server
                p.pend = []
                send_snake(p)
                break
            if (dx, dy) != p.dir:
                p.last_input = now
            p.dir = (dx, dy)
            p.snake.insert(0, (nx, ny))
            if p.grow > 0:
                p.grow -= 1
            else:
                p.snake.pop()
            p.trail.append((nx, ny))

    # 1b) đầu rắn chui vào tường / cây / nhà
    wall_hit = {}
    if BLOCKED:
        for p in alive:
            kind = BLOCKED.get(p.snake[0])
            if kind:
                wall_hit[p.id] = kind

    # 2) phát hiện va chạm (rắn đang "bất tử" không cắn được và không bị cắn)
    solid = [p for p in alive if p.protect_until <= now]
    occ = {}
    for p in solid:
        for idx, c in enumerate(p.snake):
            occ.setdefault(c, []).append((p.id, idx))
    hits = {}
    for p in solid:
        victims = set()
        selfhit = False
        for pid, idx in occ.get(p.snake[0], []):
            if pid == p.id:
                if idx > 0:
                    selfhit = True
            else:
                victims.add(pid)
        if victims or selfhit:
            hits[p.id] = victims
    for pid in wall_hit:
        hits.setdefault(pid, set())
    for pid, victims in hits.items():
        apply_hit(players[pid], victims, now, wall_hit.get(pid))

    # 3) ăn đáp án / trái tim (ai tới trước thì ăn trước)
    eaters = [p for p in alive if p.alive and p.id not in hits]
    random.shuffle(eaters)
    for p in eaters:
        cells = p.trail
        if R["st"] == "active":
            for it in list(R["items"]):
                if block(it["x"], it["y"], ITEM_SIZE).isdisjoint(cells):
                    continue
                if it["ok"]:
                    p.streak += 1
                    gain = POINTS_CORRECT + min(p.streak - 1, STREAK_BONUS_MAX) * STREAK_BONUS
                    p.score += gain
                    p.grow = min(p.grow + GROW, max(0, MAX_LEN - len(p.snake)))
                    note_score(p)
                    emit_to(p, "ev", {"t": "ok", "gain": gain, "streak": p.streak})
                    feed(f"{p.name} trả lời đúng +{gain}", "ok")
                    end_round(p, gain, now)
                else:
                    R["items"].remove(it)
                    p.streak = 0
                    p.hearts -= 1
                    emit_to(p, "ev", {"t": "wrong", "letter": "ABCD"[it["i"]]})
                    feed(f"{p.name} ăn nhầm đáp án {'ABCD'[it['i']]}", "bad")
                    if p.hearts <= 0:
                        kill(p)
                break
        if not p.alive:
            continue
        for h in list(S.hearts):
            if not block(h["x"], h["y"], HEART_SIZE).isdisjoint(cells):
                S.hearts.remove(h)
                if p.hearts < HEARTS_MAX:
                    p.hearts += 1
                    emit_to(p, "ev", {"t": "heart"})
                else:
                    p.score += HEART_FULL_BONUS
                    note_score(p)
                    emit_to(p, "ev", {"t": "heartfull", "pts": HEART_FULL_BONUS})
                break

    # 4) gửi trạng thái cho từng người (cắt theo vùng nhìn, điều tiết theo mạng)
    send_states(now)


def near(cells, cx, cy):
    """Có đốt nào của rắn nằm trong ô vuông bán kính INTEREST_R quanh (cx, cy) không (tính cả đi xuyên tường)."""
    R = INTEREST_R
    for x, y in cells:
        dx = abs(x - cx)
        if dx > W - dx:
            dx = W - dx
        if dx > R:
            continue
        dy = abs(y - cy)
        if dy > W - dy:
            dy = W - dy
        if dy <= R:
            return True
    return False


def due(link):
    """Điều tiết theo từng client: càng chậm (ack về muộn) càng gửi thưa, state là ảnh chụp đầy đủ nên bỏ bớt không sao."""
    if link.ack_seen:
        over = (S.tick - link.acked) * TICK_MS / float(max(200, LAG_SOFT_MS))
        n = 1 if over < 1 else 2 if over < 2 else 4   # tối đa 4: client vẫn nội suy mượt giữa các ảnh cách nhau 4 tick
    else:
        n = 1
    if S.tick - link.last_sent >= n:
        link.last_sent = S.tick
        return True
    return False


def build_frame(now):
    ents = []
    for p in players.values():
        if p.alive and p.snake:
            flat = []
            for x, y in p.snake:
                flat.append(x)
                flat.append(y)
            ents.append((p, [p.id, p.name, p.color, flat, p.dir[0], p.dir[1], p.hearts, p.score,
                             1 if p.protect_until > now else 0]))
    if R["st"] == "active":
        left, total = max(0.0, R["ends"] - now), ROUND_SECONDS
    else:
        left, total = max(0.0, R["between_until"] - now), INTERMISSION_SECONDS
    lb = sorted(([p.name, p.score] for p in players.values() if p.score > 0), key=lambda x: -x[1])[:5]
    common = {
        "k": S.tick,
        "r": [R["id"], 1 if R["st"] == "active" else 0, round(left, 1), total],
        "it": [[i["i"], i["x"], i["y"]] for i in R["items"]],
        "hr": [[h["x"], h["y"], round(h["until"] - now, 1)] for h in S.hearts],
        "lb": lb,
    }
    return common, ents


def send_states(now):
    if not players and not specs:
        return
    common, ents = build_frame(now)
    everyone = [e for _, e in ents]
    for p in list(players.values()):
        if not (p.connected and p.sid) or not due(p):
            continue
        if p.alive and p.snake:
            p.cam = p.snake[0]
        if p.cam is None:
            mine = everyone
        else:
            cx, cy = p.cam
            mine = [e for q, e in ents if q is p or near(q.snake, cx, cy)]
        payload = dict(common)
        payload["s"] = mine
        socketio.emit("state", payload, to=p.sid)
    if specs:
        payload = None
        for sp in list(specs.values()):
            if not due(sp):
                continue
            if payload is None:
                payload = dict(common)
                payload["s"] = everyone
            socketio.emit("state", payload, to=sp.sid)


def game_loop():
    next_t = time.monotonic()
    while True:
        connected = 0
        watchers = 0
        try:
            now = now_ts()
            with G:
                connected = sum(1 for p in players.values() if p.connected)
                watchers = len(specs)
                if connected == 0 and watchers == 0:
                    maintain_round(now, idle=True)
                    cleanup(now)
                else:
                    # chỉ có khán giả: vẫn chạy để họ thấy đồng hồ/câu hỏi, nhưng không đếm giờ câu hỏi
                    game_tick(now, idle=(connected == 0))
        except Exception:
            traceback.print_exc()
        next_t += TICK
        delay = next_t - time.monotonic()
        if delay < 0:
            next_t = time.monotonic()
            delay = 0
        socketio.sleep(delay if (connected or watchers) else max(delay, 0.4))


# =========================================
# Socket.IO
# =========================================
def join_ack(p):
    return {
        "ok": True, "id": p.id, "name": p.name, "W": W, "tick": TICK_MS, "heartsMax": HEARTS_MAX,
        "hearts": p.hearts, "score": p.score, "dead": p.dead,
        "best": best_all.get(p.key, [p.name, 0])[1], "ir": INTEREST_R, "map": MAP_ROWS, "grow": GROW, "maxLen": MAX_LEN, "is": ITEM_SIZE, "hs": HEART_SIZE,
    }


@socketio.on("join")
def on_join(data):
    sid = request.sid
    data = data if isinstance(data, dict) else {}
    name, err = clean_name(data.get("name"))
    if err:
        return {"ok": False, "error": err}
    token = str(data.get("token", ""))[:64]
    key = name_key(name)
    now = now_ts()
    with G:
        old_pid = by_sid.get(sid)
        if old_pid is not None and old_pid in players and players[old_pid].key != key:
            return {"ok": False, "error": "Bạn đang chơi bằng tên khác rồi"}
        pid = by_key.get(key)
        if pid is not None:
            p = players[pid]
            if not token or p.token != token:
                return {"ok": False, "error": "Tên này đang có người dùng, hãy chọn tên khác"}
            if p.sid and p.sid != sid:
                by_sid.pop(p.sid, None)
                socketio.emit("kicked", {"reason": "Tài khoản vừa đăng nhập ở nơi khác"}, to=p.sid)
            p.sid = sid
            p.connected = True
            p.expire = None
            p.name = name
        else:
            if len(players) >= MAX_PLAYERS:
                return {"ok": False, "error": "Phòng đã đầy, hãy thử lại sau ít phút"}
            used = {q.color for q in players.values()}
            free = [c for c in range(NUM_COLORS) if c not in used] or list(range(NUM_COLORS))
            p = Player(S.next_id, sid, name, key, token, random.choice(free))
            S.next_id += 1
            players[p.id] = p
            by_key[key] = p.id
            feed(f"{p.name} vào phòng")
        by_sid[sid] = p.id
        specs.pop(sid, None)
        p.last_input = now
        p.acked = S.tick
        p.ack_seen = False
        p.last_sent = 0
        join_room(ROOM)
        if not p.dead and not p.alive:
            spawn_snake(p, now)
        if R["q"] is not None:
            socketio.emit("question", question_payload(), to=sid)
            if R["st"] == "between" and R["last_end"]:
                le = dict(R["last_end"])
                le["left"] = round(max(0.0, R["between_until"] - now), 1)
                socketio.emit("round_end", le, to=sid)
        return join_ack(p)


def _player_of(sid):
    pid = by_sid.get(sid)
    return players.get(pid) if pid is not None else None


REWIND_MAX = env_int("REWIND_MAX", 6)   # bù trễ mạng: cho phép "rẽ lùi" tối đa bấy nhiêu bước


def try_rewind(p, d, hx, hy):
    """Client báo đã bấm rẽ khi thấy đầu rắn ở ô (hx, hy), nhưng lệnh tới muộn nên đầu thật đã đi tiếp vài bước.
    Nếu ô đó vẫn nằm trong vài đốt đầu của thân (thân chính là lịch sử đường đi), viết lại đoạn đường để rắn
    rẽ đúng tại ô đó, miễn là đường mới còn trống. Không hợp lệ thì trả False và xử lý như bình thường."""
    s = p.snake
    idx = next((i for i in range(min(REWIND_MAX, len(s) - 2) + 1) if s[i] == (hx, hy)), 0)
    if idx == 0:
        return False

    def step(a, b):
        dx, dy = (a[0] - b[0]) % W, (a[1] - b[1]) % W
        return (dx if dx <= 1 else dx - W, dy if dy <= 1 else dy - W)

    v = step(s[idx], s[idx + 1])
    if abs(v[0]) + abs(v[1]) != 1 or d == v or d == (-v[0], -v[1]):
        return False
    if any(step(s[j], s[j + 1]) != v for j in range(idx)):   # giữa chừng đã rẽ rồi
        return False
    new = [((hx + d[0] * j) % W, (hy + d[1] * j) % W) for j in range(idx, 0, -1)]
    block = set(BLOCKED) | set(s[idx:])
    block |= {(i["x"], i["y"]) for i in R["items"]} | {(h["x"], h["y"]) for h in S.hearts}
    for q in players.values():
        if q.alive and q is not p:
            block.update(q.snake)
    if any(c in block for c in new):
        return False
    p.snake = new + s[idx:]
    p.dir = d
    p.queue = []
    return True


@socketio.on("dir")
def on_dir(data):
    if not isinstance(data, dict):
        return
    try:
        dx, dy = int(data.get("x")), int(data.get("y"))
    except (TypeError, ValueError):
        return
    if abs(dx) + abs(dy) != 1:
        return
    try:
        hx, hy = int(data.get("hx")), int(data.get("hy"))
    except (TypeError, ValueError):
        hx = hy = None
    with G:
        p = _player_of(request.sid)
        if not p or not p.alive:
            return
        p.last_input = now_ts()
        if hx is not None and p.snake and try_rewind(p, (dx, dy), hx, hy):
            return
        last = p.queue[-1] if p.queue else p.dir
        if (dx, dy) == last or (dx, dy) == (-last[0], -last[1]):
            return
        if len(p.queue) < 2:
            p.queue.append((dx, dy))


@socketio.on("mv")
def on_mv(data):
    if not isinstance(data, dict):
        return
    try:
        x, y, ep = int(data.get("x")), int(data.get("y")), int(data.get("ep"))
    except (TypeError, ValueError):
        return
    with G:
        p = _player_of(request.sid)
        if p and p.alive and ep == p.ep and len(p.pend) < 16:
            p.pend.append((x % W, y % W))


@socketio.on("sync")
def on_sync(_data=None):
    with G:
        p = _player_of(request.sid)
        if p and p.alive:
            p.ep += 1
            p.pend = []
            send_snake(p)


@socketio.on("away")
def on_away(_data=None):
    with G:
        p = _player_of(request.sid)
        if p and p.alive:
            drop_snake(p)


@socketio.on("back")
def on_back(_data=None):
    with G:
        p = _player_of(request.sid)
        if not p:
            return {"ok": False}
        p.last_input = now_ts()
        if not p.alive and not p.dead:
            spawn_snake(p, now_ts())
        return {"ok": True, "hearts": p.hearts, "score": p.score, "dead": p.dead}


@socketio.on("ack")
def on_ack(data):
    """Client báo tick mới nhất đã nhận (để điều tiết) và đo ping qua callback."""
    try:
        k = int(data.get("k")) if isinstance(data, dict) else 0
    except (TypeError, ValueError):
        k = 0
    with G:
        link = _player_of(request.sid) or specs.get(request.sid)
        if link is not None:
            link.ack_seen = True
            if k > link.acked:
                link.acked = k
        return {"k": S.tick}


@socketio.on("spectate")
def on_spectate(_data=None):
    sid = request.sid
    now = now_ts()
    with G:
        if sid in by_sid:
            return {"ok": False, "error": "Bạn đang chơi, hãy thoát phòng trước khi xem"}
        if sid not in specs and len(specs) >= MAX_SPECTATORS:
            return {"ok": False, "error": "Phòng xem đã đầy, hãy thử lại sau"}
        specs[sid] = Spec(sid)
        join_room(ROOM)
        if R["q"] is not None:
            socketio.emit("question", question_payload(), to=sid)
            if R["st"] == "between" and R["last_end"]:
                le = dict(R["last_end"])
                le["left"] = round(max(0.0, R["between_until"] - now), 1)
                socketio.emit("round_end", le, to=sid)
        return {"ok": True, "spec": True, "W": W, "tick": TICK_MS, "heartsMax": HEARTS_MAX, "ir": INTEREST_R, "map": MAP_ROWS, "is": ITEM_SIZE, "hs": HEART_SIZE}


@socketio.on("unspectate")
def on_unspectate(_data=None):
    with G:
        if specs.pop(request.sid, None) is not None:
            leave_room(ROOM)
    return {"ok": True}


@socketio.on("respawn")
def on_respawn(_data=None):
    with G:
        p = _player_of(request.sid)
        if not p or not p.dead:
            return {"ok": False}
        note_score(p)
        p.dead = False
        p.hearts = HEARTS_START
        p.score = 0
        p.streak = 0
        p.last_input = now_ts()
        spawn_snake(p, now_ts())
        return {"ok": True, "hearts": p.hearts, "score": p.score}


@socketio.on("leave")
def on_leave(_data=None):
    with G:
        p = _player_of(request.sid)
        if p:
            leave_room(ROOM)
            remove_player(p)


@socketio.on("disconnect")
def on_disconnect(*_args):
    sid = request.sid
    with G:
        specs.pop(sid, None)
        p = _player_of(sid)
        by_sid.pop(sid, None)
        if p and p.sid == sid:
            p.connected = False
            p.sid = None
            p.expire = now_ts() + RECONNECT_GRACE
            drop_snake(p)


# =========================================
# HTTP (kiểm tra sức khoẻ, bảng xếp hạng)
# =========================================
def _no_cache(resp):
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def _send_web(name):
    resp = send_from_directory(WEB_DIR, name, max_age=0)
    if name.endswith((".png", ".ico")):
        resp.headers["Cache-Control"] = "public, max-age=86400"
    else:
        _no_cache(resp)
    return resp


@app.route("/")
def index():
    if SERVE_WEB and os.path.isfile(os.path.join(WEB_DIR, "index.html")):
        return _send_web("index.html")
    return jsonify({"name": "Rắn Săn Đáp Án AI", "status": "ok"})


@app.route("/<path:name>")
def web_file(name):
    # Chỉ phục vụ file trong danh sách trắng WEB_FILES, mọi đường dẫn khác trả 404
    if not SERVE_WEB or name not in WEB_FILES or not os.path.isfile(os.path.join(WEB_DIR, name)):
        abort(404)
    return _send_web(name)


@app.route("/health")
def health():
    return "ok"


@app.route("/status")
def status():
    with G:
        online = sum(1 for p in players.values() if p.connected)
    return jsonify({"online": online, "spectators": len(specs), "max": MAX_PLAYERS, "top": top_best(5)})


@app.route("/leaderboard")
def leaderboard():
    return jsonify({"top": top_best(10)})


# =========================================
# Cloudflare Tunnel helpers (giữ cách làm của main.py cũ)
# =========================================
def _cloudflared_asset():
    sysname = platform.system().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64",
            "armv7l": "arm", "armv6l": "arm", "i386": "386", "i686": "386"}.get(platform.machine().lower(), "amd64")
    if sysname == "linux":
        return f"cloudflared-linux-{arch}", False
    if sysname == "windows":
        return f"cloudflared-windows-{'386' if arch == '386' else 'amd64'}.exe", False
    if sysname == "darwin":
        return f"cloudflared-darwin-{'arm64' if arch == 'arm64' else 'amd64'}.tgz", True
    return None, False


def download_cloudflared(dest_dir):
    asset, is_tgz = _cloudflared_asset()
    if not asset:
        return None
    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{asset}"
    local_name = "cloudflared.exe" if os.name == "nt" else "cloudflared"
    local_path = os.path.join(dest_dir, local_name)
    print(f"[*] Đang tải cloudflared: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        blob = resp.read()
    if len(blob) < 1_000_000:
        raise RuntimeError(f"File tải về quá nhỏ ({len(blob)} byte), có thể bị chặn mạng")
    if is_tgz:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
            member = next(m for m in tf.getmembers() if m.name.endswith("cloudflared"))
            with open(local_path, "wb") as out:
                out.write(tf.extractfile(member).read())
    else:
        with open(local_path, "wb") as out:
            out.write(blob)
    if os.name != "nt":
        os.chmod(local_path, 0o755)
    return local_path


def _cloudflared_ok(path):
    """Chạy thử `cloudflared --version` để chắc file không hỏng / sai kiến trúc."""
    try:
        r = subprocess.run([path, "--version"], capture_output=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


def ensure_cloudflared_binary():
    """Tìm cloudflared: PATH -> cạnh main.py -> tự tải. File hỏng sẽ bị xoá và tải lại."""
    found = shutil.which("cloudflared")
    if found and _cloudflared_ok(found):
        return found
    local_name = "cloudflared.exe" if os.name == "nt" else "cloudflared"
    local_path = os.path.join(BASE_DIR, local_name)
    if os.path.exists(local_path):
        if _cloudflared_ok(local_path):
            return local_path
        print(f"[!] {local_name} bị hỏng hoặc không chạy được, đang xoá và tải lại...")
        try:
            os.remove(local_path)
        except OSError as e:
            print(f"[!] Không xoá được {local_path}: {e}")
            return None
    try:
        path = download_cloudflared(BASE_DIR)
        if path and _cloudflared_ok(path):
            return path
        print("[!] File cloudflared tải về không chạy được.")
        if path and os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"[!] Không thể tự động tải cloudflared: {e}")
    return None


def write_cloudflared_config():
    config_path = os.path.join(BASE_DIR, "config.yml")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(
            f"tunnel: {TUNNEL_TOKEN}\n\n"
            "protocol: http2\n"
            "ingress:\n"
            f"  - hostname: {TUNNEL_HOST}\n"
            f"    service: http://{HOST}:{PORT}\n"
            "  - service: http_status:404\n"
        )
    return config_path


def launch_cloudflared(bin_path):
    if TUNNEL_TOKEN and TUNNEL_HOST:
        config_path = write_cloudflared_config()
        cmd = [bin_path, "tunnel", "--no-autoupdate", "--config", config_path, "run", "--token", TUNNEL_TOKEN]
    else:
        if TUNNEL_TOKEN or TUNNEL_HOST:
            print("[!] Thiếu TUNNEL_TOKEN hoặc TUNNEL_HOST - dùng domain tạm trycloudflare.com.")
        cmd = [bin_path, "tunnel", "--protocol", "http2", "--no-autoupdate", "--url", f"http://{HOST}:{PORT}"]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")


def monitor_cloudflared(proc):
    global _cloudflared_url
    ansi = re.compile(r"\x1b\[[0-9;]*[mK]")
    try:
        with proc.stdout:
            for line in iter(proc.stdout.readline, ""):
                clean = ansi.sub("", line).strip()
                if not clean:
                    continue
                print(f"[CLOUDFLARED] {clean}")
                if TUNNEL_TOKEN and TUNNEL_HOST:
                    if _cloudflared_url is None and re.search(r"[Rr]egistered tunnel connection", clean):
                        _cloudflared_url = TUNNEL_HOST
                        print("\n" + "=" * 60)
                        print(f" Game server đang chạy tại: https://{TUNNEL_HOST}")
                        print("=" * 60 + "\n")
                    continue
                m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", clean)
                if m and m.group(0) != _cloudflared_url:
                    _cloudflared_url = m.group(0)
                    print("\n" + "=" * 60)
                    print(f" Game server đang chạy tại: {_cloudflared_url}")
                    print("=" * 60 + "\n")
    except Exception:
        pass


def start_tunnel_and_watchdog():
    global _cloudflared_proc
    bin_path = ensure_cloudflared_binary()
    if not bin_path:
        print("[!] TUNNEL=true nhưng không tìm được/tải được cloudflared. Bỏ qua tunnel.")
        return
    _cloudflared_proc = launch_cloudflared(bin_path)
    threading.Thread(target=monitor_cloudflared, args=(_cloudflared_proc,), daemon=True).start()
    while True:
        time.sleep(1)
        if _cloudflared_proc.poll() is not None:
            print("[!] cloudflared dừng đột ngột, đang khởi động lại...")
            time.sleep(2)
            _cloudflared_proc = launch_cloudflared(bin_path)
            threading.Thread(target=monitor_cloudflared, args=(_cloudflared_proc,), daemon=True).start()


def stop_tunnel():
    if _cloudflared_proc is not None:
        try:
            _cloudflared_proc.terminate()
        except Exception:
            pass


class NoDelayHandler(WSGIRequestHandler):
    """Tắt thuật toán Nagle: gói state/dir nhỏ được gửi ngay, không bị gom chờ ~40ms."""

    def setup(self):
        super().setup()
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            sk.connect(("10.255.255.255", 1))
            return sk.getsockname()[0]
    except Exception:
        return None


def shutdown_save():
    try:
        with G:
            for p in players.values():
                note_score(p)
        flush_best()
    except Exception:
        pass


# ---- HTTPS trực tiếp (cert Let's Encrypt) ----
HTTPS_CERT = os.getenv("HTTPS_CERT", "").strip()
HTTPS_KEY = os.getenv("HTTPS_KEY", "").strip()
CERT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".certs")
HTTPS_NAMES = []


def _resolve_pem(spec, name):
    kind, _, val = spec.partition(";")
    kind, val = kind.strip().lower(), val.strip()
    if kind == "file":
        return val
    if kind == "url":
        os.makedirs(CERT_DIR, exist_ok=True)
        dest = os.path.join(CERT_DIR, name)
        req = urllib.request.Request(val, headers={"User-Agent": "snake-ai"})
        with urllib.request.urlopen(req, timeout=20) as r, open(dest, "wb") as f:
            f.write(r.read())
        return dest
    raise ValueError(f"định dạng không hợp lệ: {spec!r}")


def cert_names(path):
    """Các tên miền (SAN) ghi trong cert, để hiển thị cho người dùng. Lỗi thì trả về []."""
    try:
        import ssl
        info = ssl._ssl._test_decode_cert(path)
        return [v for k, v in info.get("subjectAltName", ()) if k == "DNS"]
    except Exception:
        return []


def build_ssl_context():
    if not HTTPS_CERT or HTTPS_CERT.lower() == "none":
        return None
    key_spec = HTTPS_KEY
    if not key_spec and HTTPS_CERT.endswith("fullchain.pem"):
        key_spec = HTTPS_CERT[: -len("fullchain.pem")] + "privkey.pem"
    if not key_spec:
        print("[!] Có HTTPS_CERT nhưng thiếu HTTPS_KEY - chạy http.")
        return None
    try:
        import ssl
        cert = _resolve_pem(HTTPS_CERT, "fullchain.pem")
        key = _resolve_pem(key_spec, "privkey.pem")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        global HTTPS_NAMES
        HTTPS_NAMES = cert_names(cert)
        return ctx
    except Exception as e:
        print(f"[!] Không nạp được cert ({e}) - chạy http.")
        return None


init_db()
load_questions(force=True)
_loop_started = False


def start_game_loop():
    global _loop_started
    if not _loop_started:
        _loop_started = True
        socketio.start_background_task(game_loop)


if __name__ == "__main__":
    print(f"[*] Bản đồ {W}x{W}, tick {TICK_MS}ms, tối đa {MAX_PLAYERS} người, tim {HEARTS_START}/{HEARTS_MAX}")
    print(f"[*] CORS: {'cho phép mọi nguồn (*)' if ALLOW_ALL else ', '.join(ALLOWED_LIST)}")
    print(f"[*] Host: {'chấp nhận mọi Host' if ALLOW_ANY_HOST else 'chỉ chấp nhận ' + ', '.join(ALLOWED_HOSTS)}")
    if SERVE_WEB and os.path.isfile(os.path.join(WEB_DIR, "index.html")):
        print(f"[*] Chạy nội bộ: mở http://{'127.0.0.1' if HOST in ('0.0.0.0', '::') else HOST}:{PORT}/")
        if HOST in ("0.0.0.0", "::"):
            ip = lan_ip()
            if ip:
                print(f"[*] Máy khác trong cùng mạng LAN/Wi-Fi mở: http://{ip}:{PORT}/")
        else:
            print("[*] (Muốn máy khác trong mạng LAN vào được: đặt HOST=0.0.0.0 trong .env)")
    else:
        print("[*] Không tìm thấy index.html hoặc SERVE_WEB=false: chỉ chạy API/Socket.IO.")
    start_game_loop()

    if TUNNEL_ENABLED:
        threading.Thread(target=start_tunnel_and_watchdog, daemon=True).start()
    else:
        print("[*] TUNNEL=false - không chạy cloudflared, chỉ phục vụ nội bộ.")

    ssl_ctx = build_ssl_context()
    run_kwargs = {}
    if ssl_ctx:
        run_kwargs["ssl_context"] = ssl_ctx
        names = ", ".join(HTTPS_NAMES) if HTTPS_NAMES else "(không đọc được tên miền từ cert)"
        print(f"[*] HTTPS bật, cổng {PORT}. Cert hợp lệ cho: {names}")
        print("[*] Phải truy cập bằng đúng một trong các tên miền trên (không phải IP).")

    try:
        socketio.run(app, host=HOST, port=PORT, debug=False, allow_unsafe_werkzeug=True,
                     request_handler=NoDelayHandler, **run_kwargs)
    except KeyboardInterrupt:
        print("\n[*] Nhận Ctrl+C - đang thoát chương trình...")
        stop_tunnel()
        shutdown_save()
        os._exit(0)
    except Exception:
        stop_tunnel()
        shutdown_save()
        raise
    else:
        stop_tunnel()
        shutdown_save()