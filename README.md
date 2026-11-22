# Testflock

**A flock of testers on every phone.** One `qa.yml` runs your app on a grid of
devices, screen sizes, languages, orientations, networks, dark mode and text sizes,
on **web, Android and iOS**. Each test is either a short **script** ("tap Add, type
Keys, expect Saved") or an **AI tester** that explores like a new user. You get an
HTML report with every screenshot, JUnit for CI, a Markdown summary for pull
requests, and an email.

It needs no API key: without AI it runs scripts plus a free crawler that taps every
safe control and checks each screen. Bring your own key (or Claude subscription) to
turn on the AI testers.

```bash
pip install "testflock[web,ai] @ git+https://github.com/kanumuri9593/testflock"
playwright install chromium     # web tests only
testflock init                  # writes a starter qa.yml
testflock matrix                # shows every device setup it will run
testflock run --notify          # runs, writes testflock-report/index.html, emails it
```

## What one config covers

| Axis | Web (Playwright) | Android (emulator or USB phone) | iOS (Simulator, macOS) |
|---|---|---|---|
| Device / screen size | 11 presets (iPhone SE to iPad Pro, Pixel, Galaxy, laptop) or your own | emulator profiles (Pixel 8, Nexus 5, tablet) | any Simulator device type |
| Language + region | locale, timezone and geolocation | system locale (rooted emulator image) | AppleLanguages + AppleLocale |
| Orientation | portrait / landscape | portrait / landscape | landscape via the Simulator menu |
| Network | online, offline, wifi, 4g, fast-3g, slow-3g, 2g, flaky | airplane mode; speed and delay on emulators | online only (see below) |
| Theme | light / dark | light / dark | light / dark |
| Text size | small, default, large, largest | font scale 0.85 to 2.0 | Dynamic Type up to the largest accessibility size |
| Clean screenshots | | | status bar at 9:41, full battery |

Settings a platform cannot emulate are listed in the report under "Could not
emulate", never silently ignored. The iOS Simulator shares the Mac's network, so
offline and slow networks on iOS need Apple's Network Link Conditioner, which slows
the whole Mac.

## Tests

```yaml
tests:
  - name: Add a first item
    steps:
      - tap: "Add"                                   # by label, /regex/ or {x, y}
      - type: {into: "Name", text: "Spare keys", enter: true}
      - expect: "Spare keys"
      - relaunch: true                               # kill and reopen: was it saved?
      - expect: "Spare keys"
      - network: offline                             # change network mid-test
      - expect: {not: "Something went wrong"}
  - name: Explore like a new user
    agent:
      persona: "Busy parent, not technical, uses large text"
      goal: "Add a first item and find it again."
      max_actions: 25
  - name: Tap everything (free)
    crawl: {max_actions: 30, avoid: ["Archive"]}
```

Scripts find controls through the accessibility tree on every platform, so the same
script runs on web, Android and iOS, and a control a script cannot find is often one
VoiceOver or TalkBack cannot read either. Flutter web draws on a canvas, so
Testflock switches on Flutter's accessibility tree automatically.

Every screen also gets automatic checks: crashes and uncaught errors, content wider
than the screen, console and network errors, controls with no accessibility label,
touch targets under 44 pt / 48 dp, controls placed off screen. The crawler never
taps labels like delete, sign out, buy or send.

## AI testers

| `ai.provider` | Who pays | Setup |
|---|---|---|
| `none` (default) | nobody | agent tests run as the free crawler |
| `anthropic` | your Anthropic key | `ANTHROPIC_API_KEY`; pick `model` (default `claude-opus-5-5`, `claude-haiku-5-5` costs least) and `effort` |
| `anthropic` + `base_url` | that provider | any Anthropic-compatible API (a gateway, OpenRouter, a proxy) |
| `claude-code` | your Claude Pro/Max subscription | the `claude` CLI; in CI, `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` |

The tester sees each screenshot plus the numbered list of controls, taps by number,
reports issues as it goes, and finishes with a score out of 10 for the persona. The
report shows the token usage per run. Anthropic API calls turn on server-side
fallbacks, so a declined request retries on another model instead of failing.

## Reports and notifications

`testflock-report/` holds `index.html` (every screenshot, issues by severity),
`results.json`, `junit.xml` and `SUMMARY.md` (also written to the GitHub job
summary). `fail_on` sets which severities fail the build.

```yaml
notify:
  when: failure                 # always | failure | never
  email:
    to: [you@example.com]
    via: smtp                   # Gmail app password works; or resend
    smtp: {host: smtp.gmail.com, port: 587}   # SMTP_USER / SMTP_PASSWORD from secrets
  webhooks:
    - {url_env: SLACK_WEBHOOK_URL, kind: slack}  # slack | discord | teams | any URL (JSON)
```

## CI

`action.yml` is a GitHub Action. Ready workflows are in [`templates/`](templates/):

- **web**: builds Flutter web, splits the device setups over 4 parallel Linux jobs
  (`--shard i/4`), merges one report and emails it.
- **android**: one emulator per job on Linux runners (KVM), language changes on the
  rooted `google_apis` image.
- **ios**: your own Mac as a self-hosted runner (free), or GitHub's `macos-15`.

Any other CI runs the same command: `testflock run --shard 1/4`, then
`testflock merge shards/ --notify`.

## Simple by design

```
qa.yml ─► config.expand() ─► cells (device × language × network × ...)
                                │
             one Driver per platform: web.py · android.py · ios.py
                                │  (screen · tap · type · back · scroll · network)
         tests: steps.py (script) · crawl.py (no AI) · agent.py (AI)
                                │
                checks.py on every screen ─► report.py ─► notify.py
```

A new platform (a device farm, desktop, TV) is one new driver file. Presets for
devices, networks and languages are plain data you can extend in `qa.yml` under
`presets:`.

## Credits

Inspired by [mobile-agent-testers](https://github.com/pierridotite/mobile-agent-testers)
by Pierre Raffalli (MIT): AI testers with personas on their own simulators, AXe for iOS
input, and the touch-target check. Testflock is written from scratch and adds web,
scripted tests, network and orientation emulation, a no-AI mode and email. See
[NOTICE.md](NOTICE.md).

MIT License. Made by [One Energy Together](https://studio.oneenergytogether.com).
