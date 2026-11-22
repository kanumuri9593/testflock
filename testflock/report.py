"""Reports: one HTML page with screenshots, JSON for tools, JUnit for CI, Markdown for PR summaries."""
import html
import json
import time
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from .checks import SEVERITIES

COLORS = {"blocker": "#c62828", "major": "#e65100", "minor": "#9a6700", "cosmetic": "#57606a",
          "passed": "#1a7f37", "failed": "#c62828", "error": "#8250df", "skipped": "#57606a"}


def summarize(results, cfg):
    tests = [t for r in results for t in r["tests"]]
    issues = [i for t in tests for i in t["issues"]]
    by_sev = {s: sum(1 for i in issues if i["severity"] == s) for s in SEVERITIES}
    status = {s: sum(1 for t in tests if t["status"] == s) for s in ("passed", "failed", "error", "skipped")}
    usage = {"input": 0, "output": 0, "cache_read": 0}
    for t in tests:
        for k, v in ((t.get("agent") or {}).get("usage") or {}).items():
            usage[k] = usage.get(k, 0) + v
    ok = status["failed"] == 0 and status["error"] == 0
    return {"name": cfg.get("name"), "when": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            "cells": len(results), "tests": len(tests), "status": status, "issues": by_sev,
            "ok": ok, "ai_usage": usage, "ai_provider": (cfg.get("ai") or {}).get("provider", "none")}


def write_all(results, cfg, out_root):
    out_root = Path(out_root)
    summary = summarize(results, cfg)
    formats = cfg["report"].get("formats") or ["html", "json", "junit", "md"]
    files = {}
    if "json" in formats:
        p = out_root / "results.json"
        p.write_text(json.dumps({"summary": summary, "results": results}, indent=2))
        files["json"] = p
    if "junit" in formats:
        p = out_root / "junit.xml"
        p.write_text(junit(results))
        files["junit"] = p
    if "md" in formats:
        p = out_root / "SUMMARY.md"
        p.write_text(markdown(results, summary, cfg))
        files["md"] = p
    if "html" in formats:
        p = out_root / "index.html"
        p.write_text(html_report(results, summary, cfg))
        files["html"] = p
    return summary, files


def junit(results):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<testsuites>"]
    for r in results:
        cell = r["cell"]
        tests = r["tests"]
        fails = sum(1 for t in tests if t["status"] == "failed")
        errs = sum(1 for t in tests if t["status"] == "error")
        skips = sum(1 for t in tests if t["status"] == "skipped")
        lines.append(f'  <testsuite name={quoteattr(cell["title"])} tests="{len(tests)}" failures="{fails}" '
                     f'errors="{errs}" skipped="{skips}">')
        for t in tests:
            lines.append(f'    <testcase classname={quoteattr(cell["id"])} name={quoteattr(t["name"])} '
                         f'time="{t.get("seconds", 0)}">')
            body = "\n".join(f'[{i["severity"]}] {i["title"]}: {i.get("details", "")}' for i in t["issues"])
            if t["status"] == "failed":
                first = next((i["title"] for i in t["issues"] if i["severity"] in ("blocker", "major")), "failed")
                lines.append(f"      <failure message={quoteattr(first)}>{escape(body)}</failure>")
            elif t["status"] == "error":
                lines.append(f'      <error message={quoteattr(t.get("error", ""))}>'
                             f'{escape(t.get("traceback", ""))}</error>')
            elif t["status"] == "skipped":
                lines.append("      <skipped/>")
            if body and t["status"] == "passed":
                lines.append(f"      <system-out>{escape(body)}</system-out>")
            lines.append("    </testcase>")
        lines.append("  </testsuite>")
    lines.append("</testsuites>")
    return "\n".join(lines) + "\n"


