"""testflock: one config, many devices, scripted and AI testers, reports by email.

  testflock init [--app web|flutter|android|ios]   write a starter qa.yml
  testflock matrix [-c qa.yml] [--github]          list the device setups (or JSON for a CI matrix)
  testflock run [-c qa.yml] [--only k=v,...] [--shard 1/4] [--out DIR] [--notify]
  testflock merge DIR... --out DIR                 combine shard reports into one
  testflock notify [-c qa.yml] [--out DIR] [--force]
  testflock doctor                                 what is installed for each platform
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__, config, notify as notify_mod, report

STARTER = """# Testflock config. Docs: README.md. Every list below multiplies the matrix.
name: My app
app:
  web:
    serve: build/web            # a built folder to serve, or `url: https://...`
  android:
    package: com.example.app
    apk: build/app/outputs/flutter-apk/app-debug.apk
  ios:
    app: build/ios/iphonesimulator/Runner.app

matrix:
  platforms: [web]              # add android, ios
  devices:
    web: [iphone-se, pixel-8, ipad-mini]
    android: [pixel-8]
    ios: [iphone-16]
  locales: [en-US, es-ES]
  orientations: [portrait]      # landscape
  networks: [online, offline]   # wifi, 4g, fast-3g, slow-3g, 2g, flaky
  themes: [light, dark]
  text_sizes: [default]         # small, large, largest
  exclude:
    - {network: offline, theme: dark}
  max_cells: 24

tests:
  - name: Opens and shows the home screen
    steps:
      - expect: "/home|welcome/"
  - name: Explore like a new user
    agent:                      # needs ai.provider; with `none` it runs the free crawler instead
      persona: "Busy parent, not technical, uses large text"
      goal: "Add a first item and find it again."
      max_actions: 25

checks: [a11y, overflow, console, crash]
fail_on: [blocker]              # issue severities that fail the build (add major to be stricter)

ai:
  provider: none                # none | anthropic | claude-code
  # model: claude-opus-5-5      # any Claude model id; claude-haiku-5-5 costs least
  # effort: low
  # base_url: https://...       # any Anthropic-compatible API instead of Anthropic

report:
  out: testflock-report

notify:
  when: failure                 # always | failure | never
  # email:
  #   to: [you@example.com]
  #   via: smtp                 # smtp (Gmail app password works) | resend
  #   smtp: {host: smtp.gmail.com, port: 587}
  # webhooks:
  #   - {url_env: SLACK_WEBHOOK_URL, kind: slack}
