"""Run every test on every cell of the matrix and collect results."""
import re
import time
import traceback
from pathlib import Path

from . import checks as checks_mod
from .agent import run_agent
from .crawl import crawl
from .steps import StepFailed, run_step


def make_driver(cfg, cell, outdir):
    if cell.platform == "web":
        from .drivers.web import WebDriver as D
    elif cell.platform == "android":
        from .drivers.android import AndroidDriver as D
    elif cell.platform == "ios":
        from .drivers.ios import IOSDriver as D
    else:
        raise SystemExit(f"Unknown platform '{cell.platform}'")
    return D(cfg, cell, outdir)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40] or "test"


def _test_kind(t):
    return "steps" if "steps" in t else "agent" if "agent" in t else "crawl"


def run_cell(cfg, cell, out_root, log=print):
    root = Path(out_root) / cell.id
    results = {"cell": cell.to_dict(), "tests": [], "skipped_settings": []}
    enabled = set(cfg.get("checks") or [])
    tests = [t for t in cfg["tests"] if cell.platform in t.get("platforms", [cell.platform])]
    if (cfg.get("ai") or {}).get("provider", "none") == "none":
        # No AI: agent tests fall back to the free crawler, so a run always explores.
        tests = [dict(t, crawl=t.get("crawl", {}), _from_agent=True) if "agent" in t else t for t in tests]
        for t in tests:
            if t.get("_from_agent"):
                t.pop("agent", None)
    driver = None
    for ti, test in enumerate(tests):
        name = test.get("name") or f"{_test_kind(test)} {ti + 1}"
        outdir = root / f"{ti + 1:02d}-{slug(name)}"
        outdir.mkdir(parents=True, exist_ok=True)
        res = {"name": name, "kind": _test_kind(test), "status": "passed", "issues": [], "screens": [],
               "steps": [], "started": time.time()}
        if test.get("_from_agent"):
            res["note"] = "AI is off (ai.provider: none), so this ran as a free crawl instead."

        def on_screen(screen, label):
            res["screens"].append({"png": str(Path(screen.png).relative_to(out_root)), "label": label})
            for i in checks_mod.run_checks(screen, cell, enabled):
                add_issue(i)

        def add_issue(i):
            i = dict(i)
            i["test"] = name
            if i.get("screen"):
                p = Path(i["screen"])
                i["screen"] = str(p.relative_to(out_root)) if p.is_absolute() else str(p)
            res["issues"].append(i)

        try:
            if driver is None or test.get("fresh", False):
                if driver:
                    driver.stop()
                driver = make_driver(cfg, cell, outdir)
                driver.start()
                results["skipped_settings"] = list(dict.fromkeys(driver.skipped))
            else:
                driver.outdir = outdir
                driver.counter = 0
                if test.get("relaunch", True):
                    driver.relaunch()
            kind = _test_kind(test)
            if kind == "steps":
                ctx = {"log": res["steps"]}
                for step in test["steps"]:
                    s = run_step(driver, step, ctx)
                    if s is not None:
                        on_screen(s, res["steps"][-1])
            elif kind == "agent":
                res["agent"] = run_agent(driver, test, cfg, on_screen, add_issue)
                if res["agent"].get("skipped"):
                    res["status"] = "skipped"
            else:
                res["crawl"] = crawl(driver, test.get("crawl") or {}, on_screen)
        except StepFailed as e:
            msg, shot = e.args[0], e.args[1] if len(e.args) > 1 else None
            if shot is not None:
                on_screen(shot, "failed here")
            add_issue({"title": msg, "severity": "major", "kind": "assert",
                       "details": "Step: " + (res["steps"][-1] if res["steps"] else ""),
                       "screen": shot.png if shot is not None else None})
            res["status"] = "failed"
        except SystemExit:
            raise
        except Exception as e:  # driver or tool failure: report it, keep going
            res["status"] = "error"
            res["error"] = f"{type(e).__name__}: {e}"
            res["traceback"] = traceback.format_exc()[-2000:]
            if driver is not None:   # start the next test on a fresh device
                try:
                    driver.stop()
                except Exception:
                    pass
                driver = None
        res["issues"] = checks_mod.dedupe(res["issues"])
        if not cfg["report"].get("keep_all_screens"):
            used = {sc["png"] for sc in res["screens"]} | {p for i in res["issues"] for p in i.get("screens", [])}
            for f in outdir.glob("*.png"):
                if str(f.relative_to(out_root)) not in used:
                    f.unlink()
        if res["status"] == "passed" and any(i["severity"] in (cfg.get("fail_on") or ["blocker"])
                                             for i in res["issues"]):
            res["status"] = "failed"
        res["seconds"] = round(time.time() - res.pop("started"), 1)
        results["tests"].append(res)
        log(f"  {res['status']:>7}  {name}  ({len(res['issues'])} issues, {res['seconds']}s)")
    if driver:
        driver.stop()
    if driver:
        results["skipped_settings"] = list(dict.fromkeys(driver.skipped))
    return results


def run_all(cfg, cells, out_root, log=print):
    out = []
    try:
        for n, cell in enumerate(cells, 1):
            log(f"[{n}/{len(cells)}] {cell.title}")
            out.append(run_cell(cfg, cell, out_root, log))
    finally:
        try:
            from .drivers.web import WebDriver
            WebDriver.shutdown()
        except ImportError:
            pass
    return out
