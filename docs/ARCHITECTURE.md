# Architecture

One file, `bot.py`, ~1900 lines. That's deliberate — during an event one person has
to be able to read the whole thing on a laptop with a phone in the other hand. If
you split it, split along the section banners already in the file.

## Data flow

```
Discord message in #kitchen-requests
        │
        ├── has an audio attachment? ──► handle_voice_note()
        │                                  ├─► tts.play_file()   plays the recording
        │                                  └─► stt.transcribe()  → text (optional)
        │
        ▼
   parse_all(text)  ──►  [{item, level, detail, explicit}, …]
        │
        ├─► set_level() per item        writes STATE, appends to feed + CSV
        ├─► compose_announcement()      ONE spoken line for the whole message
        ├─► tts.speak()                 queued, never overlaps
        ├─► message.reply(embed, view)  AckView or BatchAckView
        └─► refresh_board()             edits the pinned Discord embed

   watchdog (1 min)   ──► unclaimed > nag_minutes → re-announce + ping
                      └─► prepping past ETA       → "past ready time"

   aiohttp :8080      ──► /kitchen  /  /api/state   (2s polling)
```

## The pieces

### `parse_all(text) -> list[dict]`
The core. Normalises, splits into clauses on `, ; / & and also plus but then`,
finds an item and a level per clause, and infers quantity semantics.

Key invariants, all covered by tests:

- **Clause splitting happens after normalisation but punctuation is preserved.**
  `_norm` keeps `, ; / &` precisely so `_CLAUSE_SPLIT` can use them. An earlier
  version stripped them first and silently merged clauses — that bug ate one item
  out of every three-item message.
- **`_is_unit_usage` separates counting words from items.** "2 trays of foul" =
  ful measured in trays. "we need 4 trays" = actual trays. The rule: a unit word
  preceded by a number is a unit *unless it's the only candidate in the clause*.
- **`_REMAINING_RE` decides what a number means.** With remaining context, a small
  number escalates urgency (1 left → NEED). Without it, the number is a request
  quantity and must not escalate anything.
- **`explicit=False` means "don't interrupt."** Item matched, urgency didn't. The
  board updates silently. Preserve this behaviour.

### `TTSEngine`
One `asyncio.Queue` carrying two job kinds — `tts` (gTTS renders to mp3) and
`file` (an existing recording). Both play through `FFmpegPCMAudio`.

`_ensure_connected()` exists because `guild.voice_client` can be non-None and dead
after a restart or network blip; playing into it fails *silently*. It tears down and
reconnects, up to 3 attempts. Don't remove it.

`muted()` gates everything — that's `/mute`, for speeches and prayers.

### `Transcriber`
Wraps faster-whisper, loaded once at `on_ready`. Entirely optional: if the import
fails, `available` stays False, recordings still play, and startup says so. Any
change here must keep that degradation path.

### State
`STATE` dict → `state.json`, written atomically (tmp + rename) after **every**
change. That's what makes a crash or a yanked power cord a non-event. `STATE_DIR`
is env-overridable for containers.

`request_log.csv` is append-only across all days — the audit trail and the input to
next year's prep planning.

### Views
`AckView` (single item) and `BatchAckView` (multi) are persistent — registered in
`on_ready` via `add_view`, so buttons still work after a restart. `AckView` recovers
the item id from the embed footer (`id:<item_id>`); keep that footer format if you
touch the embeds.

### Web
aiohttp on the same event loop. Pages are read from disk per request, so you can
edit `web/*.html` and refresh without restarting the bot.

Port binding walks `base … base+3` on `EADDRINUSE` rather than crashing, because a
dead screen at a festival is worse than a surprising port number.

`authorised()` is a no-op when no token is configured. **Set a token before putting
this on a public IP.**

## Conventions

- Money and unit counting were deliberately removed. Levels only. Every attempt to
  reintroduce exact counts died on the same rock: nobody updates them honestly
  during a rush.
- All user-facing strings live at their call site, not in a constants file. Easier
  to fix under pressure.
- Config over code: new items, spellings, and phrasings should never need a commit.

## Adding a feature

1. Does it need a new config key? Add it with a `_comment_*` sibling explaining it.
2. Touching the parser? Add cases to `tests/test_parser.py` **first**.
3. Anything that speaks: route through `tts.speak`/`tts.play_file` so it queues and
   respects mute.
4. Anything shown to the kitchen: ask whether it earns a spot on the big screen.
   The screen's value is that it's mostly empty.