def markdown(results, s, cfg):
    icon = "✅" if s["ok"] else "❌"
    out = [f"## {icon} Testflock: {s['name']}", "",
           f"{s['cells']} device setups, {s['tests']} tests: {s['status']['passed']} passed, "
           f"{s['status']['failed']} failed, {s['status']['error']} errors, {s['status']['skipped']} skipped.",
           "Issues: " + ", ".join(f"{n} {k}" for k, n in s["issues"].items() if n) if any(s["issues"].values())
           else "No issues found.", ""]
    top = top_issues(results)
    if top:
        out += ["### Top issues", ""]
        for g in top[:10]:
            out.append(f'- **{g["issue"]["severity"]}**: {g["issue"]["title"]} '
                       f'({len(g["setups"])} setup{"s" if len(g["setups"]) != 1 else ""}): '
                       f'{(g["issue"].get("details") or "")[:140]}')
        out.append("")
    out += ["### Every test", "", "| Setup | Test | Result | Issues |", "|---|---|---|---|"]
    for r in results:
        for t in r["tests"]:
            top = "; ".join(f'{i["severity"]}: {i["title"]}' for i in t["issues"][:3])
            out.append(f'| {r["cell"]["title"]} | {t["name"]} | {t["status"]} | {top or "none"} |')
    skipped = {x for r in results for x in r.get("skipped_settings", [])}
    if skipped:
        out += ["", "**Could not emulate:** " + "; ".join(sorted(skipped))]
    return "\n".join(out) + "\n"


def _badge(text, color):
    return f'<span class="badge" style="--c:{color}">{html.escape(text)}</span>'


ORDER = {"error": 0, "failed": 1, "skipped": 2, "passed": 3}


def top_issues(results):
    """Same issue on many device setups -> one line with where it happened."""
    groups = {}
    for r in results:
        for t in r["tests"]:
            for i in t["issues"]:
                key = (i["title"], (i.get("details") or "")[:80])
                g = groups.setdefault(key, {"issue": i, "setups": [], "screens": []})
                if r["cell"]["title"] not in g["setups"]:
                    g["setups"].append(r["cell"]["title"])
                g["screens"] += [p for p in i.get("screens") or [] if p not in g["screens"]][:2]
    return sorted(groups.values(), key=lambda g: (SEVERITIES.index(g["issue"]["severity"]), -len(g["setups"])))


