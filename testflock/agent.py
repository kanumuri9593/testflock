"""AI tester: looks at each screenshot, decides the next tap, and reports issues.

Providers (qa.yml `ai.provider`):
  none         no AI; agent tests are skipped and the crawler runs instead
  anthropic    Claude API with your key (ANTHROPIC_API_KEY, or `ai.api_key_env`).
               `ai.base_url` points it at any Anthropic-compatible API instead
               (OpenRouter, a gateway, a local proxy), billed to that account.
  claude-code  Claude Code CLI (`claude -p`), so a Claude Pro/Max subscription
               pays (CLAUDE_CODE_OAUTH_TOKEN in CI, from `claude setup-token`).
"""
import base64
import io
import json
import os
import shutil
import subprocess

SYSTEM = """You are a careful QA tester using a real {platform} app on {device} \
(language {locale}, {orientation}, network {network}, {theme} mode, text size {text_size}).
Persona: {persona}
Goal: {goal}

Each turn you get a screenshot and a numbered list of on-screen elements (centre positions in \
the screenshot's pixels). Use exactly one tool per turn. Prefer tapping by element number.
Report every real problem with report_issue as soon as you see it: crashes, dead ends, wrong or \
untranslated text, cut or overlapping text, controls hidden by the keyboard, notch or home bar, \
confusing steps, missing feedback, broken offline or slow-network behaviour, accessibility gaps.
Rules: never delete real data, sign out, buy, or send messages to anyone. A blocked step is a \
finding, then try another way, as a real user would. You have about {budget} actions; call finish \
before you run out, with an honest score out of 10 from the persona's point of view."""

TOOLS = [
    {"name": "tap", "description": "Tap an element by its number, or a position in screenshot pixels.",
     "input_schema": {"type": "object", "properties": {
         "element": {"type": "integer"}, "x": {"type": "integer"}, "y": {"type": "integer"},
         "why": {"type": "string"}}, "additionalProperties": False}},
    {"name": "long_press", "description": "Long press an element by its number.",
     "input_schema": {"type": "object", "properties": {"element": {"type": "integer"}},
                      "required": ["element"], "additionalProperties": False}},
    {"name": "type_text", "description": "Type text. Give `element` to tap a field first. `enter` presses return.",
     "input_schema": {"type": "object", "properties": {
         "text": {"type": "string"}, "element": {"type": "integer"}, "enter": {"type": "boolean"}},
         "required": ["text"], "additionalProperties": False}},
    {"name": "scroll", "description": "Scroll the screen.",
     "input_schema": {"type": "object", "properties": {"direction": {"type": "string", "enum": ["down", "up"]}},
                      "required": ["direction"], "additionalProperties": False}},
    {"name": "back", "description": "Go back (system back, swipe back or browser back).",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "relaunch", "description": "Close and reopen the app (to check what was saved).",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "report_issue", "description": "Report one problem you can see on the current screen.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"},
         "severity": {"type": "string", "enum": ["blocker", "major", "minor", "cosmetic"]},
         "details": {"type": "string", "description": "Steps, what happened, what you expected."}},
         "required": ["title", "severity", "details"], "additionalProperties": False}},
    {"name": "finish", "description": "End the test with a short verdict.",
     "input_schema": {"type": "object", "properties": {
         "summary": {"type": "string"}, "goal_reached": {"type": "boolean"},
         "score": {"type": "integer", "minimum": 0, "maximum": 10}},
         "required": ["summary", "goal_reached", "score"], "additionalProperties": False}},
]


def _image(screen, max_side=1280):
    """PNG bytes for the model, shrunk if large. Returns (base64, factor)."""
    data = open(screen.png, "rb").read()
    factor = 1.0
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        big = max(img.size)
        if big > max_side:
            factor = max_side / big
            img = img.convert("RGB").resize((round(img.size[0] * factor), round(img.size[1] * factor)))
            buf = io.BytesIO()
            img.save(buf, "PNG")
            data = buf.getvalue()
    except ImportError:
        pass
    return base64.standard_b64encode(data).decode(), factor


