# SMSM Festival — Kitchen Comms & Prep Board
### Build guide: eliminating the echo, the shouting, and the relay person

---

## Why last year was loud, and why this fixes it

You had a speaker in the kitchen and open microphones on the floor, all in one voice channel. That arrangement has three failure modes baked into it, and you hit all three:

| What happened | Why it was inevitable |
|---|---|
| **Echo** | The kitchen speaker plays audio. A microphone in that same room hears it and sends it back. That's an acoustic feedback loop — it isn't a settings problem, it's physics. Any open mic in earshot of the speaker will do this. |
| **People talking over each other** | One shared channel, no turn-taking. Two people key up, both are unintelligible. |
| **Someone had to sit and relay** | Nobody could tell whether the kitchen heard them, so a human became the acknowledgment layer. |

**The fix is to make audio one-directional.** Nobody holds an open microphone. People type — or tap the microphone key on their phone keyboard and just talk, which types for them. The bot reads it aloud in the kitchen in one clean, consistent voice, at a consistent volume, one message at a time.

With exactly one audio source in the channel, feedback is impossible. Cross-talk is impossible — messages queue. And the relay person is replaced by a button the kitchen taps, which everyone sees instantly.

You said you'll have mics around and someone in the kitchen who can man one if needed. That's fine and it's covered — **Part 4** has the rules that let you keep live mics without reintroducing the echo. The short version: anyone who talks wears a headset, never the room speaker's device.

---

## What you're building

**Someone types in `#kitchen-requests`:** *"we have two trays of koshary left"*

Within about a second:

1. The bot recognizes **Koushary**, reads "two trays" as **getting low**, and works out it takes ~25 minutes to make more.
2. The kitchen speaker says: *"Kitchen. Koushary is getting low. Two trays left."*
3. **KOUSHARY** turns amber on the big kitchen screen with the amount and who reported it.
4. A card appears with two buttons the kitchen taps: **On it — prepping** or **Ready now**.
5. Tapping *On it* posts "ready around 7:10 PM" so front of house stops asking.
6. All of it is logged, timestamped, and searchable forever.

Spelling doesn't matter. *koshary, koshari, kushari, kosheri* all work — same for shawarma/shwarma/shawerma, falafel/felafel/tameya, konafa/kunafa/kanafeh, and so on. That list is in `config.json` and you can add to it.

**Three screens, each showing the right amount:**

| Screen | Who | Shows |
|---|---|---|
| **Kitchen wall screen** | Cooks | Huge text. Only what needs action, plus what's being prepped. Everything healthy shrinks to a small tile. |
| **Command center** | Leads | Every item by station, the live request feed, who's on shift. |
| **Discord prep board** | Everyone on a phone | Pinned message that keeps itself updated. |

The two web screens are served by the bot itself. You open a browser on the same Wi-Fi and go to an address — no accounts, no cloud, no subscription.

---

## Part 1 — Get the bot running (30 min, once)

### 1.1 Create the server
Discord → **+** → **Create My Own**. Name it `SMSM Festival Ops`.

### 1.2 Register the bot
1. **https://discord.com/developers/applications** → **New Application** → name it `SMSM Kitchen`.
2. Left sidebar → **Bot**.
3. Scroll to **Privileged Gateway Intents** and turn on **all three** — Presence, **Server Members**, **Message Content** — then **Save Changes**.

> ⚠️ **Message Content Intent is not optional here.** The whole design is "just type a sentence." Without it the bot cannot read what people write and nothing works.

4. **Reset Token** → **Copy**. You see it once. Never post it anywhere.

### 1.3 Invite it
**OAuth2 → URL Generator** → scopes `bot` + `applications.commands` → permission **Administrator** → open the generated URL → pick your server → **Authorize**.

Then in **Server Settings → Roles**, drag the bot's role **above** all other roles.

### 1.4 Install the prerequisites

**Mac** — open Terminal and paste:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python@3.12 ffmpeg
```

**Windows** — install Python from python.org (**tick "Add python.exe to PATH"**), then in PowerShell as Administrator:
```powershell
winget install Gyan.FFmpeg
```

> FFmpeg is what produces the spoken audio. Without it everything else works but the kitchen stays silent. Check with `ffmpeg -version`.

### 1.5 Add your token
Rename `.env.example` → `.env`, open it, paste your token after `DISCORD_TOKEN=`. No quotes, no spaces.

### 1.6 Start it
Double-click **`run-mac.command`** or **`run-windows.bat`**. First launch takes a couple of minutes.

You'll see:
```
[ok] Logged in as SMSM Kitchen — SMSM Festival
[ok] Synced 15 slash commands.
[ok] Kitchen screen   →  http://192.168.1.42:8080/kitchen
[ok] Command center   →  http://192.168.1.42:8080/
```

**Write those two addresses down.** Leave the window open — closing it stops everything.

### 1.7 Build the server
In Discord:
```
/setup_server        creates every channel, role and permission
/board               run this inside #prep-board
/tts_join            connects the bot to the kitchen speaker channel
/screens             shows the screen addresses again any time
```

---

## Part 2 — The screens

On the kitchen TV and the command center screen, open a browser and type the address from `/screens`.

- **Kitchen TV** → `http://<laptop-ip>:8080/kitchen` — then press **F11**, or double-click anywhere, for fullscreen.
- **Command center** → `http://<laptop-ip>:8080/`

