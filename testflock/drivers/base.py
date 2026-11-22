"""One small interface every platform implements.

Scripts, the no-AI crawler and the AI agent only talk to this interface, so a
new platform (a real phone farm, Windows, a TV) is one new file.

Coordinates are always in the screenshot's own pixels (`Screen.png`), the
driver converts them to whatever its tool needs (CSS px, points, device px).
"""
import hashlib
import re
from dataclasses import dataclass, field


@dataclass
class Element:
    kind: str            # button, field, text, link, switch, image, other
    label: str
    x: int               # centre, screenshot pixels
    y: int
    w: int
    h: int
    value: str = ""
    enabled: bool = True

    @property
    def tappable(self):
        return self.kind in ("button", "link", "switch", "field", "tab", "cell") and self.enabled

    def short(self, i):
        v = f' value="{self.value[:30]}"' if self.value and self.value != self.label else ""
        return f'[{i}] {self.kind} "{self.label[:60]}"{v} at ({self.x},{self.y}) {self.w}x{self.h}'


@dataclass
class Screen:
    png: str                       # path of the screenshot
    width: int                     # screenshot size in pixels
    height: int
    elements: list = field(default_factory=list)
    unit: float = 1.0              # screenshot pixels per platform unit (dp, pt or CSS px)
    notes: list = field(default_factory=list)  # driver warnings: crash, app closed, console errors

    def signature(self):
        """Same labels in the same places = same screen (for the crawler)."""
        key = "|".join(sorted(f"{e.kind}:{e.label}" for e in self.elements if e.label))
        return hashlib.sha1(key.encode()).hexdigest()[:10]

    def find(self, target):
        """Find an element by its label: exact, then case-insensitive, then contains, then regex /.../."""
        if isinstance(target, int):
            return self.elements[target] if 0 <= target < len(self.elements) else None
        t = str(target)
        if len(t) > 2 and t.startswith("/") and t.endswith("/"):
            rx = re.compile(t[1:-1], re.I)
            return next((e for e in self.elements if rx.search(e.label) or rx.search(e.value)), None)
        for test in (lambda e: e.label == t,
                     lambda e: e.label.lower() == t.lower(),
                     lambda e: t.lower() in e.label.lower(),
                     lambda e: t.lower() in e.value.lower()):
            hits = [e for e in self.elements if test(e)]
            if hits:
                return sorted(hits, key=lambda e: (not e.tappable, e.y))[0]
        return None

    def text(self):
        return "\n".join(e.short(i) for i, e in enumerate(self.elements))


class Driver:
    """Base class. Subclasses implement the methods that raise NotImplementedError."""

    platform = "?"
    supports = {"offline": True, "throttle": True, "orientation": True, "locale": True,
                "theme": True, "text_size": True}

    def __init__(self, cfg, cell, outdir):
        self.cfg, self.cell, self.outdir = cfg, cell, outdir
        self.app = (cfg.get("app") or {}).get(cell.platform) or {}
        self.counter = 0
        self.skipped = []          # settings this platform could not apply

    # lifecycle
    def start(self):
        raise NotImplementedError

    def stop(self):
        pass

    def relaunch(self):
        raise NotImplementedError

    # seeing
    def screen(self, name=None) -> Screen:
        raise NotImplementedError

    def next_name(self, name=None):
        self.counter += 1
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", name or "screen").strip("-")[:40]
        return f"{self.counter:03d}-{safe}"

    # acting
    def tap(self, x, y):
        raise NotImplementedError

    def long_press(self, x, y):
        self.tap(x, y)

    def type_text(self, text):
        raise NotImplementedError

    def press_enter(self):
        raise NotImplementedError

    def back(self):
        raise NotImplementedError

    def scroll(self, direction="down"):
        raise NotImplementedError

    def open_url(self, url):
        raise NotImplementedError

    def set_network(self, name):
        raise NotImplementedError

    def wait(self, seconds):
        import time
        time.sleep(float(seconds))
