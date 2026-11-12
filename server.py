"""CCA-F open course, with optional accounts that only save a learner's own progress.

Anyone can read the course without signing in; their ticks, highlights and notes then stay in that
browser, as the course always did. Signing in (or creating an account, open to anyone) keeps the
same record on the server under that account, so it follows the learner to any browser. Nobody else
sees it: there is no admin page and no tracking.

The course page is Mohammed Mustafa's, unchanged on disk. It already knows how to sync its reading
record to a server (`/reading`), a path it uses beside its tutor. The few lines swapped as it is
served (SWAPS) keep the tutor off and run that sync whenever the learner is signed in.

Standard library only. Data lives in CCAF_DATA_DIR (a volume in production):
  users.json      email -> {id, pw (pbkdf2), created}
  sessions.json   session id hash -> {uid, csrf, expires}
  progress/<id>.json   the page's reading record, as it sends it
"""
import hashlib, hmac, html, json, os, re, secrets, sys, threading, time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.environ.get("CCAF_SITE_DIR") or HERE
DATA = os.path.abspath(os.environ.get("CCAF_DATA_DIR") or os.path.join(HERE, "data"))
PORT = int(os.environ.get("PORT") or "8080")
HOST = os.environ.get("CCAF_HOST") or "0.0.0.0"
COOKIE_SECURE = os.environ.get("CCAF_COOKIE_SECURE", "1") != "0"
EXAM = "Claude_Certified_Architect_-_Foundations__Practice_Exam__Study_Mode_.html"
SESSION_DAYS = 90
MAX_READING = 2 * 1024 * 1024
USERS_F, SESSIONS_F = os.path.join(DATA, "users.json"), os.path.join(DATA, "sessions.json")
lock = threading.RLock()
failures = {}

# (count, from, to). Each must match exactly that many times, or the server refuses to start rather
# than serve a page that mixes two learners' records or shows a tutor with nothing behind it.
SWAPS = (
    # Signed in, the browser copy is kept per account, so two people sharing a browser do not mix.
    # The first time an account is used here it starts from what this browser did before signing in.
    (1, "var STORAGE_KEY = 'ccaf_path_v1';",
        "var STORAGE_KEY = 'ccaf_path_v1' + ('__UID__'.charAt(0) === '_' ? '' : '_u__UID__');"),
    (1, "try { raw = window.localStorage.getItem(STORAGE_KEY); }",
        "try { raw = window.localStorage.getItem(STORAGE_KEY) || window.localStorage.getItem('ccaf_path_v1'); }"),
    (1, "var tutorAvailable = RELAY_TOKEN.charAt(0) !== '_';", "var tutorAvailable = false;"),
    (1, "var tutorLive = false;", "var tutorLive = false, syncLive = false;"),
    (2, "if (!tutorLive || !readingReady) return;", "if (!(tutorLive || syncLive) || !readingReady) return;"),
    (1, "function tutorBoot() {\n    if (!tutorAvailable) return;",
        "function tutorBoot() {\n    syncLive = RELAY_TOKEN.charAt(0) !== '_'; if (syncLive) readingBoot(); return;"),
    (1, "Progress loaded from this course folder \\u2014 it is shared by every browser on this computer.",
        "Progress loaded from your account."),
    (1, "    } else {\n      h += '<p class=\"dialog-note\">Your progress, highlights and notes are saved <strong>in this browser only</strong> ' +",
        "    } else if (syncLive) {\n      h += '<p class=\"dialog-note\">You are signed in, so your progress, highlights and notes are saved "
        "<strong>to your account</strong> and every browser you sign in from shows them. Nobody else can see them.</p>';\n"
        "    } else {\n      h += '<p class=\"dialog-note\">Your progress, highlights and notes are saved <strong>in this browser only</strong> ' +"),
    (1, "Running the tutor keeps them in the course folder ' +\n        'instead, where every browser can see them.",
        "Sign in (bottom left) to keep them ' +\n        'in an account instead, so every browser you use shows them."),
)