Both refresh themselves every 2 seconds. The dot in the top-left is green while connected; if the laptop drops off Wi-Fi it turns red and blinks, so you'll know immediately rather than staring at stale numbers.

**Kitchen screen layout, top to bottom:**

1. **Red and amber panels** — anything OUT, NEEDED, or LOW. Biggest text on the screen, sized to read from across a kitchen. Red pulses gently.
2. **Blue strip** — what's being prepped and roughly when it's ready.
3. **Small tiles** — everything that's fine. Deliberately small; they're not what you look at.

When nothing is wrong the whole screen says **ALL CLEAR** in large green text. That's a useful signal on its own — it means the cooks can trust a glance.

Which items appear on the kitchen screen is the `"screen": true` flag in `config.json`. Right now that's the 23 things cooks actually fire. Drinks, desserts, and supplies are tracked but stay off the kitchen wall — they show on the command center instead. Change any of them any time.

> **Any browser works.** An old iPad, a spare laptop, a Fire tablet, a smart TV's built-in browser, a $35 Chromecast with a browser app. It's a plain web page on your own Wi-Fi.

---

## Part 3 — How people actually use it

### The only thing to teach volunteers

> **In `#kitchen-requests`, either type it or hold the mic button and say it.**

That's the entire training. There are three ways in, and they all end up in the same place:

| Way in | How | What the kitchen gets |
|---|---|---|
| **Type it** | Normal typing | Clean synthesized voice + board updates |
| **Dictate it** | Tap the mic key on your phone **keyboard**, speak, send | Same as typing — the phone converts it |
| **Voice message** | Hold the mic button in the **message box**, talk, release | **Your actual voice** plays in the kitchen, and the board updates from the transcript |

**Voice messages are the hands-busy option.** Hold, talk, release — about two seconds of effort. The recording plays through the kitchen speaker in your own voice, and the bot transcribes it in the background so *"two trays of koshary left"* still turns KOUSHARY amber on the wall screen.

It still can't echo. A voice message is a recording, not an open microphone — there's no live mic anywhere in the loop.

Clips longer than 45 seconds are rejected so nobody monopolizes the speaker. Change that with `voice_input.max_seconds`.

#### Turning on transcription

Voice messages **play** with no extra setup. To also have them **move the board**, install the speech engine once:

```bash
cd ~/Desktop/smsm-festival-bot
./.venv/bin/pip install faster-whisper
```

Restart the bot. First launch downloads a ~150 MB model, then you'll see:

```
[ok] Speech-to-text ready — spoken messages will update the board.
```

It runs entirely on your laptop — no account, no API key, no audio leaving the building. On a modern laptop a five-second clip transcribes in about a second.

If you skip this, nothing breaks. Voice messages still play in the kitchen; they just log as "voice message" instead of parsed text. The startup window tells you which mode you're in.

Accuracy tuning is `voice_input.model` in `config.json`: `tiny.en` (fastest), `base.en` (default), `small.en` (most accurate, a bit slower). In a loud room, `small.en` is worth the extra second.

#### Typed and dictated examples

These all work:

| Someone types | Bot understands | Kitchen hears |
|---|---|---|
| "we have two trays of koshary left" | Koushary — **getting low** | *"Koushary is getting low. Two trays left."* |
| "we're out of falafel" | Falafel — **out** | *"Falafel is out."* (said twice) |
| "need more tawook asap" | Tawook — **need now** | *"Need Tawook now."* (said twice) |
| "down to one pan of mac bechamel" | Mac Bechamel — **need now** | *"Need Mac Bechamel now. One pan left."* |
| "half a tray of hummus left" | Hummus — **need now** | *"Need Hummus now."* |
| "prepping more kofta now" | Kofta — **prepping** | *(silent — no interruption needed)* |
| "we are good on fries" | Fries — **good** | *(silent — clears the alert)* |
| "someone bring napkins to booth 3" | Napkins — **need now** | *"Need Napkins now."* |
| "the front gate needs another table" | no item matched | *spoken aloud and logged anyway* |

