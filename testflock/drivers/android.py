"""Android driver (adb). Works with an emulator or a USB phone.

In CI the emulator is booted by reactivecircus/android-emulator-runner (see
templates/); locally, start one (`emulator -avd <name>`) or plug in a phone.
Set ANDROID_SERIAL to pick a device when several are connected.

Emulates: language (needs an emulator image with root, e.g. google_apis),
orientation, dark mode, font scale, offline (airplane mode) and slow
networks (emulator console: `adb emu network speed/delay`, emulator only).
"""
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .. import presets
from .base import Driver, Element, Screen


def adb(*args, check=False, timeout=60, binary=False):
    cmd = ["adb"]
    if os.environ.get("ANDROID_SERIAL"):
        cmd += ["-s", os.environ["ANDROID_SERIAL"]]
    r = subprocess.run(cmd + list(args), capture_output=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"adb {' '.join(args)} failed: {r.stderr.decode(errors='replace')[:300]}")
    return r.stdout if binary else r.stdout.decode(errors="replace")


def sh(cmd, **kw):
    return adb("shell", cmd, **kw)


class AndroidDriver(Driver):
    platform = "android"

    def start(self):
        cell, app = self.cell, self.app
        self.pkg = app.get("package")
        if not self.pkg:
            raise SystemExit("app.android needs `package` (applicationId).")
        adb("wait-for-device", timeout=180)
        self.is_emulator = "emulator" in adb("get-serialno") or sh("getprop ro.kernel.qemu").strip() == "1"
        self._set_locale(cell.locale)
        apk = app.get("apk")
        if apk:
            apk = str(Path(self.cfg["_dir"]) / apk)
            adb("install", "-r", "-g", apk, timeout=300)
        sh("cmd uimode night " + ("yes" if cell.theme == "dark" else "no"))
        scale = presets.TEXT_SIZES.get(cell.text_size, {}).get("scale", 1.0)
        sh(f"settings put system font_scale {scale}")
        sh("settings put system accelerometer_rotation 0")
        sh("settings put system user_rotation " + ("1" if cell.orientation == "landscape" else "0"))
        geo = presets.LOCALES.get(cell.locale, {}).get("geo")
        if geo and self.is_emulator:
            adb("emu", "geo", "fix", str(geo[1]), str(geo[0]))
        if app.get("clear_data", True):
            sh(f"pm clear {self.pkg}")
            for perm in app.get("grant", []):
                sh(f"pm grant {self.pkg} {perm}")
        self.relaunch()
        self.set_network(cell.network)

    def _set_locale(self, locale):
        if sh("getprop persist.sys.locale").strip() == locale:
            return
        adb("root")
        time.sleep(2)
        adb("wait-for-device")
        out = sh(f"setprop persist.sys.locale {locale}; setprop ctl.restart zygote")
        if "denied" in out.lower():
            self.skipped.append(f"locale {locale}: needs a rooted emulator image (google_apis)")
            return
        time.sleep(8)
        adb("wait-for-device")
        for _ in range(60):
            if sh("getprop sys.boot_completed").strip() == "1":
                break
            time.sleep(2)

    def set_network(self, name):
        net = presets.NETWORKS[name]
        if net.get("offline"):
            sh("cmd connectivity airplane-mode enable")
            return
        sh("cmd connectivity airplane-mode disable")
        if not self.is_emulator:
            if net.get("android"):
                self.skipped.append(f"network {name}: throttling needs an emulator (a USB phone stays at full speed)")
            return
        adb("emu", "network", "speed", net.get("android", "full"))
        delay = {"gsm": "gprs", "edge": "edge", "umts": "umts"}.get(net.get("android", ""), "none")
        adb("emu", "network", "delay", delay)

    def relaunch(self):
        sh(f"am force-stop {self.pkg}")
        activity = self.app.get("activity")
        if activity:
            sh(f"am start -n {self.pkg}/{activity}")
        else:
            sh(f"monkey -p {self.pkg} -c android.intent.category.LAUNCHER 1")
        time.sleep(float(self.app.get("launch_wait", 4)))
        adb("logcat", "-c")

    def _running(self):
        return self.pkg in sh("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'")

    def screen(self, name=None):
        time.sleep(0.8)
        path = Path(self.outdir) / f"{self.next_name(name)}.png"
        path.write_bytes(adb("exec-out", "screencap", "-p", binary=True))
        sh("uiautomator dump /sdcard/tf-ui.xml", timeout=30)
        xml = sh("cat /sdcard/tf-ui.xml")
        els, w, h = [], 0, 0
        try:
            root = ET.fromstring(xml[xml.find("<"):])
            for n in root.iter("node"):
                b = [int(v) for v in re.findall(r"-?\d+", n.get("bounds", ""))]
                if len(b) != 4:
                    continue
                w, h = max(w, b[2]), max(h, b[3])
                label = (n.get("text") or n.get("content-desc") or "").strip()
                cls = n.get("class", "")
                if "EditText" in cls:
                    kind = "field"
                elif "Switch" in cls or "CheckBox" in cls or n.get("checkable") == "true":
                    kind = "switch"
                elif n.get("clickable") == "true":
                    kind = "button"
                elif label:
                    kind = "text"
                else:
                    continue
                if not label and kind == "button":   # name it after its first labelled child
                    label = next(((m.get("text") or m.get("content-desc")).strip() for m in n.iter("node")
                                  if (m.get("text") or m.get("content-desc") or "").strip()), "")
                els.append(Element(kind, label, (b[0] + b[2]) // 2, (b[1] + b[3]) // 2, b[2] - b[0], b[3] - b[1],
                                   value=(n.get("text") or "") if kind == "field" else "",
                                   enabled=n.get("enabled") != "false"))
        except ET.ParseError:
            pass
        density = re.findall(r"\d+", sh("wm density"))
        s = Screen(str(path), w, h, els, unit=(int(density[-1]) / 160) if density else 1.0)
        if not self._running():
            s.notes.append("crash: the app is no longer in front (crash or closed)")
        crash = adb("logcat", "-d", "-b", "crash", timeout=20)
        if self.pkg in crash:
            s.notes.append("crash: logcat crash buffer mentions the app")
            adb("logcat", "-c", "-b", "crash")
        return s

    def tap(self, x, y):
        sh(f"input tap {int(x)} {int(y)}")

    def long_press(self, x, y):
        sh(f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} 900")

    def type_text(self, text):
        # `input text` needs spaces as %s and shell characters escaped
        safe = re.sub(r"([\\\"'`$&|;<>()])", r"\\\1", text).replace(" ", "%s")
        sh(f"input text {safe}")

    def press_enter(self):
        sh("input keyevent 66")

    def back(self):
        sh("input keyevent 4")

    def scroll(self, direction="down"):
        size = re.findall(r"(\d+)x(\d+)", sh("wm size"))
        w, h = (int(size[-1][0]), int(size[-1][1])) if size else (1080, 2400)
        y1, y2 = (h * 3 // 4, h // 4) if direction == "down" else (h // 4, h * 3 // 4)
        sh(f"input swipe {w // 2} {y1} {w // 2} {y2} 400")

    def open_url(self, url):
        sh(f"am start -a android.intent.action.VIEW -d '{url}' {self.pkg}")
