"""Load qa.yml and expand it into a list of cells (one device setup each)."""
import itertools
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import presets

AXES = ("platform", "device", "locale", "orientation", "network", "theme", "text_size")

DEFAULT_MATRIX = {
    "platforms": ["web"],
    "devices": {"web": ["iphone-16", "pixel-8"], "android": ["pixel-8"], "ios": ["iphone-16"]},
    "locales": ["en-US"],
    "orientations": ["portrait"],
    "networks": ["online"],
    "themes": ["light"],
    "text_sizes": ["default"],
    "include": [],
    "exclude": [],
    "max_cells": 40,
}


@dataclass
class Cell:
    platform: str
    device: str
    locale: str = "en-US"
    orientation: str = "portrait"
    network: str = "online"
    theme: str = "light"
    text_size: str = "default"
    extra: dict = field(default_factory=dict)

    @property
    def id(self):
        parts = [self.platform, self.device, self.locale, self.orientation, self.network, self.theme, self.text_size]
        return "_".join(p.replace(" ", "-").lower() for p in parts)

    @property
    def title(self):
        bits = [self.device, self.locale]
        if self.orientation != "portrait":
            bits.append(self.orientation)
        if self.network != "online":
            bits.append(self.network)
        if self.theme != "light":
            bits.append(self.theme)
        if self.text_size != "default":
            bits.append(f"text {self.text_size}")
        return f"{self.platform}: " + ", ".join(bits)

    def to_dict(self):
        d = asdict(self)
        d["id"], d["title"] = self.id, self.title
        return d


def _load_file(path):
    text = Path(path).read_text(encoding="utf-8")
    if str(path).endswith(".json"):
        return json.loads(text)
    try:
        import yaml
    except ImportError as e:  # pragma: no cover
        raise SystemExit("qa.yml needs PyYAML: pip install pyyaml (or write qa.json)") from e
    return yaml.safe_load(text) or {}


def _expand_env(value):
    """${VAR} and ${VAR:-default} inside strings, so CI can inject URLs and paths."""
    if isinstance(value, str):
        out, i = "", 0
        while i < len(value):
            j = value.find("${", i)
            if j < 0:
                out += value[i:]
                break
            k = value.find("}", j)
            if k < 0:
                out += value[i:]
                break
            out += value[i:j]
            expr = value[j + 2:k]
            name, _, default = expr.partition(":-")
            out += os.environ.get(name, default)
            i = k + 1
        return out
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value


def load(path):
    raw = _expand_env(_load_file(path))
    raw.setdefault("name", Path(path).resolve().parent.name)
    raw.setdefault("app", {})
    raw.setdefault("tests", [{"name": "Explore", "crawl": {}}])
    raw.setdefault("checks", ["a11y", "overflow", "console", "crash"])
    raw.setdefault("ai", {"provider": "none"})
    raw.setdefault("report", {})
    raw["report"].setdefault("out", "testflock-report")
    raw["report"].setdefault("formats", ["html", "json", "junit", "md"])
    raw.setdefault("notify", {})
    m = dict(DEFAULT_MATRIX)
    m.update(raw.get("matrix") or {})
    if isinstance(m.get("devices"), list):  # one list for every platform
        m["devices"] = {p: m["devices"] for p in m["platforms"]}
    raw["matrix"] = m
    # Custom presets merge over the built-in ones
    for name, table in (raw.get("presets") or {}).items():
        target = {"web": presets.WEB_DEVICES, "android": presets.ANDROID_DEVICES, "ios": presets.IOS_DEVICES,
                  "networks": presets.NETWORKS, "locales": presets.LOCALES}.get(name)
        if target is not None:
            target.update(table)
    raw["_dir"] = str(Path(path).resolve().parent)
    return raw


def _matches(cell, rule):
    return all(str(getattr(cell, k, cell.extra.get(k))) == str(v) for k, v in rule.items())


def expand(cfg, only=None):
    """Every combination of the matrix, minus `exclude`, plus `include`.

    `only` is a filter from the command line, e.g. {"platform": "web", "network": "offline"}.
    """
    m = cfg["matrix"]
    cells = []
    for platform in m["platforms"]:
        devices = (m["devices"] or {}).get(platform) or DEFAULT_MATRIX["devices"].get(platform, [])
        for device, locale, orient, net, theme, text in itertools.product(
                devices, m["locales"], m["orientations"], m["networks"], m["themes"], m["text_sizes"]):
            cells.append(Cell(platform, device, locale, orient, net, theme, text))
    cells = [c for c in cells if not any(_matches(c, r) for r in m.get("exclude") or [])]
    for extra in m.get("include") or []:
        known = {k: extra[k] for k in extra if k in Cell.__dataclass_fields__ and k != "extra"}
        rest = {k: v for k, v in extra.items() if k not in known}
        cells.append(Cell(**known, extra=rest))
    if only:
        cells = [c for c in cells if _matches(c, only)]
    seen, unique = set(), []
    for c in cells:
        if c.id not in seen:
            seen.add(c.id)
            unique.append(c)
    limit = int(m.get("max_cells") or 0)
    if limit and len(unique) > limit:
        raise SystemExit(f"The matrix has {len(unique)} cells, over max_cells={limit}. "
                         "Trim the matrix, add `exclude` rules or raise max_cells.")
    return unique