"""


def _parse_only(text):
    if not text:
        return None
    return dict(kv.split("=", 1) for kv in text.split(",") if "=" in kv)


def cmd_init(a):
    p = Path(a.config)
    if p.exists() and not a.force:
        sys.exit(f"{p} exists (use --force to overwrite)")
    p.write_text(STARTER)
    print(f"Wrote {p}. Next: testflock matrix, then testflock run")


def cmd_matrix(a):
    cfg = config.load(a.config)
    cells = config.expand(cfg, _parse_only(a.only))
    if a.github:
        shards = max(1, a.shards)
        include = []
        for i in range(shards):
            mine = cells[i::shards]
            if mine:
                include.append({"shard": f"{i + 1}/{shards}", "platform": mine[0].platform,
                                "cells": len(mine)})
        print(json.dumps({"include": include}))
        return
    for c in cells:
        print(f"{c.id}\n    {c.title}")
    print(f"\n{len(cells)} device setups × {len(cfg['tests'])} tests")


def _shard(cells, spec):
    if not spec:
        return cells
    i, n = (int(x) for x in spec.split("/"))
    return cells[i - 1::n]


def cmd_run(a):
    from .runner import run_all
    cfg = config.load(a.config)
    cells = _shard(config.expand(cfg, _parse_only(a.only)), a.shard)
    out = Path(a.out or cfg["report"]["out"])
    if out.exists() and not a.keep:
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"Testflock {__version__}: {len(cells)} device setups, {len(cfg['tests'])} tests -> {out}/")
    results = run_all(cfg, cells, out)
    summary, files = report.write_all(results, cfg, out)
    print(f"\n{'PASS' if summary['ok'] else 'FAIL'}: {summary['status']} issues {summary['issues']}")
    print(f"Report: {files.get('html', out)}")
    if os.environ.get("GITHUB_STEP_SUMMARY") and files.get("md"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(files["md"].read_text())
    if a.notify:
        for line in notify_mod.notify(cfg, summary, out):
            print(line)
    sys.exit(0 if summary["ok"] or a.no_fail else 1)


def cmd_merge(a):
    cfg = config.load(a.config) if Path(a.config).exists() else {"name": "QA", "report": {}, "ai": {}}
    cfg.setdefault("report", {})
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    merged = []
    for d in a.dirs:
        d = Path(d)
        for res_file in sorted(d.rglob("results.json")):
            base = res_file.parent
            data = json.loads(res_file.read_text())
            rel = os.path.relpath(base, out)
            for r in data["results"]:
                for t in r["tests"]:
                    for sc in t["screens"]:
                        sc["png"] = f"{rel}/{sc['png']}"
                    for i in t["issues"]:
                        i["screens"] = [f"{rel}/{p}" for p in i.get("screens") or []]
                merged.append(r)
    summary, files = report.write_all(merged, cfg, out)
    print(f"Merged {len(merged)} device setups -> {files.get('html')}")
    if a.notify:
        for line in notify_mod.notify(cfg, summary, out):
            print(line)
    sys.exit(0 if summary["ok"] or a.no_fail else 1)


def cmd_notify(a):
    cfg = config.load(a.config)
    out = Path(a.out or cfg["report"]["out"])
    data = json.loads((out / "results.json").read_text())
    for line in notify_mod.notify(cfg, data["summary"], out, force=a.force):
        print(line)


def cmd_doctor(a):
    def have(cmd):
        return "yes" if shutil.which(cmd) else "no"
    try:
        import playwright  # noqa: F401
        pw = "yes"
    except ImportError:
        pw = "no (pip install 'testflock[web]')"
    print(f"web      playwright: {pw}")
    print(f"android  adb: {have('adb')}, emulator: {have('emulator')}")
    print(f"ios      xcrun: {have('xcrun')}, axe: {have('axe')} (brew install cameroncooke/axe/axe)")
    print(f"ai       claude CLI: {have('claude')}, ANTHROPIC_API_KEY set: "
          f"{'yes' if os.environ.get('ANTHROPIC_API_KEY') else 'no'}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="testflock", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("-c", "--config", default="qa.yml")
        return sp

    sp = common(sub.add_parser("init"))
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_init)
    sp = common(sub.add_parser("matrix"))
    sp.add_argument("--only")
    sp.add_argument("--github", action="store_true")
    sp.add_argument("--shards", type=int, default=1)
    sp.set_defaults(fn=cmd_matrix)
    sp = common(sub.add_parser("run"))
    sp.add_argument("--only", help="filter, e.g. platform=web,network=offline")
    sp.add_argument("--shard", help="i/n: run every n-th setup starting at i (CI parallel jobs)")
    sp.add_argument("--out")
    sp.add_argument("--keep", action="store_true", help="keep old files in the output folder")
    sp.add_argument("--notify", action="store_true", help="send email/webhooks after the run")
    sp.add_argument("--no-fail", action="store_true", help="exit 0 even when tests fail")
    sp.set_defaults(fn=cmd_run)
    sp = common(sub.add_parser("merge"))
    sp.add_argument("dirs", nargs="+")
    sp.add_argument("--out", default="testflock-report")
    sp.add_argument("--notify", action="store_true")
    sp.add_argument("--no-fail", action="store_true")
    sp.set_defaults(fn=cmd_merge)
    sp = common(sub.add_parser("notify"))
    sp.add_argument("--out")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_notify)
    sp = sub.add_parser("doctor")
    sp.set_defaults(fn=cmd_doctor)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
