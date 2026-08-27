# SMSM Festival Ops

A Discord bot that runs a food festival kitchen. Someone types or says
**"we need 2 bechamel, 2 foul sandwich and 3 koshary trays"** in a channel, and:

1. All three items land separately on a live prep board
2. The kitchen speaker says it aloud, once, clearly
3. A card appears that the kitchen taps to claim
4. If nobody claims it in 7 minutes, it asks again

Built for the SMSM Festival in North Tonawanda, NY. Runs on a laptop or a small
cloud box.

---

## Why it exists

The previous system was an open Discord voice channel with a speaker in the kitchen
and live mics on the floor. That arrangement has three failure modes built into it:

| Problem | Cause |
|---|---|
| Deafening echo | A speaker and an open mic in one room is an acoustic feedback loop. Not a settings issue — physics. |
| People talking over each other | One shared channel, no turn-taking. |
| A person tied up relaying messages | No acknowledgment path, so a human became one. |

**The fix is one-directional audio.** Nobody holds an open mic. People type, dictate,
or send a voice message; the bot is the only thing that ever transmits. Feedback
becomes impossible, messages queue instead of colliding, and a tap on a button
replaces the human relay.

---

## What's in the box

| Piece | What it does |
|---|---|
| `bot.py` | Everything — parser, TTS queue, speech-to-text, Discord commands, web server |
| `config.json` | Menu, aliases, phrase→status mapping, prep times, voice and dashboard settings |
| `web/kitchen.html` | Big-text screen for the kitchen wall. Only what needs action |
| `web/command.html` | Full board + live request feed for the command center |
| `tests/` | Parser test suite. Run these before changing the parser |
| `deploy/` | Dockerfile, compose file, systemd unit |
| `docs/` | Architecture, deployment, day-of operations, Discord onboarding text |

Single file by design. It's ~1900 lines and one person needs to be able to read all
of it at 6pm on a Saturday with a phone in one hand.

---

## Quick start (local)

```bash
git clone <this-repo> && cd smsm-festival-ops
python3.12 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env          # then paste your bot token into it
./.venv/bin/python bot.py
```

Requires **Python 3.12** and **ffmpeg** (`brew install ffmpeg` / `apt install ffmpeg`).

> Python 3.13 removed the `audioop` stdlib module that discord.py's voice support
> needs. 3.12 is the tested path. 3.13+ works via the `audioop-lts` backport, which
> `requirements.txt` pulls in conditionally, but it's less proven.

Then in Discord: `/setup_server` → `/board` → `/tts_join`.
`/screens` prints the dashboard URLs.

Non-technical users: double-click `scripts/FIX-AND-START.command` (macOS) or
`scripts/run-windows.bat`.

---

## How the parser works

Plain English in, structured status out. Five levels: `good` `low` `need`
`prepping` `out`.

```
we need 2 bechamel, 2 foul sandwich and 3 koshary trays  → 3 × NEED NOW
two trays of koshary left                                → LOW · "two trays left"
down to one pan of mac bechamel                          → NEED · "one pan left"
falafel is out but koshary is fine                       → OUT + GOOD
bring 4 bags of ice and 2 propane tanks                  → 2 × NEED
we are good on fries                                     → clears the alert
```

Three things worth knowing before you touch it:

- **It distinguishes "2 left" from "need 2."** Remaining vs. requested are opposite
  meanings. `_REMAINING_RE` decides which, and only a *remaining* count escalates
  urgency.
- **Unit words are disambiguated from items.** "2 trays of foul" means ful, not
  serving trays — but "we need 4 trays" does mean trays. See `_is_unit_usage`.
- **Silence is a feature.** If an item matches but no urgency phrase does, the board
  updates and the speaker stays quiet, and the card is marked *(unconfirmed)*. A
  kitchen speaker that cries wolf gets ignored by hour two, and then it's worse than
  useless.

284 spelling aliases cover what speech-to-text actually produces for Egyptian dish
names (bashamel, kushari, shwarma, tameya, hawashy, kunafa…). Add more under
`items[].aliases` — no code change needed.

**Run `pytest` before and after any parser change.** There are 17 phrase cases and
they exist because each one was a real bug.

---

## Voice

Two paths, both one-directional:

- **Text / dictation → TTS.** gTTS renders, ffmpeg plays into the voice channel.
- **Discord voice message → played back, then transcribed.** faster-whisper runs
  locally, so no audio leaves the building. Transcription is optional; without it
  recordings still play, they just don't move the board.

Everything goes through one `asyncio.Queue` so two announcements can never overlap.

---

## Configuration

| Key | Purpose |
|---|---|
| `items[].aliases` | Every spelling people say |
| `items[].screen` | Show on the big kitchen screen (keep this list short) |
| `items[].prep_min` | Default prep time; `/preptime` overrides at runtime |
| `phrases` | Plain English → status level |
| `voice.speak_levels` | Which levels interrupt the kitchen |
| `voice_input.model` | `tiny.en` / `base.en` / `small.en` |
| `behavior.nag_minutes` | Minutes before an unclaimed request is re-announced |
| `dashboard.access_token` | **Set this before exposing the dashboards publicly** |

Env overrides: `DISCORD_TOKEN`, `SMSM_CONFIG`, `SMSM_STATE_DIR`, `SMSM_DASH_TOKEN`,
`PORT`.

---

## Deploying

See [`docs/DEPLOY.md`](docs/DEPLOY.md). Short version: it's a single long-running
process with a small volume for `state.json`. Docker and systemd files are in
`deploy/`.

**One caveat that will bite you:** Discord voice needs outbound UDP. Some PaaS tiers
block or NAT it in ways that break audio while text keeps working. Test `/say`
immediately after your first deploy, not the day of the event.

---

## Docs

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how it fits together, where to add things
- [`docs/DEPLOY.md`](docs/DEPLOY.md) — cloud deployment
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — day-of runbook, audio rules, troubleshooting
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — what to build next
- [`docs/discord-onboarding-text.md`](docs/discord-onboarding-text.md) — copy/paste volunteer instructions

---

## License

MIT. See [LICENSE](LICENSE).
