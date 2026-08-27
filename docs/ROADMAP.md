# Roadmap

Ordered by value per hour of work. Everything here is optional — the system is
complete and has run a festival as-is.

Ground rule for all of it: **the kitchen path must keep working when the new thing
fails.** Every feature below should degrade to current behaviour, not to an error.

---

## Tier 1 — highest value

### 1. Claude API for the messages the parser can't handle
The regex parser is fast, free, and deterministic, and it handles the 90% of
messages that sound like the examples. The other 10% — *"the doro tray on the end
is looking thin, maybe twenty minutes worth"* — currently get spoken and logged but
don't move the board.

**Hybrid design, in this order:**
1. `parse_all()` runs first. If it returns results, use them. Nothing changes.
2. Only if it returns nothing, call Claude with the item list and ask for the same
   `{item, level, detail}` shape.
3. Timeout at ~3s and fall back to today's behaviour.

Also worth wiring: `@bot how much koshary is left?` answering from `STATE`, and
`@bot status rundown` for shift changes.

Cost is a few dollars for a festival weekend on a small model. The reason to keep it
off the primary path isn't cost — it's that an API timeout during a Saturday rush
must not delay a NEED NOW announcement.

### 2. Health endpoint + uptime alert
`GET /health` returning bot latency, voice connected y/n, queue depth, last state
write. Point any free uptime monitor at it and text a lead if it goes down. Cheap,
and it turns "the board looks frozen" into a push notification.

### 3. Per-station screens
`/kitchen?station=Grill` filtered to one line's items. Grill cooks don't need the
dessert table. Small change to the existing filter; big reduction in visual noise.

---

## Tier 2 — clear wins

### 4. POS integration
If the festival ever runs Square or Toast, a webhook that decrements on sale means
nobody types `/sell` at all and the board becomes real-time without human input.
This is the single biggest possible upgrade, and also the most dependent on
decisions outside this repo.

### 5. Historical analytics
`request_log.csv` accumulates across years. "Koushary hit NEED NOW 14 times on
Saturday between 5 and 7pm" turns prep planning from folklore into arithmetic.
A `/report` command or a static page over the CSVs.

### 6. Photo requests
Attach an image to a request — "this is what's left" — and show the thumbnail on
the command center. Removes a lot of ambiguity about what "low" means.

### 7. Prep-time learning
The system knows when *prepping* started and when *ready* was tapped. After a
weekend it can propose better `prep_min` values than anyone's guess. Suggest, don't
auto-apply.

---

## Tier 3 — nice to have

- **Multi-day comparison** on the command center: today vs. yesterday at this hour.
- **Shift handover summary** — `/handover` posting what's outstanding, spoken aloud.
- **Vendor channels** if multiple kitchens ever sell simultaneously.
- **i18n** — Arabic-language announcements alongside English.
- **Mobile-optimised command center**; it's usable on a phone but not designed for it.
- **Web push** to leads for critical incidents.

---

## Explicitly rejected

Not oversights — each was tried or considered and rejected for a reason.

| Idea | Why not |
|---|---|
| Exact unit counts / inventory | Tried first. Nobody updates counts honestly during a rush, and a wrong number is worse than no number. Levels survive contact with a real kitchen. |
| Price and revenue tracking | Built, then removed. It made the board harder to read and answered a question nobody asked mid-service. Do it in the POS. |
| Open voice channel for staff | This is the original problem. Any live mic near the kitchen speaker recreates the echo. |
| Speaking every status change | Tested. Alert fatigue by hour two. Hence `speak_levels` and the `explicit` flag. |
| Splitting `bot.py` into modules | One file is readable under pressure by one tired person. Revisit only if it passes ~3000 lines. |

---

## Before you touch the parser

`pytest` first. The 17 cases in `tests/test_parser.py` each exist because something
broke in a way that would have cost a real request on a real night. In particular:

- comma handling (clause splitting)
- unit-vs-item disambiguation ("2 trays of foul" vs "4 trays")
- remaining-vs-requested quantity semantics
- the `explicit` flag staying False when urgency is unstated

If a change makes one of those fail, the change is wrong, not the test.
