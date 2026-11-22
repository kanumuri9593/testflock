import json
import tempfile
import unittest
from pathlib import Path

from testflock import config, report
from testflock.checks import dedupe, run_checks
from testflock.drivers.base import Element, Screen


def write_cfg(text):
    d = Path(tempfile.mkdtemp())
    p = d / "qa.json"
    p.write_text(json.dumps(text))
    return p


class MatrixTest(unittest.TestCase):
    def test_product_exclude_include(self):
        cfg = config.load(write_cfg({"matrix": {
            "platforms": ["web"], "devices": {"web": ["iphone-se", "pixel-8"]},
            "locales": ["en-US", "es-ES"], "networks": ["online", "offline"],
            "exclude": [{"network": "offline", "locale": "es-ES"}],
            "include": [{"platform": "web", "device": "ipad-mini", "theme": "dark"}]}}))
        cells = config.expand(cfg)
        self.assertEqual(len(cells), 2 * 2 * 2 - 2 + 1)
        self.assertTrue(any(c.device == "ipad-mini" and c.theme == "dark" for c in cells))
        self.assertEqual(len(config.expand(cfg, {"network": "offline"})), 2)

    def test_max_cells(self):
        cfg = config.load(write_cfg({"matrix": {"platforms": ["web"], "devices": ["a", "b", "c"], "max_cells": 2}}))
        with self.assertRaises(SystemExit):
            config.expand(cfg)

    def test_env(self):
        import os
        os.environ["TF_URL"] = "http://x"
        cfg = config.load(write_cfg({"app": {"web": {"url": "${TF_URL}", "other": "${NOPE:-d}"}}}))
        self.assertEqual(cfg["app"]["web"], {"url": "http://x", "other": "d"})


class FindTest(unittest.TestCase):
    def setUp(self):
        self.s = Screen("x.png", 400, 800, [
            Element("text", "Continue reading", 10, 10, 100, 20),
            Element("button", "Continue", 200, 700, 300, 50),
            Element("field", "Your name", 200, 300, 300, 40, value="Sam")])

    def test_find_order(self):
        self.assertEqual(self.s.find("Continue").kind, "button")
        self.assertEqual(self.s.find("continue").kind, "button")
        self.assertEqual(self.s.find("/your\\s+name/").kind, "field")
        self.assertEqual(self.s.find("Sam").kind, "field")
        self.assertIsNone(self.s.find("Nope"))
        self.assertEqual(self.s.find(2).label, "Your name")


class ChecksTest(unittest.TestCase):
    def test_small_and_unnamed(self):
        cell = config.Cell("web", "iphone-se")
        s = Screen("x.png", 400, 800, [Element("button", "", 100, 100, 50, 50),
                                       Element("button", "Hide", 200, 200, 30, 30)],
                   notes=["crash: the app is no longer running"])
        titles = {i["title"] for i in run_checks(s, cell, {"a11y", "crash"})}
        self.assertIn("Control with no accessibility label", titles)
        self.assertIn("Touch target under 44", titles)
        self.assertIn("App crashed or closed", titles)

    def test_dedupe(self):
        i = {"title": "A", "severity": "minor", "details": "d", "screen": "1.png", "test": "t"}
        out = dedupe([i, dict(i, screen="2.png"), {"title": "B", "severity": "blocker", "screen": None, "test": "t"}])
        self.assertEqual(out[0]["title"], "B")
        self.assertEqual(out[1]["screens"], ["1.png", "2.png"])


class ReportTest(unittest.TestCase):
    def test_reports(self):
        cell = config.Cell("web", "iphone-se").to_dict()
        results = [{"cell": cell, "skipped_settings": [], "tests": [
            {"name": "t1", "kind": "steps", "status": "failed", "seconds": 1, "screens": [],
             "issues": [{"title": "Expected <Saved>", "severity": "major", "details": "&", "screens": []}]}]}]
        out = Path(tempfile.mkdtemp())
        summary, files = report.write_all(results, {"name": "X", "report": {}, "ai": {}}, out)
        self.assertFalse(summary["ok"])
        import xml.dom.minidom
        xml.dom.minidom.parse(str(files["junit"]))
        self.assertIn("Expected &lt;Saved&gt;", files["html"].read_text())


if __name__ == "__main__":
    unittest.main()
