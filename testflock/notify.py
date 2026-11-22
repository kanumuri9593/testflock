"""Send the report: email (SMTP or Resend) and chat webhooks (Slack, Discord, Teams, any URL).

notify:
  when: failure            # always | failure | never
  email:
    to: [you@example.com]
    via: smtp              # smtp | resend
    from: "Testflock <qa@example.com>"
    smtp: {host: smtp.gmail.com, port: 587, user_env: SMTP_USER, password_env: SMTP_PASSWORD}
    resend: {api_key_env: RESEND_API_KEY}
    attach: zip            # zip | html | none (zip of the whole report if under 9 MB)
  webhooks:
    - {url_env: SLACK_WEBHOOK_URL, kind: slack}
Secrets are read from environment variables (GitHub secrets), never from qa.yml.
"""
import base64
import json
import os
import shutil
import smtplib
import ssl
import tempfile
import urllib.request
from email.message import EmailMessage
from pathlib import Path


def should_send(cfg, summary, force=False):
    when = (cfg.get("notify") or {}).get("when", "always")
    return force or when == "always" or (when == "failure" and not summary["ok"])


def run_link():
    if os.environ.get("GITHUB_RUN_ID"):
        return (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                f"{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    return os.environ.get("TESTFLOCK_REPORT_URL", "")


def subject(summary):
    icon = "✅" if summary["ok"] else "❌"
    iss = sum(summary["issues"].values())
    return (f"{icon} {summary['name']} QA: {summary['status']['passed']}/{summary['tests']} passed, "
            f"{iss} issue{'s' if iss != 1 else ''}")


def email_html(summary, md_text):
    link = run_link()
    rows = "".join(f"<li>{k}: <b>{n}</b></li>" for k, n in summary["issues"].items() if n) or "<li>No issues</li>"
    import html
    return (f"<div style='font-family:-apple-system,Segoe UI,sans-serif;font-size:15px'>"
            f"<h2 style='margin:0'>{html.escape(subject(summary))}</h2>"
            f"<p>{summary['cells']} device setups, {summary['tests']} tests ({summary['when']}).</p><ul>{rows}</ul>"
            + (f"<p><a href='{link}'>Open the run and download the full report</a></p>" if link else "")
            + f"<pre style='white-space:pre-wrap;font-size:12px'>{html.escape(md_text)}</pre></div>")


def _attachment(out_root, mode):
    if mode == "none":
        return None
    if mode == "html":
        p = Path(out_root) / "index.html"
        return ("report.html", p.read_bytes(), "text/html") if p.exists() else None
    tmp = Path(tempfile.mkdtemp()) / "testflock-report"
    archive = shutil.make_archive(str(tmp), "zip", out_root)
    data = Path(archive).read_bytes()
    if len(data) > 9 * 1024 * 1024:
        return None
    return ("testflock-report.zip", data, "application/zip")


def send_email(cfg, summary, out_root, md_text):
    em = (cfg.get("notify") or {}).get("email")
    if not em or not em.get("to"):
        return "email: not configured"
    to = em["to"] if isinstance(em["to"], list) else [em["to"]]
    sender = em.get("from") or os.environ.get("SMTP_USER") or "testflock@localhost"
    att = _attachment(out_root, em.get("attach", "zip"))
    via = em.get("via", "smtp")
    if via == "resend":
        key = os.environ.get((em.get("resend") or {}).get("api_key_env", "RESEND_API_KEY"))
        if not key:
            return "email: RESEND_API_KEY not set"
        body = {"from": sender, "to": to, "subject": subject(summary), "html": email_html(summary, md_text)}
        if att:
            body["attachments"] = [{"filename": att[0], "content": base64.b64encode(att[1]).decode()}]
        req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
        return f"email: sent to {len(to)} via Resend"
    s = em.get("smtp") or {}
    user = os.environ.get(s.get("user_env", "SMTP_USER"))
    password = os.environ.get(s.get("password_env", "SMTP_PASSWORD"))
    if not (user and password):
        return "email: SMTP_USER / SMTP_PASSWORD not set"
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject(summary), sender, ", ".join(to)
    msg.set_content(md_text)
    msg.add_alternative(email_html(summary, md_text), subtype="html")
    if att:
        maintype, subtype = att[2].split("/")
        msg.add_attachment(att[1], maintype=maintype, subtype=subtype, filename=att[0])
    host, port = s.get("host", "smtp.gmail.com"), int(s.get("port", 587))
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as srv:
            srv.login(user, password)
            srv.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as srv:
            srv.starttls(context=ssl.create_default_context())
            srv.login(user, password)
            srv.send_message(msg)
    return f"email: sent to {len(to)} via {host}"


def send_webhooks(cfg, summary, md_text):
    out = []
    for hook in (cfg.get("notify") or {}).get("webhooks") or []:
        url = os.environ.get(hook.get("url_env", "")) or hook.get("url")
        if not url:
            out.append(f"webhook {hook.get('url_env')}: not set")
            continue
        text = subject(summary) + (f"\n{run_link()}" if run_link() else "")
        kind = hook.get("kind", "slack")
        body = {"slack": {"text": text}, "discord": {"content": text[:1900]},
                "teams": {"text": text}}.get(kind, {"summary": summary, "markdown": md_text})
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
        out.append(f"webhook {kind}: sent")
    return out


def notify(cfg, summary, out_root, force=False):
    if not should_send(cfg, summary, force):
        return ["notify: skipped (when: " + (cfg.get("notify") or {}).get("when", "always") + ")"]
    md_path = Path(out_root) / "SUMMARY.md"
    md_text = md_path.read_text() if md_path.exists() else subject(summary)
    results = []
    for fn in (lambda: send_email(cfg, summary, out_root, md_text), lambda: send_webhooks(cfg, summary, md_text)):
        try:
            r = fn()
            results += r if isinstance(r, list) else [r]
        except Exception as e:  # a failed email must not hide the test result
            results.append(f"notify error: {type(e).__name__}: {e}")
    return results
