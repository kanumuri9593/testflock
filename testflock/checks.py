"""Automatic checks run on every screen, with or without AI.

Each check returns issues: {title, severity, kind, details, screen}.
Severities: blocker > major > minor > cosmetic.
"""
SEVERITIES = ["blocker", "major", "minor", "cosmetic"]

# Smallest comfortable touch target in platform units: 44 pt (Apple), 48 dp (Android), 44 CSS px (web).
MIN_TARGET = {"ios": 44, "android": 48, "web": 44}


def issue(title, severity, kind, details="", screen=None):
    return {"title": title, "severity": severity, "kind": kind, "details": details, "screen": screen}


def run_checks(screen, cell, enabled):
    out = []
    png = screen.png
    for note in screen.notes:
        kind, _, text = note.partition(": ")
        if kind == "crash" and "crash" in enabled:
            out.append(issue("App crashed or closed" if "no longer" in text else "Uncaught error",
                             "blocker" if "no longer" in text else "major", "crash", text, png))
        elif kind == "offline":
            out.append(issue("Does not reopen offline", "major", "offline", text, png))
        elif kind == "overflow" and "overflow" in enabled:
            out.append(issue("Content wider than the screen", "minor", "layout", text, png))
        elif kind == "network" and "console" in enabled and cell.network == "online":
            out.append(issue("Request failed", "minor", "network", text, png))
        elif kind == "console" and "console" in enabled:
            out.append(issue("Console error", "minor", "console", text, png))
    if "a11y" in enabled:
        minimum = MIN_TARGET.get(cell.platform, 44)
        unit = screen.unit or 1.0
        small, noname, offscreen = [], [], []
        for e in screen.elements:
            if not e.tappable:
                continue
            if e.kind != "field" and not e.label.strip():
                noname.append(e)
            w, h = e.w / unit, e.h / unit
            touches_edge = e.y - e.h / 2 <= 1 or e.y + e.h / 2 >= screen.height - 1
            if min(w, h) < minimum - 0.5 and not touches_edge and e.kind != "field":
                small.append((e, w, h))
            if e.x > screen.width or e.x < 0:
                offscreen.append(e)
        if noname:
            at = ", ".join(f"({e.x},{e.y})" for e in noname[:5])
            out.append(issue("Control with no accessibility label", "minor", "a11y",
                             f"{len(noname)} tappable control(s) a screen reader cannot name, at {at}", png))
        if small:
            desc = "; ".join(f'"{e.label[:30]}" {w:.0f}x{h:.0f}' for e, w, h in small[:5])
            out.append(issue(f"Touch target under {minimum}", "cosmetic", "a11y", desc, png))
        if offscreen:
            out.append(issue("Control placed off screen", "minor", "layout",
                             ", ".join(f'"{e.label[:30]}"' for e in offscreen[:5]), png))
    return out


def dedupe(issues):
    """One entry per (title, details-prefix); keep every screenshot it was seen on."""
    merged = {}
    for i in issues:
        key = (i["title"], (i.get("details") or "")[:60], i.get("test"))
        if key in merged:
            m = merged[key]
            if i.get("screen") and i["screen"] not in m["screens"]:
                m["screens"].append(i["screen"])
            m["count"] += 1
        else:
            m = dict(i)
            m["screens"] = [i["screen"]] if i.get("screen") else []
            m["count"] = 1
            merged[key] = m
    return sorted(merged.values(), key=lambda i: SEVERITIES.index(i.get("severity", "minor")))