def html_report(results, s, cfg):
    e = html.escape
    rows = []
    pairs = sorted(((r, t) for r in results for t in r["tests"]), key=lambda rt: ORDER.get(rt[1]["status"], 9))
    for r, t in pairs:
        c = r["cell"]
        issues = "".join(
            f'<li>{_badge(i["severity"], COLORS.get(i["severity"], "#57606a"))} <b>{e(i["title"])}</b>'
            f'{" ×" + str(i["count"]) if i.get("count", 1) > 1 else ""}'
            f'<div class="det">{e(i.get("details") or "")}</div>'
            + "".join(f'<a href="{e(p)}" target="_blank"><img loading="lazy" class="mini" src="{e(p)}"></a>'
                      for p in (i.get("screens") or [])[:4]) + "</li>"
            for i in t["issues"]) or '<li class="muted">No issues</li>'
        shots = "".join(f'<figure><a href="{e(sc["png"])}" target="_blank"><img loading="lazy" '
                        f'src="{e(sc["png"])}"></a><figcaption>{e(sc["label"][:40])}</figcaption></figure>'
                        for sc in t["screens"][:24])
        verdict = (t.get("agent") or {}).get("verdict")
        extra = ""
        if verdict:
            extra = (f'<p class="verdict">AI verdict: {e(str(verdict.get("summary", "")))} '
                     f'(score {e(str(verdict.get("score")))}/10, goal reached: {e(str(verdict.get("goal_reached")))})</p>')
        if t.get("note"):
            extra += f'<p class="muted">{e(t["note"])}</p>'
        if t.get("error"):
            extra += f'<pre class="err">{e(t["error"])}</pre>'
        if t.get("steps"):
            extra += '<ol class="steps">' + "".join(f"<li>{e(x)}</li>" for x in t["steps"]) + "</ol>"
        rows.append(f'''<details class="card" {"open" if t["status"] in ("failed", "error") else ""}>
<summary>{_badge(t["status"], COLORS.get(t["status"], "#57606a"))} <b>{e(c["title"])}</b> · {e(t["name"])}
<span class="muted">{len(t["issues"])} issues · {len(t["screens"])} screens · {t.get("seconds", 0)}s</span></summary>
{extra}<ul class="issues">{issues}</ul><div class="shots">{shots}</div></details>''')
    top = "".join(
        f'<li>{_badge(g["issue"]["severity"], COLORS.get(g["issue"]["severity"], "#57606a"))} '
        f'<b>{e(g["issue"]["title"])}</b> <span class="muted">on {len(g["setups"])} setup'
        f'{"s" if len(g["setups"]) != 1 else ""}</span><div class="det">{e(g["issue"].get("details") or "")}</div>'
        f'<div class="det">Seen on: {e(", ".join(g["setups"][:6]))}{" and more" if len(g["setups"]) > 6 else ""}</div>'
        + "".join(f'<a href="{e(p)}" target="_blank"><img loading="lazy" class="mini" src="{e(p)}"></a>'
                  for p in g["screens"][:3]) + "</li>"
        for g in top_issues(results)[:25])
    top_html = f'<h2>Issues across all setups</h2><ul class="issues">{top}</ul>' if top else ""
    skipped = sorted({x for r in results for x in r.get("skipped_settings", [])})
    skipped_html = ("<p class='muted'><b>Could not emulate:</b> " + e("; ".join(skipped)) + "</p>") if skipped else ""
    tiles = "".join(f'<div class="tile"><div class="n" style="color:{COLORS[k]}">{n}</div>{k}</div>'
                    for k, n in s["issues"].items())
    status = "".join(f'<div class="tile"><div class="n" style="color:{COLORS[k]}">{n}</div>{k}</div>'
                     for k, n in s["status"].items())
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Testflock report</title>
<style>
:root{{--bg:#fff;--fg:#1f2328;--muted:#59636e;--card:#f6f8fa;--line:#d1d9e0}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;--card:#151b23;--line:#3d444d}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:24px 16px 64px}}
h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:18px;margin:28px 0 8px}} .muted{{color:var(--muted)}}
.tiles{{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;min-width:86px;color:var(--muted);font-size:13px}}
.tile .n{{font-size:24px;font-weight:700}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:10px 0;padding:10px 14px}}
summary{{cursor:pointer;display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
.badge{{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600;color:#fff;background:var(--c)}}
.issues{{padding-left:18px}} .issues li{{margin:8px 0}} .det{{color:var(--muted);font-size:13px;white-space:pre-wrap}}
.mini{{height:90px;border-radius:6px;border:1px solid var(--line);margin:4px 4px 0 0}}
.shots{{display:flex;gap:10px;overflow-x:auto;padding:6px 0}}
figure{{margin:0;flex:0 0 auto;text-align:center}} figure img{{height:260px;border-radius:10px;border:1px solid var(--line)}}
figcaption{{font-size:12px;color:var(--muted);max-width:140px;margin:auto}}
.err{{color:#c62828;white-space:pre-wrap}} .verdict{{font-style:italic}}
footer{{margin-top:32px;font-size:12px}}
</style></head><body><main>
<h1>{"✅" if s["ok"] else "❌"} {e(str(s["name"]))}</h1>
<div class="muted">{e(s["when"])} · {s["cells"]} device setups · {s["tests"]} tests · AI: {e(s["ai_provider"])}</div>
<div class="tiles">{status}</div><div class="tiles">{tiles}</div>{skipped_html}
{top_html}<h2>Every test</h2>
{"".join(rows)}
<footer class="muted">Made with Testflock by One Energy Together. Inspired by
<a href="https://github.com/pierridotite/mobile-agent-testers">mobile-agent-testers</a> by Pierre Raffalli (MIT).</footer>
</main></body></html>'''
