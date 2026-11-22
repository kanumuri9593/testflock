"""iOS Simulator driver (macOS only): xcrun simctl + AXe (brew install cameroncooke/axe/axe).

Emulates: device type, language and region, dark mode, Dynamic Type size,
location, a clean status bar (9:41, full battery).
Limits, reported in the run instead of failing it:
- Network: the Simulator shares the Mac's network. Offline and slow networks
  need Apple's Network Link Conditioner, which changes the whole Mac, so they
  are skipped unless `app.ios.network_link_conditioner: true`.
- Orientation: rotated through the Simulator app's menu (needs the
  Simulator window and Accessibility permission for Terminal).
"""
import json
import os
import plistlib
import subprocess
import time
from pathlib import Path

from .. import presets
from .base import Driver, Element, Screen


def run(*args, timeout=120, check=False):
    r = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(args)} failed: {r.stderr[:300]}")
    return r.stdout


def simctl(*args, **kw):
    return run("xcrun", "simctl", *args, **kw)


class IOSDriver(Driver):
    platform = "ios"

    def start(self):
        cell, app = self.cell, self.app
        dev = presets.IOS_DEVICES.get(cell.device, {"type": cell.device})
        self.points_w = None
        self.udid = os.environ.get("TESTFLOCK_UDID") or self._create(dev["type"])
        lang = cell.locale.split("-")[0]
        region = cell.locale.replace("-", "_")
        simctl("spawn", self.udid, "defaults", "write", "-g", "AppleLanguages", "-array", lang)
        simctl("spawn", self.udid, "defaults", "write", "-g", "AppleLocale", "-string", region)
        simctl("boot", self.udid)
        simctl("bootstatus", self.udid, "-b", timeout=600)
        simctl("ui", self.udid, "appearance", "dark" if cell.theme == "dark" else "light")
        size = presets.TEXT_SIZES.get(cell.text_size, {}).get("ios", "large")
        simctl("ui", self.udid, "content_size", size)
        simctl("status_bar", self.udid, "override", "--time", "9:41", "--batteryState", "charged",
               "--batteryLevel", "100", "--cellularBars", "4", "--wifiBars", "3")
        geo = presets.LOCALES.get(cell.locale, {}).get("geo")
        if geo:
            simctl("location", self.udid, "set", f"{geo[0]},{geo[1]}")
        app_path = app.get("app")
        self.bundle = app.get("bundle_id")
        if app_path:
            app_path = str(Path(self.cfg["_dir"]) / app_path)
            simctl("install", self.udid, app_path, check=True)
            with open(Path(app_path) / "Info.plist", "rb") as f:
                self.bundle = plistlib.load(f).get("CFBundleIdentifier", self.bundle)
        if not self.bundle:
            raise SystemExit("app.ios needs `app` (a .app built for the Simulator) or `bundle_id`.")
        for perm in app.get("grant", []):   # e.g. photos, camera, location
            simctl("privacy", self.udid, "grant", perm, self.bundle)
        if cell.orientation == "landscape":
            self._rotate()
        self.relaunch()
        self.set_network(cell.network)

    def _create(self, device_type):
        name = f"testflock-{device_type}".replace(" ", "-")
        devices = json.loads(simctl("list", "devices", "-j"))["devices"]
        for runtime, devs in devices.items():
            for d in devs:
                if d["name"] == name and d.get("isAvailable", True):
                    simctl("shutdown", d["udid"])
                    simctl("erase", d["udid"])
                    return d["udid"]
        runtimes = [r for r in json.loads(simctl("list", "runtimes", "-j"))["runtimes"]
                    if r.get("isAvailable") and r["name"].startswith("iOS")]
        if not runtimes:
            raise SystemExit("No iOS Simulator runtime installed (Xcode > Settings > Components).")
        rt = sorted(runtimes, key=lambda r: [int(p) for p in r["version"].split(".")])[-1]["identifier"]
        return simctl("create", name, device_type, rt, check=True).strip()

    def _rotate(self):
        script = ('tell application "Simulator" to activate\n'
                  'tell application "System Events" to tell process "Simulator" to '
                  'click menu item "Rotate Left" of menu "Device" of menu bar 1')
        if subprocess.run(["osascript", "-e", script], capture_output=True).returncode:
            self.skipped.append("orientation: allow Accessibility for your terminal to rotate the Simulator")

    def set_network(self, name):
        if name == "online":
            return
        if not self.app.get("network_link_conditioner"):
            self.skipped.append(f"network {name}: iOS Simulator uses the Mac's network "
                                "(turn on Network Link Conditioner and set app.ios.network_link_conditioner)")

    def stop(self):
        if not os.environ.get("TESTFLOCK_UDID"):
            simctl("shutdown", self.udid)

    def relaunch(self):
        simctl("terminate", self.udid, self.bundle)
        time.sleep(1)
        simctl("launch", self.udid, self.bundle)
        time.sleep(float(self.app.get("launch_wait", 5)))

    def _axe(self, *args):
        return run("axe", *args, "--udid", self.udid, timeout=60)

    def screen(self, name=None):
        time.sleep(0.8)
        path = Path(self.outdir) / f"{self.next_name(name)}.png"
        simctl("io", self.udid, "screenshot", "--type=png", str(path))
        try:
            tree = json.loads(self._axe("describe-ui"))
        except (json.JSONDecodeError, FileNotFoundError):
            tree = []
        root = tree[0] if isinstance(tree, list) and tree else (tree if isinstance(tree, dict) else {})
        wpt = int((root.get("frame") or {}).get("width") or 0) or self.points_w or 393
        self.points_w = wpt
        pw, ph = _png_size(path)
        scale = pw / wpt if wpt else 3.0
        self.scale = scale
        self.points_h = round(ph / scale)
        els = []

        def walk(n):
            if isinstance(n, list):
                for c in n:
                    walk(c)
                return
            if not isinstance(n, dict):
                return
            f = n.get("frame") or {}
            t = (n.get("type") or n.get("role_description") or "").strip()
            label = (n.get("AXLabel") or n.get("title") or "").strip()
            value = str(n.get("AXValue") or "").strip()
            kind = ("field" if "Field" in t or t == "TextArea" else
                    "switch" if t in ("Switch", "CheckBox") else
                    "button" if t in ("Button", "Link", "Cell", "Tab", "MenuItem") else
                    "image" if t == "Image" else "text" if (label or value) else None)
            if kind and f.get("width", 0) > 0 and t not in ("Application", "Window", "ScrollBar"):
                els.append(Element(kind, label or value, round((f["x"] + f["width"] / 2) * scale),
                                   round((f["y"] + f["height"] / 2) * scale), round(f["width"] * scale),
                                   round(f["height"] * scale), value=value, enabled=n.get("enabled", True)))
            walk(n.get("children") or [])

        walk(tree)
        s = Screen(str(path), pw, ph, els, unit=scale)
        if self.bundle not in simctl("spawn", self.udid, "launchctl", "list"):
            s.notes.append("crash: the app is no longer running (crash or closed)")
        return s

    def tap(self, x, y):
        s = self._scale()
        self._axe("tap", "-x", str(round(x / s)), "-y", str(round(y / s)))

    def long_press(self, x, y):
        s = self._scale()
        self._axe("touch", "-x", str(round(x / s)), "-y", str(round(y / s)), "--down", "--up", "--delay", "1")

    def _scale(self):
        return getattr(self, "scale", 3.0)

    def type_text(self, text):
        self._axe("type", text)

    def press_enter(self):
        self._axe("key", "40")

    def back(self):
        w = self.points_w or 393
        self._axe("swipe", "--start-x", "2", "--start-y", "300", "--end-x", str(int(w * 0.8)),
                  "--end-y", "300", "--duration", "0.3")

    def scroll(self, direction="down"):
        w = self.points_w or 393
        h = getattr(self, "points_h", None) or int(w * 2.1)
        y1, y2 = (h * 3 // 4, h // 4) if direction == "down" else (h // 4, h * 3 // 4)
        self._axe("swipe", "--start-x", str(w // 2), "--start-y", str(y1), "--end-x", str(w // 2),
                  "--end-y", str(y2), "--duration", "0.5")

    def open_url(self, url):
        simctl("openurl", self.udid, url)


def _png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
