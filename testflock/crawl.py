"""No-AI explorer: taps every safe control it can reach, screen by screen.

It needs no key and costs nothing. It finds crashes, dead ends, layout and
accessibility problems on each screen it reaches; it does not judge whether
the app makes sense (that is what agent mode is for).
"""
from . import presets


def crawl(driver, opts, on_screen):
    max_actions = int(opts.get("max_actions", 25))
    max_screens = int(opts.get("max_screens", 12))
    avoid = [a.lower() for a in presets.DEFAULT_AVOID + list(opts.get("avoid", []))]
    tapped_any = set()
    tried = {}        # screen signature -> labels already tapped there
    seen = {}         # signature -> first screenshot
    actions = 0
    s = driver.screen("start")
    on_screen(s, "start")
    seen[s.signature()] = s.png
    stuck = 0
    while actions < max_actions and len(seen) <= max_screens:
        sig = s.signature()
        done = tried.setdefault(sig, set())
        options = [e for e in s.elements if e.tappable and e.kind != "field" and e.label
                   and e.label not in done and not any(a in e.label.lower() for a in avoid)]
        if not options:
            if stuck >= 2:
                break
            stuck += 1
            driver.back()
            s = driver.screen("back")
            on_screen(s, "back")
            continue
        stuck = 0
        # Controls never tapped anywhere first, then the biggest (main buttons like Continue)
        options.sort(key=lambda e: (e.label in tapped_any, -(e.w * e.h)))
        el = options[0]
        done.add(el.label)
        tapped_any.add(el.label)
        driver.tap(el.x, el.y)
        actions += 1
        s = driver.screen(f"tap-{el.label[:24]}")
        on_screen(s, f'tap "{el.label}"')
        if s.signature() not in seen:
            seen[s.signature()] = s.png
    return {"actions": actions, "screens": len(seen)}