That last row matters: **a message that doesn't match any item still gets spoken and still gets remembered.** The channel works for anything, not just the tracked list.

### When the bot isn't sure

If someone names an item without saying how bad it is — *"can somebody check the propane tank"* — the bot marks it on the board but **stays silent** and labels the card *(unconfirmed)*. This is deliberate. A kitchen speaker that cries wolf gets ignored by hour two, and then it's worse than useless. Only clear signals interrupt the cooks.

### Closing the loop — the part that replaces the relay person

Every low/need/out card carries three buttons:

| Button | Effect |
|---|---|
| **On it — prepping** | Item turns blue, an ETA is calculated from that item's prep time, and everyone sees "ready around 7:10 PM." |
| **Ready now** | Item returns to green, and the **front of house speaker** announces "Koushary is ready for pickup." |
| **Say it again** | Repeats the announcement in the kitchen. For when the fryer was going. |

The kitchen person taps a button instead of shouting back. Front of house sees it without asking. Nobody sits there relaying.

### Optional commands

Nobody has to learn these, but leads will want them:

| Command | Does |
|---|---|
| `/status` | Private snapshot of everything low or out |
| `/set` | Set an item's status directly from a dropdown |
| `/history` | Everything said about one item today |
| `/say` | Speak something without changing any status |
| `/screens` | The two screen addresses |
| `/incident` | Flag a problem to the leads, spoken on both speakers |
| `/checkin` `/checkout` | Volunteer hours |
| `/export` | Download the memory bank |
| `/allclear` | Reset every item to Good — run each morning |
| `/help_festival` | The in-Discord version of this section |

---

## Part 4 — Audio setup: the rules that keep the echo gone

**This is the most important page in this guide.** Get these five rules right and last year's problem does not come back.

### Rule 1 — The room speaker's device has no microphone, ever

Whatever device is plugged into the kitchen speaker (tablet, old phone, spare laptop) joins the **🔊 KITCHEN SPEAKER** channel and:

- In Discord, click the **microphone icon** to mute it. Then, in **User Settings → Voice & Video**, set **Input Device** to something that doesn't exist, or physically unplug/disable the mic.
- On a tablet, revoke Discord's microphone permission in the OS settings. That's the bulletproof version.

If that device's mic is live, you get the echo back. Everything else is secondary to this.

### Rule 2 — Anyone who talks wears a headset, never a room speaker

You mentioned having someone man a mic in the kitchen. That's fine — **as long as they're wearing a headset with one earbud in**, not talking into the device that's driving the room speaker.

A headset mic sits an inch from their mouth and hears almost nothing from the room. The room speaker's audio never reaches it at a level that matters. Kitchen noise stops being a problem too.

**Cheap and correct:** any $20 USB or 3.5mm headset with a boom mic. One per person who needs to talk. Wired beats Bluetooth here — no pairing drops, no battery, no latency.

### Rule 3 — Push-to-talk on every microphone. No exceptions.

For every person with a mic: **User Settings → Voice & Video → Input Mode → Push to Talk**, and bind a key.

Voice Activity mode means their mic is open whenever the room is loud — which, in a festival kitchen, is always. Push-to-talk means the mic is off unless a finger is held down. This single setting eliminates the "everyone's mic is hot" problem.

### Rule 4 — Talkers and the room speaker go in different places

Put the people who talk in a **separate voice channel** from the one the room speaker sits in. The bot speaks into the speaker channel; humans talk in the other. They never share air.

If you'd rather have live human voice in the kitchen too, that's what **🔊 FRONT OF HOUSE SPEAKER** is for — the bot uses it for "ready for pickup" announcements, and it's a natural place to put a second speaker away from the mics.

### Rule 5 — Prefer typing. It's faster than you think.

A phone-dictated message takes about four seconds and arrives perfectly legible, timestamped, attributed, logged, and spoken in a voice engineered to cut through noise. A shouted message takes about the same and arrives as "WHAT?"

Keep the mics for the genuine exceptions — a fire, a medical issue, a lead needing to coordinate in real time. That's maybe five times across three days. For the other four hundred messages, typing wins.

### Kitchen speaker placement

- Point it **away from** any live microphone, and away from hard reflective walls.
- Chest height or higher, not on the floor, not behind equipment.
- Loud enough to hear over a fryer, no louder. If you have to shout over the speaker, it's too loud.
- Test it with the fryers and the exhaust hood **running**. A quiet-room test tells you nothing.

---

## Part 5 — The memory bank

Everything is remembered. Three ways to get at it:

- **`/history koshary`** — every message about Koushary today, with who and when.
- **The command center feed** — live scrolling column of everything said, all day.
- **`/export`** — two CSVs plus a summary of *which items hit "need now" or "out" most often.*