def now():
    return datetime.now(timezone.utc)


def iso(dt=None):
    return (dt or now()).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    os.replace(tmp, path)


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def hash_pw(pw):
    salt = secrets.token_hex(16)
    return "pbkdf2$%s$%s" % (salt, hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200000).hex())


def check_pw(pw, stored):
    try:
        _, salt, h = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200000).hex(), h)


def throttled(key):
    with lock:
        hits = [t for t in failures.get(key, []) if t > time.time() - 900]
        failures[key] = hits
        return len(hits) >= 10


def note_failure(key):
    with lock:
        failures.setdefault(key, []).append(time.time())


def load_page():
    with open(os.path.join(SITE, "index.html"), encoding="utf-8") as fh:
        page = fh.read().replace("\r\n", "\n")
    bad = [a[:50] for n, a, _ in SWAPS if page.count(a) != n]
    if bad or "'__RELAY_TOKEN__'" not in page:
        sys.exit("index.html has changed shape; update SWAPS in server.py: %s" % (bad or "__RELAY_TOKEN__"))
    for _, a, b in SWAPS:
        page = page.replace(a, b)
    return page


PAGE = None
EXAM_BYTES = None

CSS = """:root{--bg:#f6f4ee;--fg:#1c1b18;--mut:#6b675e;--card:#fbfaf6;--line:#e2ddd0;--acc:#2f5d50;--bad:#a33b2b}
@media (prefers-color-scheme:dark){:root{--bg:#15140f;--fg:#ece8dc;--mut:#a39e90;--card:#1d1c16;--line:#34322a;--acc:#8cc2b0;--bad:#f0907e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 Georgia,'Iowan Old Style',serif}
main{max-width:400px;margin:9vh auto 0;padding:0 16px}h1{font-size:26px;font-weight:600;margin:0 0 6px}
.brand{font:12px/1 system-ui,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:var(--mut);margin:0 0 18px}
p{margin:0 0 14px}.mut{color:var(--mut);font-size:14px}.bad{color:var(--bad);font:14px system-ui,sans-serif}
label{display:block;font:13px system-ui,sans-serif;color:var(--mut);margin:14px 0 5px}
input{width:100%;padding:10px 11px;border:1px solid var(--line);border-radius:7px;background:var(--card);color:var(--fg);font:16px system-ui,sans-serif}
input:focus{outline:2px solid var(--acc);outline-offset:1px}
button{width:100%;margin-top:20px;padding:11px;border:0;border-radius:7px;background:var(--acc);color:var(--bg);font:600 15px system-ui,sans-serif;cursor:pointer}
a{color:var(--acc)}.alt{margin-top:22px;font:14px system-ui,sans-serif}"""


def shell(title, body):
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>%s</title>"
            "<style>%s</style></head><body><main><p class=\"brand\">CCA-F Learning Path</p>%s</main></body></html>"
            % (html.escape(title), CSS, body)).encode("utf-8")


