import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from testflock import notify

SUMMARY = {"name": "TagVault", "ok": False, "tests": 4, "cells": 2, "when": "now",
           "status": {"passed": 3, "failed": 1, "error": 0, "skipped": 0},
           "issues": {"blocker": 0, "major": 1, "minor": 2, "cosmetic": 0}}


class Sent(Exception):
    pass


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def starttls(self, context=None):
        pass

    def login(self, u, p):
        assert (u, p) == ("me@gmail.com", "app-pass")

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


class NotifyTest(unittest.TestCase):
    def test_smtp_with_zip(self):
        out = Path(tempfile.mkdtemp())
        (out / "index.html").write_text("<html></html>")
        (out / "SUMMARY.md").write_text("## summary")
        cfg = {"notify": {"when": "failure", "email": {"to": ["qa@example.com"], "via": "smtp"}}}
        with mock.patch.dict(os.environ, {"SMTP_USER": "me@gmail.com", "SMTP_PASSWORD": "app-pass"}), \
                mock.patch("smtplib.SMTP", FakeSMTP):
            res = notify.notify(cfg, SUMMARY, out)
        self.assertIn("email: sent to 1 via smtp.gmail.com", res)
        msg = FakeSMTP.sent[-1]
        self.assertIn("❌ TagVault QA: 3/4 passed, 3 issues", msg["Subject"])
        names = [p.get_filename() for p in msg.iter_attachments()]
        self.assertEqual(names, ["testflock-report.zip"])

    def test_when_failure_skips_green_runs(self):
        cfg = {"notify": {"when": "failure", "email": {"to": ["a@b.c"]}}}
        self.assertFalse(notify.should_send(cfg, dict(SUMMARY, ok=True)))


if __name__ == "__main__":
    unittest.main()