def _elements_text(screen, factor):
    lines = []
    for i, e in enumerate(screen.elements[:80]):
        v = f' value="{e.value[:30]}"' if e.value and e.value != e.label else ""
        lines.append(f'[{i}] {e.kind} "{e.label[:60]}"{v} at ({round(e.x * factor)},{round(e.y * factor)})')
    return "\n".join(lines) or "(no elements found: use x/y on the screenshot)"


def _act(driver, screen, name, args, factor):
    """Run one tool call on the device. Returns a short text result."""
    def el_xy():
        if args.get("element") is not None:
            e = screen.find(int(args["element"]))
            if e is None:
                raise ValueError(f"no element {args['element']}")
            return e.x, e.y
        if "x" in args and "y" in args:
            return args["x"] / factor, args["y"] / factor
        raise ValueError("give element or x and y")

    if name == "tap":
        driver.tap(*el_xy())
    elif name == "long_press":
        driver.long_press(*el_xy())
    elif name == "type_text":
        if args.get("element") is not None:
            driver.tap(*el_xy())
        driver.type_text(args["text"])
        if args.get("enter"):
            driver.press_enter()
    elif name == "scroll":
        driver.scroll(args.get("direction", "down"))
    elif name == "back":
        driver.back()
    elif name == "relaunch":
        driver.relaunch()
    return "done"


class _Anthropic:
    def __init__(self, ai):
        import anthropic
        key = os.environ.get(ai.get("api_key_env", "ANTHROPIC_API_KEY"))
        kw = {"api_key": key} if key else {}
        if ai.get("base_url"):
            kw["base_url"] = ai["base_url"]
        self.client = anthropic.Anthropic(**kw)
        self.model = ai.get("model", "claude-opus-5-5")
        self.effort = ai.get("effort", "low")
        self.fallbacks = ai.get("fallbacks", "default") and not ai.get("base_url")
        self.usage = {"input": 0, "output": 0, "cache_read": 0}

    def turn(self, system, messages):
        kw = dict(model=self.model, max_tokens=4000, system=system, tools=TOOLS, messages=messages,
                  output_config={"effort": self.effort}, cache_control={"type": "ephemeral"})
        if self.fallbacks:
            resp = self.client.beta.messages.create(betas=["server-side-fallback-2026-07-01"],
                                                    fallbacks="default", **kw)
        else:
            resp = self.client.messages.create(**kw)
        u = resp.usage
        self.usage["input"] += u.input_tokens or 0
        self.usage["output"] += u.output_tokens or 0
        self.usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        return resp


def run_agent(driver, test, cfg, on_screen, add_issue):
    ai = cfg.get("ai") or {}
    provider = ai.get("provider", "none")
    agent = test.get("agent") or {}
    budget = int(agent.get("max_actions", 30))
    c = driver.cell
    system = SYSTEM.format(platform=c.platform, device=c.device, locale=c.locale, orientation=c.orientation,
                           network=c.network, theme=c.theme, text_size=c.text_size, budget=budget,
                           persona=agent.get("persona", "a first-time user who is busy and not technical"),
                           goal=agent.get("goal", "Explore the main features as a new user."))
    if provider == "claude-code":
        return _run_claude_code(driver, system, budget, on_screen, add_issue, ai)
    if provider != "anthropic":
        return {"skipped": "ai.provider is none: agent test skipped (set ai.provider to use it)"}
    llm = _Anthropic(ai)
    messages, verdict = [], None
    screen = driver.screen("agent-start")
    on_screen(screen, "agent start")
    pending_results = []
    for step in range(budget + 3):
        b64, factor = _image(screen)
        content = list(pending_results) + [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
            {"type": "text", "text": f"Screen {step + 1}. Elements:\n{_elements_text(screen, factor)}"
                                     + (f"\nDriver notes: {'; '.join(screen.notes)}" if screen.notes else "")
                                     + (f"\n{budget - step} actions left." if step >= budget - 5 else "")}]
        messages.append({"role": "user", "content": content})
        resp = llm.turn(system, messages)
        if resp.stop_reason == "refusal":
            verdict = {"summary": "The model declined to continue.", "goal_reached": False, "score": None}
            break
        messages.append({"role": "assistant", "content": resp.content})
        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:
            pending_results = [{"type": "text", "text": "Use one of the tools."}]
            continue
        pending_results, acted = [], False
        for call in calls:
            args = call.input if isinstance(call.input, dict) else json.loads(call.input)
            if call.name == "report_issue":
                add_issue({"title": args["title"], "severity": args["severity"], "kind": "agent",
                           "details": args["details"], "screen": screen.png})
                result = "noted"
            elif call.name == "finish":
                verdict = args
                result = "ok"
            else:
                try:
                    result = _act(driver, screen, call.name, args, factor)
                    acted = True
                except Exception as e:  # a bad index must not end the test
                    result = f"error: {e}"
            pending_results.append({"type": "tool_result", "tool_use_id": call.id, "content": result,
                                    **({"is_error": True} if str(result).startswith("error") else {})})
        if verdict:
            break
        if acted:
            screen = driver.screen(f"agent-{calls[-1].name}")
            on_screen(screen, f"agent {calls[-1].name}")
    out = {"verdict": verdict or {"summary": "Ran out of actions.", "goal_reached": False, "score": None},
           "usage": llm.usage, "model": llm.model}
    return out


