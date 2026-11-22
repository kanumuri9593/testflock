"""Agent loop plumbing with a fake model and a fake device (no network, no cost)."""
import tempfile
import unittest
from types import SimpleNamespace as NS
from pathlib import Path

from testflock import agent, config
from testflock.drivers.base import Element, Screen

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


class FakeDriver:
    def __init__(self):
        self.cell = config.Cell("web", "iphone-se")
        self.taps, self.d = [], Path(tempfile.mkdtemp())
        self.n = 0

    def screen(self, name=None):
        self.n += 1
        p = self.d / f"{self.n}.png"
        p.write_bytes(PNG)
        return Screen(str(p), 400, 800, [Element("button", "Add", 200, 700, 200, 50)])

    def tap(self, x, y):
        self.taps.append((x, y))


class FakeLLM:
    model = "fake"

    def __init__(self, ai):
        self.usage = {"input": 1, "output": 1, "cache_read": 0}
        self.turns = 0

    def turn(self, system, messages):
        self.turns += 1
        assert messages[-1]["role"] == "user"
        if self.turns == 1:
            return NS(stop_reason="tool_use", content=[
                NS(type="tool_use", id="a", name="report_issue",
                   input={"title": "Button cut off", "severity": "minor", "details": "x"}),
                NS(type="tool_use", id="b", name="tap", input={"element": 0})])
        return NS(stop_reason="tool_use", content=[
            NS(type="tool_use", id="c", name="finish", input={"summary": "ok", "goal_reached": True, "score": 8})])


class AgentTest(unittest.TestCase):
    def test_loop(self):
        agent._Anthropic = FakeLLM
        d, issues = FakeDriver(), []
        out = agent.run_agent(d, {"agent": {"goal": "add"}}, {"ai": {"provider": "anthropic"}},
                              lambda s, l: None, issues.append)
        self.assertEqual(d.taps, [(200, 700)])
        self.assertEqual(issues[0]["title"], "Button cut off")
        self.assertEqual(out["verdict"]["score"], 8)

    def test_none_provider_skips(self):
        out = agent.run_agent(FakeDriver(), {"agent": {}}, {"ai": {"provider": "none"}}, None, None)
        self.assertIn("skipped", out)


if __name__ == "__main__":
    unittest.main()
