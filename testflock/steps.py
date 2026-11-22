"""Scripted tests: a short list of steps, the same on web, Android and iOS.

    - tap: "Add item"              # by label (exact, then case-insensitive, then contains, /regex/)
    - tap: {x: 200, y: 640}        # or by position (screenshot pixels)
    - type: {into: "Name", text: "Spare keys", enter: true}
    - expect: "Spare keys"         # text must be on screen (waits up to 8 s)
    - expect: {not: "Error"}
    - wait: 2                      # seconds, or {for: "Saved", timeout: 10}
    - scroll: down                 # or {until: "Settings", max: 6}
    - back: true
    - relaunch: true               # kill and reopen: checks what was saved
    - open: "/items/42"            # URL or deep link
    - network: offline             # switch network mid-test
    - screenshot: "after-save"
Add `optional: true` to any step to skip it when its target is missing
(e.g. a permission dialog that only shows on first launch).
"""
import time


class StepFailed(Exception):
    pass


def _visible(screen, text):
    return screen.find(text) is not None


def _wait_for(driver, text, timeout, present=True):
    end = time.time() + float(timeout)
    while True:
        s = driver.screen("wait")
        if _visible(s, text) == present:
            return s
        if time.time() > end:
            return None
        time.sleep(0.7)


def run_step(driver, step, ctx):
    """Run one step. Returns the screen after it. Raises StepFailed on a failed check."""
    optional = bool(step.get("optional"))
    action = next(k for k in step if k not in ("optional", "name"))
    arg = step[action]
    shown = arg
    if isinstance(arg, dict):
        shown = arg.get("label") or arg.get("text") or arg.get("for") or arg.get("until") or \
            (f"not {arg['not']}" if "not" in arg else "") or (f"{arg.get('x')},{arg.get('y')}" if "x" in arg else "")
        if action == "type" and arg.get("into"):
            shown = f'"{arg.get("text")}" into {arg["into"]}'
    label = step.get("name") or f"{action} {'' if shown is True else shown}".strip()
    ctx["log"].append(label)

    def target_screen(target):
        s = driver.screen(f"before-{action}")
        el = s.find(target)
        if el is None:
            s2 = _wait_for(driver, target, 6)
            el = s2.find(target) if s2 else None
            s = s2 or s
        return s, el

    if action in ("tap", "long_press"):
        if isinstance(arg, dict) and "x" in arg:
            getattr(driver, action)(arg["x"], arg["y"])
        else:
            target = arg.get("label") if isinstance(arg, dict) else arg
            s, el = target_screen(target)
            if el is None:
                if optional:
                    return s
                raise StepFailed(f'Could not find "{target}" to {action.replace("_", " ")}', s)
            getattr(driver, action)(el.x, el.y)
    elif action == "type":
        text = arg["text"] if isinstance(arg, dict) else str(arg)
        if isinstance(arg, dict) and arg.get("into"):
            s, el = target_screen(arg["into"])
            if el is None:
                if optional:
                    return s
                raise StepFailed(f'Could not find field "{arg["into"]}"', s)
            driver.tap(el.x, el.y)
            time.sleep(0.5)
        driver.type_text(text)
        if isinstance(arg, dict) and arg.get("enter"):
            driver.press_enter()
    elif action == "expect":
        if isinstance(arg, dict) and "not" in arg:
            s = _wait_for(driver, arg["not"], arg.get("timeout", 3), present=False)
            if s is None:
                raise StepFailed(f'"{arg["not"]}" is on screen but should not be', driver.screen("unexpected"))
            return s
        text = arg.get("text") if isinstance(arg, dict) else arg
        s = _wait_for(driver, text, (arg.get("timeout", 8) if isinstance(arg, dict) else 8))
        if s is None:
            raise StepFailed(f'Expected "{text}" on screen', driver.screen("missing"))
        return s
    elif action == "wait":
        if isinstance(arg, dict) and arg.get("for"):
            s = _wait_for(driver, arg["for"], arg.get("timeout", 10))
            if s is None and not optional:
                raise StepFailed(f'Timed out waiting for "{arg["for"]}"', driver.screen("timeout"))
            return s or driver.screen("timeout")
        driver.wait(arg)
    elif action == "scroll":
        if isinstance(arg, dict) and arg.get("until"):
            for _ in range(int(arg.get("max", 6))):
                s = driver.screen("scroll")
                if _visible(s, arg["until"]):
                    return s
                driver.scroll(arg.get("direction", "down"))
            s = driver.screen("scroll")
            if not _visible(s, arg["until"]) and not optional:
                raise StepFailed(f'Scrolled but never found "{arg["until"]}"', s)
            return s
        driver.scroll(arg if isinstance(arg, str) else "down")
    elif action == "back":
        driver.back()
    elif action == "relaunch":
        driver.relaunch()
    elif action == "open":
        driver.open_url(arg)
    elif action == "network":
        driver.set_network(arg)
    elif action == "screenshot":
        return driver.screen(str(arg))
    else:
        raise StepFailed(f"Unknown step '{action}'", None)
    return driver.screen(action)