def _run_claude_code(driver, system, budget, on_screen, add_issue, ai):
    """Same loop through `claude -p`, one call per screen, resuming one session."""
    if not shutil.which("claude"):
        return {"skipped": "claude CLI not found (npm i -g @anthropic-ai/claude-code)"}
    session, verdict = None, None
    screen = driver.screen("agent-start")
    on_screen(screen, "agent start")
    howto = ('Reply with ONE JSON object only, one of: {"tap": N} | {"tap_xy": [x, y]} | '
             '{"type": "text", "element": N, "enter": true} | {"scroll": "down"|"up"} | {"back": true} | '
             '{"relaunch": true} | {"finish": {"summary": "...", "goal_reached": true, "score": 7}}. '
             'Add "issues": [{"title": "...", "severity": "major", "details": "..."}] for problems on this screen.')
    for step in range(budget + 2):
        prompt = ((system + "\n\n" + howto + "\n\n") if session is None else "") + \
            f"Screen {step + 1}: read the image {screen.png}\nElements:\n{_elements_text(screen, 1.0)}"
        cmd = ["claude", "-p", prompt, "--output-format", "json", "--allowedTools", "Read",
               "--model", ai.get("model", "sonnet")]
        if session:
            cmd += ["--resume", session]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        try:
            meta = json.loads(r.stdout)
            session = meta.get("session_id", session)
            text = meta.get("result", "")
            action = json.loads(text[text.find("{"):text.rfind("}") + 1])
        except (json.JSONDecodeError, ValueError):
            continue
        for i in action.get("issues", []):
            add_issue({"title": i.get("title", "Issue"), "severity": i.get("severity", "minor"),
                       "kind": "agent", "details": i.get("details", ""), "screen": screen.png})
        if "finish" in action:
            verdict = action["finish"]
            break
        try:
            if "tap" in action:
                _act(driver, screen, "tap", {"element": action["tap"]}, 1.0)
            elif "tap_xy" in action:
                _act(driver, screen, "tap", {"x": action["tap_xy"][0], "y": action["tap_xy"][1]}, 1.0)
            elif "type" in action:
                _act(driver, screen, "type_text", {"text": action["type"], "element": action.get("element"),
                                                   "enter": action.get("enter")}, 1.0)
            elif "scroll" in action:
                driver.scroll(action["scroll"])
            elif "back" in action:
                driver.back()
            elif "relaunch" in action:
                driver.relaunch()
        except Exception:
            pass
        screen = driver.screen("agent")
        on_screen(screen, "agent")
    return {"verdict": verdict or {"summary": "Ran out of actions.", "goal_reached": False, "score": None},
            "model": f"claude-code:{ai.get('model', 'sonnet')}"}