That last one is the real prize. After Sunday you'll know exactly which five things you under-prepped and by roughly how much. That converts a gut feeling into a prep sheet for next year — and it's the difference between guessing again and knowing.

`request_log.csv` in the bot folder accumulates across all three days and survives restarts.

---

## Part 6 — Day-of runbook

### The night before
- [ ] Read `config.json` and adjust `prep_min` for anything whose timing you know better than I guessed.
- [ ] Add any nicknames your crew uses to the `aliases` lists.
- [ ] Charge every tablet and headset.
- [ ] **Test on site, on the venue's Wi-Fi.** Confirm the kitchen TV can load the screen address. This is the one thing that can't be tested from home.

### 90 minutes before doors
- [ ] Start the bot. Confirm the two screen addresses print.
- [ ] Kitchen TV on the `/kitchen` page, fullscreen. Command center on `/`.
- [ ] Speaker device joined, **mic disabled**, volume set with the fryers running.
- [ ] `/say testing one two three` — heard clearly in the kitchen.
- [ ] Every headset on **push-to-talk**.
- [ ] Post in `#start-here`: *"Type what you'd say in #kitchen-requests. On your phone, tap the mic key on your keyboard and talk."*
- [ ] `/allclear` to reset the day.
- [ ] Laptop plugged in, lid open, **DO NOT CLOSE** sign taped on.

### During service
Cooks watch the wall. Leads watch the command center. Everyone else types. Kitchen taps buttons.

### At close
- [ ] `/export` → save both CSVs, email them to yourself immediately.
- [ ] `/allclear` before the next day.

---

## Part 7 — Troubleshooting

| Symptom | Cause and fix |
|---|---|
| **Echo is back** | A live mic is in earshot of the speaker. Find it and mute it. 99% of the time it's the speaker device's own mic. |
| Bot doesn't react to typed messages | Message Content Intent is off (Part 1.2), or you're typing in the wrong channel. |
| `PrivilegedIntentsRequired` on startup | Same — the three intent toggles. |
| Screens won't load on the TV | Different Wi-Fi network, or the laptop's firewall is blocking port 8080. Mac: System Settings → Network → Firewall → allow Python. Windows: allow it when prompted. |
| Screen loads but the dot is red | Laptop lost Wi-Fi or the bot stopped. Relaunch — nothing is lost. |
| Bot posts but never speaks | FFmpeg missing. `ffmpeg -version` to check. |
| Speaker connected but silent | Device is deafened, output volume is zero, or it's muted in Discord's user list. |
| Wrong item matched | Add the right spelling to that item's `aliases` in `config.json`, restart. |
| Voice messages play but the board doesn't move | faster-whisper isn't installed. See Part 3. The startup window says which mode you're in. |
| Voice message transcribed wrong | Switch `voice_input.model` to `small.en`. Ask people to hold the phone closer and step away from the fryer. |
| Voice message did nothing at all | Clip was over 45 seconds, or it was sent outside `#kitchen-requests`. |
| Too many spoken alerts | Remove `"low"` from `speak_levels` in `config.json` — then only NEED and OUT interrupt. |
| Slash commands missing | Wait a minute, then fully quit and reopen Discord. |
| "No .env file found" | It's saved as `.env.txt`. Windows hides extensions — turn them on in File Explorer → View. |

---

## Part 8 — Laptop hardening

1. **Disable sleep completely.** Mac: System Settings → Lock Screen → everything **Never**. Windows: Settings → System → Power → **Never**.
2. **Plug into power, and ethernet if the venue has it.** Venue Wi-Fi with several hundred people on it behaves nothing like home Wi-Fi.
3. **Turn off automatic updates for the weekend.**
4. **Leave the lid open** — closing it drops Wi-Fi on most laptops even with sleep off.
5. **Teach one backup person the recovery move:** close the black window, double-click the launcher again. Every status is written to disk on every change, so a restart loses nothing and the screens repopulate in about two seconds.

---

## File reference

| File | Purpose |
|---|---|
| `config.json` | **Your items, aliases, phrases, prep times, screen flags.** The one file you edit. |
| `bot.py` | The bot. You shouldn't need to open it. |
| `web/kitchen.html` | Big-text kitchen screen. Edit the CSS if you want different sizes or colors. |
| `web/command.html` | Command center screen. |
| `.env` | Your secret token. Never share. |
| `run-mac.command` / `run-windows.bat` | Double-click to start. Auto-restarts, keeps the laptop awake. |
| `state.json` | Current status of everything. Auto-saved on every change. |
| `request_log.csv` | The memory bank. Every message, all three days. |
