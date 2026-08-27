# #start-here — copy/paste text

Post these as **separate messages** in `#start-here`, in order. Discord caps a message
at 2000 characters, so they're split to fit. Pin message 1 and message 2.

Everything below is written in Discord markdown — paste it exactly as-is and it will
format itself. Replace `@Kitchen` style mentions only if your role names differ.

---

## ▸ MESSAGE 1 — Welcome

```
# 👋 Welcome to SMSM Festival Ops

This server replaces shouting across the kitchen.

**There is one thing you need to know:**

## 📣 Type what you'd say in ⁠#kitchen-requests

That's it. No commands. No buttons. No training.

> *"we're out of falafel"*
> *"two trays of koshary left"*
> *"need more tawook asap"*

The kitchen **hears it out loud** on their speaker within a second, and it shows up in big letters on the kitchen screen.

**Don't want to type?** Hold the 🎙️ microphone button in the message box, say it, let go. Your voice plays in the kitchen and the board still updates.

-# Nobody uses a live microphone in this server. That's what caused the echo last year.
```

---

## ▸ MESSAGE 2 — How to say things

```
# 🗣️ How to say things

Just talk normally. It understands all of these:

**Running out**
`we're out of falafel` · `no more baklava` · `falafel is gone`

**Getting low**
`two trays of koshary left` · `hummus is running low` · `half a pan of shiro left`

**Need it now**
`need more tawook asap` · `bring 4 bags of ice` · `down to one tray of kofta`

**All clear**
`we're good on fries` · `never mind on the hummus`

## ✅ Say several at once
> *"we need 2 bechamel, 2 foul sandwich and 3 koshary trays"*

All three get posted separately — and the kitchen hears **one** clear announcement instead of three.

## 🔤 Spelling doesn't matter
koshary · koshari · kushari · bashamel · bechamel · shwarma · shawarma · foul · ful · tameya · falafel — all work.

-# If it isn't sure how urgent something is, it updates the board quietly instead of interrupting the cooks. Say **low**, **need now**, or **out** to be certain.
```

---

## ▸ MESSAGE 3 — For the kitchen

```
# 👨‍🍳 If you're in the kitchen

When a request comes in, you'll see buttons. **Tap one.** That's how everyone knows you heard it — no shouting back.

🔵 **On it — prepping**
Claims it and tells everyone roughly when it'll be ready.

✅ **Ready now**
Marks it done. Front of house hears "ready for pickup."

⏱️ **Set time**
Taking longer than usual? Put in your own minutes.

🔵 **On it — all of them**
Appears when someone asks for several things at once.

🔁 **Say it again**
Didn't catch it over the fryer? Replays the announcement.

## ⏰ It will chase you
If nobody taps a button within **7 minutes**, it announces it again and pings @Kitchen. If prep runs past its ready time, it says so. Nothing gets forgotten.
```

---

## ▸ MESSAGE 4 — The channels

```
# 📁 What each channel is for

⁠**#kitchen-requests** ← **you live here**
Type or speak anything the kitchen needs to know.

⁠**#prep-board**
Live status of everything. Updates itself. Just look, don't post.

⁠**#kitchen-comms**
Kitchen-only pings for urgent items.

⁠**#supply-runs**
Need napkins, ice, propane, trays? Post it, a runner claims it.

⁠**#incidents**
Something wrong — spill, injury, equipment, angry guest. Leads get pinged immediately.

⁠**#shift-check-in**
Clock in and out (see below).

⁠**#announcements**
Festival-wide notices from the leads.

## 🖥️ The screens
Big screens in the kitchen and at command center show all of this live. You don't need to do anything for them.
```

---

## ▸ MESSAGE 5 — Shifts and extras

```
# 🕐 Starting and ending your shift

When you arrive, type: `/checkin`
When you leave, type: `/checkout`

That's how we track volunteer hours for thank-you letters. Takes two seconds.

# 🛠️ Handy commands (optional)

`/status` — what's low or out right now
`/history koshary` — everything said about one item today
`/say` — speak a message in the kitchen without changing any status
`/supply` — request napkins, ice, propane, trays
`/incident` — flag a problem to the leads
`/help_festival` — this guide, any time

# 🙋 Confused? Just type it in plain English
Seriously. If you're not sure, write what you'd say out loud and it'll figure it out. Worst case a lead sees it and helps.

**Thank you for volunteering. Let's have a great weekend.** 🇪🇬
```

---

## ▸ OPTIONAL — Leads-only message for #ops-command

```
# 🔐 Lead controls

`/preptime koushary 35` — change how long an item takes. Sticks permanently.
`/preptimes` — see every prep time, overrides marked
`/mute 10` — silence the kitchen speaker 10 min (speeches, prayer). Screens stay live.
`/mute 0` — bring the speaker back early
`/undo` — revert the last status change
`/set` — set any item's status directly
`/allclear` — reset everything to Good. **Run each morning before doors.**
`/export` — download today's full log + which items ran short most
`/screens` — the kitchen + command center screen addresses
`/audio` — diagnose why the speaker isn't talking
`/board` — re-post the prep board
`/tts_join` `/tts_leave` — reconnect the bot to the speaker channel

## ⚠️ Two rules for whoever runs the laptop
1. **Never close the black Terminal window.** That's the whole system.
2. **Stop the bot before moving or renaming its folder.**

If anything breaks: close the window, double-click `FIX-AND-START.command` again. Nothing is ever lost — every change is saved instantly.
```
