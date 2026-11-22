"""Web and mobile-web driver (Playwright, Chromium).

Emulates: viewport, pixel ratio, touch, phone user agent, orientation,
language + timezone + geolocation, dark mode, reduced motion, text size,
offline and throttled networks (Chrome DevTools protocol).
Flutter web apps draw on a canvas, so the driver switches on Flutter's
accessibility tree and reads buttons and fields from it.
"""
import functools
import http.server
import os
import socket
import threading
from pathlib import Path

from .. import presets
from .base import Driver, Element, Screen

COLLECT_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const vw = window.innerWidth, vh = window.innerHeight;
  const sel = 'a[href],button,input,textarea,select,summary,[role],[aria-label],[tabindex],flt-semantics,h1,h2,h3,label,img[alt]';
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    if (r.bottom < 0 || r.right < 0 || r.top > vh || r.left > vw) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || st.opacity === '0') {
      if (el.tagName !== 'FLT-SEMANTICS') continue;
    }
    const role = (el.getAttribute('role') || '').toLowerCase();
    const tag = el.tagName.toLowerCase();
    let kind = 'other';
    if (tag === 'a' || role === 'link') kind = 'link';
    else if (tag === 'button' || role === 'button' || role === 'menuitem' || tag === 'summary') kind = 'button';
    else if (tag === 'input' && ['checkbox','radio'].includes(el.type) || ['switch','checkbox','radio'].includes(role)) kind = 'switch';
    else if (tag === 'input' || tag === 'textarea' || tag === 'select' || role === 'textbox' || role === 'combobox' || role === 'searchbox') kind = 'field';
    else if (role === 'tab') kind = 'tab';
    else if (tag === 'img' || role === 'img') kind = 'image';
    else if (/^h[1-6]$/.test(tag) || role === 'heading' || role === 'text' || tag === 'label') kind = 'text';
    else if (tag === 'flt-semantics') {
      if (el.getAttribute('flt-tappable') !== null) kind = 'button';
      else kind = 'text';
    }
    let label = el.getAttribute('aria-label') || el.getAttribute('alt') || el.getAttribute('title') || '';
    if (!label && el.labels && el.labels.length) label = el.labels[0].innerText;
    if (!label) label = el.getAttribute('placeholder') || '';
    if (!label && kind !== 'field') label = (el.innerText || el.textContent || '').trim();
    label = label.replace(/\s+/g, ' ').trim().slice(0, 120);
    const value = (el.value !== undefined && typeof el.value === 'string') ? el.value : '';
    if (kind === 'other' && !label) continue;
    if (kind === 'text' && !label) continue;
    const key = kind + label + Math.round(r.x) + Math.round(r.y);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({kind, label, value, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
              w: Math.round(r.width), h: Math.round(r.height),
              enabled: !(el.disabled || el.getAttribute('aria-disabled') === 'true')});
  }
  return out;
}
"""

FLUTTER_PLACEHOLDER_JS = r"""
() => {
  const p = document.querySelector('flt-semantics-placeholder');
  if (!p) return null;
  const r = p.getBoundingClientRect();
  return {x: r.x + r.width / 2, y: r.y + r.height / 2, big: r.width > 20};
}
"""

OVERFLOW_JS = r"""
() => {
  const se = document.scrollingElement || document.documentElement;
  return {scrollWidth: se.scrollWidth, innerWidth: window.innerWidth};
}
"""


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve_dir(directory):
    """Serve a built web app (e.g. Flutter's build/web) on a free local port."""
    port = _free_port()
    handler = functools.partial(_QuietHandler, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{port}/"


class WebDriver(Driver):
    platform = "web"
    _shared = {}   # one browser process and one static server per run

    def start(self):
        from playwright.sync_api import sync_playwright

        cell, app = self.cell, self.app
        dev = dict(presets.WEB_DEVICES.get(cell.device) or {})
        if not dev:
            raise SystemExit(f"Unknown web device '{cell.device}'. Add it under presets.web in qa.yml.")
        w, h = dev["width"], dev["height"]
        if cell.orientation == "landscape":
            w, h = h, w
        loc = presets.LOCALES.get(cell.locale, {})

        if "pw" not in self._shared:
            self._shared["pw"] = sync_playwright().start()
            exe = os.environ.get("TESTFLOCK_CHROMIUM") or (app.get("chromium") or None)
            if not exe and Path("/opt/pw-browsers/chromium").exists():
                exe = "/opt/pw-browsers/chromium"
            self._shared["browser"] = self._shared["pw"].chromium.launch(executable_path=exe)
        if app.get("serve") and "url" not in self._shared:
            root = Path(self.cfg["_dir"]) / app["serve"]
            self._shared["server"], self._shared["url"] = serve_dir(root)
        self.url = app.get("url") or self._shared.get("url")
        if not self.url:
            raise SystemExit("app.web needs `url` (a running site) or `serve` (a built folder).")

        ctx_args = dict(
            viewport={"width": w, "height": h}, device_scale_factor=dev.get("dpr", 1),
            is_mobile=dev.get("mobile", False), has_touch=dev.get("touch", False),
            locale=cell.locale, timezone_id=loc.get("tz"),
            color_scheme="dark" if cell.theme == "dark" else "light",
            reduced_motion="reduce" if cell.extra.get("reduced_motion") else "no-preference",
        )
        if dev.get("ua"):
            ctx_args["user_agent"] = dev["ua"]
        if loc.get("geo"):
            ctx_args["geolocation"] = {"latitude": loc["geo"][0], "longitude": loc["geo"][1]}
            ctx_args["permissions"] = ["geolocation"]
        self.context = self._shared["browser"].new_context(**ctx_args)
        self.page = self.context.new_page()
        self.console, self.page_errors, self.failed_requests, self.pending = [], [], [], []
        # "Failed to load resource" duplicates the network listener below, which names the URL
        self.page.on("console", lambda m: m.type == "error" and not m.text.startswith("Failed to load resource")
                     and self.console.append(m.text[:300]))
        self.page.on("pageerror", lambda e: self.page_errors.append(str(e)[:300]))
        self.page.on("response", lambda r: r.status >= 400 and self.failed_requests.append(
            f"HTTP {r.status} {self._path(r.url)}"))
        self.cdp = self.context.new_cdp_session(self.page)
        # Load online first, so "offline" tests what a user sees when the
        # connection drops after the app opened (the realistic case).
        self.page.goto(self.url, wait_until="load", timeout=60000)
        self._settle(first=True)
        self._apply_text_size()
        self.set_network(cell.network)

    def _path(self, url):
        """Drop the random local port, so the same missing file groups across devices."""
        base = (self.url or "").rstrip("/")
        return url[len(base):] if base and url.startswith(base) else url[:160]

    def _settle(self, first=False):
        try:
            self.page.wait_for_load_state("networkidle", timeout=8000 if first else 3000)
        except Exception:
            pass
        self.page.wait_for_timeout(1500 if first else 600)
        # Flutter web: turn on its accessibility tree. On desktop the placeholder is a
        # 1 px button (a DOM click works); on phones it covers the screen and wants a
        # real tap in its centre.
        ph = self.page.evaluate(FLUTTER_PLACEHOLDER_JS)
        if ph:
            if ph["big"]:
                self.tap(ph["x"], ph["y"])
            else:
                self.page.eval_on_selector("flt-semantics-placeholder", "e => e.click()")
            self.page.wait_for_timeout(800)

    def _apply_text_size(self):
        scale = presets.TEXT_SIZES.get(self.cell.text_size, {}).get("scale", 1.0)
        if scale != 1.0:
            self.page.add_style_tag(content=f"html{{font-size:{int(scale * 100)}% !important}}")
            if self.page.query_selector("flt-glass-pane, flutter-view"):
                self.skipped.append("text size: Flutter web ignores the browser text size")

    def set_network(self, name):
        net = presets.NETWORKS.get(name)
        if net is None:
            raise SystemExit(f"Unknown network '{name}'.")
        if net.get("offline"):
            self.context.set_offline(True)
            return
        self.context.set_offline(False)
        if "down_kbps" in net:
            self.cdp.send("Network.enable")
            self.cdp.send("Network.emulateNetworkConditions", {
                "offline": False, "latency": net["latency_ms"],
                "downloadThroughput": net["down_kbps"] * 1000 / 8,
                "uploadThroughput": net["up_kbps"] * 1000 / 8})
        else:
            self.cdp.send("Network.emulateNetworkConditions", {
                "offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})

    def stop(self):
        try:
            self.context.close()
        except Exception:
            pass

    @classmethod
    def shutdown(cls):
        if "browser" in cls._shared:
            cls._shared["browser"].close()
            cls._shared["pw"].stop()
        if "server" in cls._shared:
            cls._shared["server"].shutdown()
        cls._shared.clear()

    def relaunch(self):
        try:
            self.page.reload(wait_until="load", timeout=30000)
        except Exception as e:
            if not presets.NETWORKS.get(self.cell.network, {}).get("offline"):
                raise
            # A real finding: the app cannot reopen without a connection.
            self.pending.append(f"offline: the app does not reopen offline ({str(e).splitlines()[0][:120]})")
            self.context.set_offline(False)
            self.page.goto(self.url, wait_until="load", timeout=60000)
            self.context.set_offline(True)
        self._settle(first=True)

    def screen(self, name=None):
        self._settle()
        path = Path(self.outdir) / f"{self.next_name(name)}.png"
        self.page.screenshot(path=str(path), scale="css")
        vp = self.page.viewport_size
        els = [Element(**e) for e in self.page.evaluate(COLLECT_JS)]
        s = Screen(str(path), vp["width"], vp["height"], els, unit=1.0)
        ov = self.page.evaluate(OVERFLOW_JS)
        if ov["scrollWidth"] > ov["innerWidth"] + 2:
            s.notes.append(f"overflow: page is {ov['scrollWidth']}px wide on a {ov['innerWidth']}px screen (sideways scroll)")
        for e in self.page_errors:
            s.notes.append(f"crash: uncaught error: {e}")
        for e in self.console:
            s.notes.append(f"console: {e}")
        for e in self.failed_requests:
            s.notes.append(f"network: {e}")
        s.notes += self.pending
        self.pending.clear()
        self.failed_requests.clear()
        self.page_errors.clear()
        self.console.clear()
        return s

    def tap(self, x, y):
        if (presets.WEB_DEVICES.get(self.cell.device) or {}).get("touch"):
            self.page.touchscreen.tap(x, y)
        else:
            self.page.mouse.click(x, y)

    def long_press(self, x, y):
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.page.wait_for_timeout(900)
        self.page.mouse.up()

    def type_text(self, text):
        self.page.keyboard.type(text, delay=20)

    def press_enter(self):
        self.page.keyboard.press("Enter")

    def back(self):
        self.page.go_back(wait_until="load")

    def scroll(self, direction="down"):
        vp = self.page.viewport_size
        self.page.mouse.move(vp["width"] / 2, vp["height"] / 2)
        dy = {"down": 0.7, "up": -0.7}.get(direction, 0.7) * vp["height"]
        self.page.mouse.wheel(0, dy)

    def open_url(self, url):
        if url.startswith("/"):
            url = self.url.rstrip("/") + url
        self.page.goto(url, wait_until="load")
