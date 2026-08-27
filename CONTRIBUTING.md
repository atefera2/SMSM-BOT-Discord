# Contributing

## Setup

```bash
python3.12 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt pytest
cp .env.example .env      # paste a bot token from a TEST Discord server
```

Use a throwaway Discord server for development. Do not develop against the live
festival server — `/setup_server` creates channels and `/allclear` wipes the board.

## Before every commit

```bash
pytest
```

44 tests, runs in under a second. They import `bot.py` directly and never touch
Discord.

## Rules of the road

1. **The kitchen path must never depend on something that can fail.** New
   integrations go behind a timeout with a fallback to current behaviour.
2. **Parser changes need tests first.** Add the failing case to
   `tests/test_parser.py`, then fix it. Every existing case is a real bug that got
   caught.
3. **Config over code.** New menu items, spellings, and phrasings must not require
   a commit — they go in `config.json`.
4. **Anything that makes noise goes through `tts.speak` / `tts.play_file`** so it
   queues properly and respects `/mute`.
5. **Think hard before adding to the kitchen screen.** Its value is that it's
   mostly empty. `screen: false` is the default answer.
6. **Never commit `.env`, `state.json`, or `request_log.csv`.** `.gitignore` covers
   them; don't `git add -f` around it.

## Testing voice locally

Voice needs ffmpeg plus a real Discord connection. `/audio` in Discord is the
diagnostic — it checks ffmpeg, connection liveness, whether anyone is actually in
the channel, Speak permission, server-mute, and queue depth.

`config.json` → `voice_input.transcribe: false` skips loading the whisper model,
which makes restarts much faster while iterating.

## Style

No formatter is enforced. Match what's there: 4-space indent, ~90 column soft wrap,
comments that explain *why* rather than *what*.