def bar(user, csrf):
    style = ("position:fixed;left:10px;bottom:10px;z-index:2147483000;font:12px/1.3 system-ui,sans-serif;"
             "background:rgba(28,27,24,.88);color:#ece8dc;border-radius:8px;padding:6px 10px;display:flex;"
             "gap:10px;align-items:center")
    if not user:
        return ('<div id="ccaf-acct" style="%s"><span>Progress is saved in this browser.</span>'
                '<a href="/login" style="color:#a8d5c5">Sign in to keep it</a></div>' % style)
    return ('<div id="ccaf-acct" style="%s"><span>Saved to %s</span>'
            '<form method="post" action="/logout" style="margin:0"><input type="hidden" name="csrf" value="%s">'
            '<button style="all:unset;cursor:pointer;color:#a8d5c5">Sign out</button></form></div>'
            % (style, html.escape(user["email"]), csrf))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ccaf"
    sys_version = ""

    def log_message(self, fmt, *args):
        sys.stdout.write("%s %s\n" % (self.command, self.path.split("?")[0][:60]))

    def client_ip(self):
        fwd = self.headers.get("X-Forwarded-For") or ""
        return (fwd.split(",")[-1].strip() if fwd else "") or self.client_address[0]

    def cookie(self):
        m = re.search(r"(?:^|;\s*)ccaf_sid=([A-Za-z0-9_\-]+)", self.headers.get("Cookie") or "")
        return m.group(1) if m else ""

    def me(self):
        sid = self.cookie()
        if not sid:
            return None, None
        with lock:
            s = load(SESSIONS_F, {}).get(sha(sid))
            if not s or s["expires"] < iso():
                return None, None
            u = next((dict(v, email=k) for k, v in load(USERS_F, {}).items() if v["id"] == s["uid"]), None)
        return (u, s["csrf"]) if u else (None, None)

    def send(self, code, ctype, body, headers=()):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def redirect(self, where, headers=()):
        self.send(303, "text/plain", b"", [("Location", where)] + list(headers))

    def set_cookie(self, sid, age):
        return ("Set-Cookie", "ccaf_sid=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax%s"
                % (sid, age, "; Secure" if COOKIE_SECURE else ""))

    def body(self, cap):
        n = int(self.headers.get("Content-Length") or 0)
        if n > cap:
            return None
        return self.rfile.read(n) if n else b""

    def form(self):
        raw = self.body(16384)
        return None if raw is None else {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/healthz":
            return self.send(200, "text/plain", b"ok")
        if path in ("/", "/index.html"):
            u, csrf = self.me()
            page = PAGE.replace("__RELAY_TOKEN__", csrf if u else "__RELAY_TOKEN__") \
                       .replace("__UID__", u["id"] if u else "__UID__")
            i = page.rfind("</body>")
            page = page[:i] + bar(u, csrf) + page[i:]
            return self.send(200, "text/html; charset=utf-8", page)
        if path == "/" + EXAM and EXAM_BYTES:
            return self.send(200, "text/html; charset=utf-8", EXAM_BYTES)
        if path == "/login":
            return self.login_page()
        if path == "/signup":
            return self.signup_page()
        if path == "/reading":
            u, csrf = self.me()
            if not u or not hmac.compare_digest(self.headers.get("X-CCAF-Token") or "", csrf):
                return self.send(403, "text/plain", b"sign in first")
            return self.send(200, "application/json", json.dumps(
                {"ok": True, "state": load(os.path.join(DATA, "progress", u["id"] + ".json"), None)}))
        self.send(404, "text/plain", b"Not found")

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/reading":
            return self.reading_post()
        f = self.form()
        if f is None:
            return self.send(413, "text/plain", b"too large")
        if path == "/login":
            return self.login_post(f)
        if path == "/signup":
            return self.signup_post(f)
        if path == "/logout":
            u, csrf = self.me()
            if u and hmac.compare_digest(f.get("csrf") or "", csrf):
                with lock:
                    s = load(SESSIONS_F, {})
                    s.pop(sha(self.cookie()), None)
                    save(SESSIONS_F, s)
            return self.redirect("/", [self.set_cookie("", 0)])
        self.send(404, "text/plain", b"Not found")

    def reading_post(self):
        u, csrf = self.me()
        raw = self.body(MAX_READING)
        try:
            req = json.loads(raw or b"{}")
        except ValueError:
            req = None
        if not isinstance(req, dict) or not isinstance(req.get("state"), dict):
            return self.send(400, "text/plain", b"bad request")
        if not u or not hmac.compare_digest(str(req.get("token") or ""), csrf):
            return self.send(403, "text/plain", b"sign in first")
        with lock:
            save(os.path.join(DATA, "progress", u["id"] + ".json"), req["state"])
        self.send(200, "application/json", b'{"ok":true}')

    def start_session(self, uid):
        sid = secrets.token_urlsafe(32)
        with lock:
            s = {k: v for k, v in load(SESSIONS_F, {}).items() if v["expires"] > iso()}
            # The page treats a token starting with "_" as "no server", so never start with one.
            s[sha(sid)] = {"uid": uid, "csrf": "k" + secrets.token_urlsafe(24),
                           "expires": iso(now() + timedelta(days=SESSION_DAYS))}
            save(SESSIONS_F, s)
        self.redirect("/", [self.set_cookie(sid, SESSION_DAYS * 86400)])

    def login_page(self, error="", email=""):
        self.send(200, "text/html; charset=utf-8", shell("Sign in", """<h1>Sign in</h1>
<p class="mut">To keep your progress, highlights and notes in your account.</p>%s
<form method="post" action="/login"><label>Email</label><input type="email" name="email" value="%s" required autocomplete="email">
<label>Password</label><input type="password" name="password" required autocomplete="current-password">
<button>Sign in</button></form>
<p class="alt">No account? <a href="/signup">Create one</a> &middot; <a href="/">Back to the course</a></p>"""
            % ('<p class="bad">%s</p>' % html.escape(error) if error else "", html.escape(email))))

    def signup_page(self, error="", email=""):
        self.send(200, "text/html; charset=utf-8", shell("Create an account", """<h1>Create an account</h1>
<p class="mut">It only saves your own progress. Nobody else sees it.</p>%s
<form method="post" action="/signup"><label>Email</label><input type="email" name="email" value="%s" required autocomplete="email">
<label>Password, at least 8 characters</label><input type="password" name="password" required minlength="8" autocomplete="new-password">
<button>Create account</button></form>
<p class="mut" style="margin-top:14px">What you already did in this browser is kept and moves into the account.</p>
<p class="alt">Have one? <a href="/login">Sign in</a> &middot; <a href="/">Back to the course</a></p>"""
            % ('<p class="bad">%s</p>' % html.escape(error) if error else "", html.escape(email))))

    def login_post(self, f):
        email, pw = (f.get("email") or "").strip().lower(), f.get("password") or ""
        keys = ("ip:" + self.client_ip(), "em:" + email)
        if any(throttled(k) for k in keys):
            return self.login_page("Too many attempts. Wait fifteen minutes and try again.", email)
        with lock:
            u = load(USERS_F, {}).get(email)
        if not u or not check_pw(pw, u["pw"]):
            for k in keys:
                note_failure(k)
            return self.login_page("That email and password do not match.", email)
        self.start_session(u["id"])

    def signup_post(self, f):
        email, pw = (f.get("email") or "").strip().lower(), f.get("password") or ""
        ip = "su:" + self.client_ip()
        if throttled(ip):
            return self.signup_page("Too many new accounts from here. Try again later.", email)
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) or len(email) > 200:
            return self.signup_page("That does not look like an email address.", email)
        if len(pw) < 8 or len(pw) > 200:
            return self.signup_page("The password needs at least 8 characters.", email)
        with lock:
            users = load(USERS_F, {})
            if email in users:
                return self.signup_page("There is already an account for that email. Sign in instead.", email)
            uid = secrets.token_hex(8)
            users[email] = {"id": uid, "pw": hash_pw(pw), "created": iso()}
            save(USERS_F, users)
        note_failure(ip)          # counts toward the sign-up limit: ten accounts per address per 15 minutes
        self.start_session(uid)


def main():
    global PAGE, EXAM_BYTES
    os.makedirs(os.path.join(DATA, "progress"), exist_ok=True)
    PAGE = load_page()
    try:
        with open(os.path.join(SITE, EXAM), "rb") as fh:
            EXAM_BYTES = fh.read()
    except OSError:
        EXAM_BYTES = None
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print("CCA-F course on %s:%d, data in %s" % (HOST, PORT, DATA), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
