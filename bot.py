#!/usr/bin/env python3
"""
SMSM Festival — Kitchen Comms Bot
=================================
Somebody types (or phone-dictates) "two trays of koshary left" in #kitchen-requests.
The bot:
  1. figures out which item and how urgent,
  2. says it out loud in the kitchen in one clean voice,
  3. flips that item's status on the big kitchen screen,
  4. posts a card the kitchen taps to acknowledge,
  5. remembers all of it, forever, searchable.

Nobody holds an open microphone. That's what kills the echo.

Run:  python bot.py     (or double-click run-mac.command / run-windows.bat)
Docs: BUILD-GUIDE.md
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
import shutil
import socket
import tempfile
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

load_dotenv(BASE_DIR / ".env")

# These can be pointed elsewhere with env vars, which is what makes the bot
# deployable in a container: mount a volume, set SMSM_STATE_DIR to it, and the
# live state and logs survive redeploys.
CONFIG_PATH = Path(os.getenv("SMSM_CONFIG", str(BASE_DIR / "config.json")))
STATE_DIR = Path(os.getenv("SMSM_STATE_DIR", str(BASE_DIR)))
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH = STATE_DIR / "state.json"
LOG_PATH = STATE_DIR / "request_log.csv"

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

with CONFIG_PATH.open(encoding="utf-8") as fh:
    CFG: dict[str, Any] = json.load(fh)

FEST = CFG["festival_name"]
ITEMS: list[dict[str, Any]] = CFG["items"]
ITEM_BY_ID = {i["id"]: i for i in ITEMS}
ROLES, CHANS, VOICE = CFG["roles"], CFG["channels"], CFG["voice"]
DASH, BEH, PHRASES = CFG["dashboard"], CFG["behavior"], CFG["phrases"]
VIN = CFG.get("voice_input", {})
DEFAULT_LEVEL = CFG.get("default_level", "low")

LEVELS = {
    "good":     {"label": "GOOD",        "emoji": "🟢", "color": 0x2ECC71, "rank": 0},
    "prepping": {"label": "PREPPING",    "emoji": "🔵", "color": 0x3498DB, "rank": 1},
    "ready":    {"label": "READY",       "emoji": "✅", "color": 0x1ABC9C, "rank": 1},
    "low":      {"label": "GETTING LOW", "emoji": "🟡", "color": 0xF1C40F, "rank": 2},
    "need":     {"label": "NEED NOW",    "emoji": "🔴", "color": 0xE74C3C, "rank": 3},
    "out":      {"label": "OUT",         "emoji": "⚫", "color": 0x992D22, "rank": 4},
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp() -> str:
    return now().strftime("%Y-%m-%d %H:%M:%S UTC")


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# --------------------------------------------------------------------------
# State — written to disk after every change, so a restart loses nothing
# --------------------------------------------------------------------------

def blank_item() -> dict[str, Any]:
    return {"level": "good", "detail": "", "by": "", "at": None,
            "ack_by": "", "ack_at": None, "eta": None}


def load_state() -> dict[str, Any]:
    base = {"items": {}, "feed": [], "board_channel": None, "board_message": None,
            "shifts": {}, "incidents": [], "opened_at": now().isoformat()}
    if STATE_PATH.exists():
        try:
            with STATE_PATH.open(encoding="utf-8") as fh:
                loaded = json.load(fh)
            base.update(loaded)
        except Exception:
            shutil.copy(STATE_PATH, STATE_PATH.with_suffix(".corrupt.json"))
            print("[warn] state.json unreadable — started fresh, old copy saved.")
    for it in ITEMS:
        base["items"].setdefault(it["id"], blank_item())
    return base


STATE = load_state()
_lock = asyncio.Lock()


def save_state() -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(STATE, fh, indent=2)
    tmp.replace(STATE_PATH)


save_state()


def log_row(kind: str, actor: str, item: str, level: str, text: str) -> None:
    new = not LOG_PATH.exists()
    with LOG_PATH.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["timestamp_utc", "type", "who", "item", "level", "message"])
        w.writerow([stamp(), kind, actor, item, level, text])


# --------------------------------------------------------------------------
# Plain-English parsing
# --------------------------------------------------------------------------

_NUM_WORDS = {"half a": 0, "half": 0, "a": 1, "an": 1, "one": 1, "two": 2,
              "three": 3, "four": 4, "five": 5, "six": 6}

# Longest phrases first so "almost out" beats "out" and "no more" beats "more".
_PHRASE_INDEX: list[tuple[re.Pattern, str]] = [
    (re.compile(rf"(?<!\w){re.escape(p.lower())}(?!\w)"), lvl)
    for p, lvl in sorted(
        ((p, lvl) for lvl, plist in PHRASES.items() for p in plist),
        key=lambda t: -len(t[0]),
    )
]

_ALIAS_INDEX: list[tuple[re.Pattern, str]] = [
    (re.compile(rf"(?<!\w){re.escape(a)}(?!\w)"), iid)
    for a, iid in sorted(
        (
            (alias.lower(), it["id"])
            for it in ITEMS
            for alias in ([it["name"].lower()] + [x.lower() for x in it.get("aliases", [])])
        ),
        key=lambda t: -len(t[0]),
    )
]

_UNITS = (r"trays?|pans?|batch(?:es)?|bins?|cases?|boxes?|bags?|racks?|sheets?|"
          r"containers?|orders?|plates?|pieces?|pcs?|sandwich(?:es)?|skewers?|"
          r"boats?|portions?|servings?|lbs?|pounds?")
_NUM = r"half a|half|a couple of|a couple|a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d+"

_QTY_UNIT_RE = re.compile(rf"(?<!\w)({_NUM})\s+(?:\w+\s+){{0,2}}?({_UNITS})(?!\w)")
_QTY_BARE_RE = re.compile(rf"(?<!\w)({_NUM})(?!\w)")

# Words that mean the number is what's LEFT, not what's being asked for.
# "two trays left" = 2 remaining.   "need two trays" = 2 requested.
_REMAINING_RE = re.compile(
    r"(?<!\w)(left|remaining|remain|still have|still got|down to|only|"
    r"got about|we have|there's|theres|have about)(?!\w)")

# Where one request ends and the next begins.
_CLAUSE_SPLIT = re.compile(
    r"\s*(?:[,;/]|&|\n|\band\b|\balso\b|\bplus\b|\bbut\b|\bthen\b)\s*")

MAX_ITEMS_PER_MESSAGE = 8


def _norm(text: str) -> str:
    # Keep , ; / & — they're how people separate one request from the next.
    t = " " + re.sub(r"[^\w\s',;/&-]", " ", text.lower()) + " "
    return re.sub(r"\s+", " ", t)


_UNIT_WORD_RE = re.compile(rf"^(?:{_UNITS})$")


def _is_unit_usage(t: str, start: int, matched: str) -> bool:
    """
    True when an alias is really a unit of measure, not the item itself.
    "2 trays of foul left" — 'trays' is how we're counting the ful, not a
    request for serving trays.
    """
    if not _UNIT_WORD_RE.match(matched.strip()):
        return False
    before = t[:start].strip().split()
    return bool(before) and (before[-1].isdigit() or before[-1] in _NUM_WORDS)


def _find_item(t: str) -> Optional[str]:
    cands: list[tuple[str, int, str]] = []
    for pat, iid in _ALIAS_INDEX:
        mm = pat.search(t)
        if mm:
            cands.append((iid, mm.start(), mm.group(0)))
    if not cands:
        return None
    real = [c for c in cands if not _is_unit_usage(t, c[1], c[2])]
    pool = real or cands            # if ALL we have is "4 trays", they do want trays
    pool.sort(key=lambda c: -len(c[2]))
    return pool[0][0]


def _find_level(t: str) -> tuple[Optional[str], bool]:
    for pat, lvl in _PHRASE_INDEX:
        if pat.search(t):
            return lvl, True
    return None, False


def _to_int(word: str) -> int:
    n = _NUM_WORDS.get(word)
    if n is not None:
        return n
    try:
        return int(word)
    except ValueError:
        return 99


def _find_qty(t: str) -> tuple[str, int, str]:
    """Return (raw_number, value, unit). Unit may be blank."""
    m = _QTY_UNIT_RE.search(t)
    if m:
        return m.group(1), _to_int(m.group(1)), m.group(2)
    m = _QTY_BARE_RE.search(t)
    if m:
        # A bare "a"/"an" is an article, not a count. "a tray" was caught above.
        if m.group(1) in ("a", "an"):
            return "", 0, ""
        return m.group(1), _to_int(m.group(1)), ""
    return "", 0, ""


def parse_all(text: str) -> list[dict]:
    """
    Pull every item out of one message.

      "we need 2 bechamel, 2 foul sandwich and 3 koshary trays"
        -> Mac Bechamel  need  "need 2"
           Ful Medames   need  "need 2"
           Koushary      need  "need 3 trays"

    Each result carries `explicit` — False means nobody said how urgent it is,
    so it updates the board quietly instead of interrupting the kitchen.
    """
    whole = _norm(text)
    global_level, global_explicit = _find_level(whole)

    clauses = [c for c in _CLAUSE_SPLIT.split(whole) if c.strip()]
    if not clauses:
        clauses = [whole]

    found: dict[str, dict] = {}
    for clause in clauses:
        c = f" {clause.strip()} "
        iid = _find_item(c)
        if iid is None:
            continue

        level, explicit = _find_level(c)
        if level is None:
            level, explicit = global_level, global_explicit

        raw, n, unit = _find_qty(c)
        # Does the message talk about what's LEFT? That decides whether the
        # number means remaining or wanted. "2 trays of foul left and 1 tray of
        # hawawshi" — the 'left' governs both halves.
        remaining_ctx = bool(_REMAINING_RE.search(c)) or bool(_REMAINING_RE.search(whole))

        detail = ""
        if raw:
            unit_txt = f" {unit}" if unit else ""
            if remaining_ctx:
                detail = f"{raw}{unit_txt} left"
                # A small remaining count is urgent on its own.
                if level in (None, "low"):
                    if n <= 1:
                        level, explicit = "need", True
                    elif n <= 3:
                        level, explicit = "low", True
            elif level in ("need", "out"):
                detail = f"need {raw}{unit_txt}"
            else:
                detail = f"{raw}{unit_txt}"

        if level is None:
            level = DEFAULT_LEVEL

        prev = found.get(iid)
        if prev is None or LEVELS[level]["rank"] > LEVELS[prev["level"]]["rank"]:
            found[iid] = {"item": iid, "level": level, "detail": detail,
                          "explicit": explicit}

    return list(found.values())[:MAX_ITEMS_PER_MESSAGE]


def parse_message(text: str) -> tuple[Optional[str], Optional[str], str, bool]:
    """Single-item view of parse_all — kept for the simple call sites."""
    r = parse_all(text)
    if not r:
        return None, None, "", False
    top = max(r, key=lambda x: LEVELS[x["level"]]["rank"])
    return top["item"], top["level"], top["detail"], top["explicit"]


# --------------------------------------------------------------------------
# Bot
# --------------------------------------------------------------------------

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)


def chan(guild: discord.Guild, key: str) -> Optional[discord.TextChannel]:
    return discord.utils.get(guild.text_channels, name=CHANS.get(key, ""))


def role_obj(guild: discord.Guild, key: str) -> Optional[discord.Role]:
    return discord.utils.get(guild.roles, name=ROLES.get(key, ""))


def is_admin(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return bool({r.name for r in member.roles} & set(BEH["admin_requires_role"]))


# --------------------------------------------------------------------------
# Voice — one direction only. The bot is the only thing that ever transmits.
# --------------------------------------------------------------------------

class TTSEngine:
    """
    One audio queue for the whole festival. Everything the kitchen hears goes
    through here — synthesized speech and recorded voice messages alike — so
    two announcements can never overlap and nothing ever gets talked over.
    """

    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict] = asyncio.Queue()
        self.worker: Optional[asyncio.Task] = None
        self.available = True
        self.reason = ""
        try:
            from gtts import gTTS  # noqa: F401
        except ImportError:
            self.available, self.reason = False, "gTTS not installed"
        if shutil.which("ffmpeg") is None:
            self.available, self.reason = False, "ffmpeg not found on PATH"
        if not self.available:
            print(f"[warn] Voice disabled — {self.reason}. Text still works.")

    def start(self) -> None:
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self._run())

    @staticmethod
    def muted() -> bool:
        """Quiet period — used during speeches, prayers, announcements."""
        until = STATE.get("mute_until")
        if not until:
            return False
        if now() >= datetime.fromisoformat(until):
            STATE["mute_until"] = None
            return False
        return True

    async def speak(self, guild_id: int, text: str, target: str = "kitchen",
                    repeat: int = 1) -> None:
        if self.available and text.strip() and not self.muted():
            await self.queue.put({"kind": "tts", "guild": guild_id,
                                  "text": text.strip(), "target": target,
                                  "repeat": max(1, repeat)})

    async def play_file(self, guild_id: int, path: str, target: str = "kitchen",
                        repeat: int = 1, cleanup: bool = True) -> None:
        """Play an existing audio file — a recorded voice message, a chime, anything."""
        if shutil.which("ffmpeg") is None or self.muted():
            return
        await self.queue.put({"kind": "file", "guild": guild_id, "path": path,
                              "target": target, "repeat": max(1, repeat),
                              "cleanup": cleanup})

    def _targets(self, target: str) -> list[str]:
        if target == "kitchen":
            return [VOICE["kitchen_vc"]]
        if target == "foh":
            return [VOICE["foh_vc"]]
        return [VOICE["kitchen_vc"], VOICE["foh_vc"]]

    async def _ensure_connected(self, guild: discord.Guild,
                                channel: discord.VoiceChannel):
        """
        Get a *live* voice client for this channel. After a restart or a Wi-Fi
        blip, guild.voice_client can exist but be dead — playing into it fails
        silently, which is exactly the "nothing came out of the speaker" bug.
        """
        for attempt in (1, 2, 3):
            vc = guild.voice_client
            try:
                if vc is not None and not vc.is_connected():
                    await vc.disconnect(force=True)
                    vc = None
                    await asyncio.sleep(1)
                if vc is None:
                    vc = await channel.connect(reconnect=True, timeout=20)
                elif vc.channel.id != channel.id:
                    await vc.move_to(channel)
                    await asyncio.sleep(0.5)
                if vc.is_connected():
                    return vc
            except discord.ClientException:
                # "Already connected" — grab the existing client and use it.
                vc = guild.voice_client
                if vc is not None and vc.is_connected():
                    return vc
            except Exception as exc:
                print(f"[tts] connect attempt {attempt} to '{channel.name}' failed: {exc}")
            await asyncio.sleep(1.5)

        print(f"[tts] GIVING UP connecting to '{channel.name}'. "
              f"Run /audio in Discord to see why.")
        return None

    async def _run(self) -> None:
        from gtts import gTTS
        while True:
            job = await self.queue.get()
            guild_id, target, repeat = job["guild"], job["target"], job["repeat"]
            path, cleanup = None, True
            try:
                guild = bot.get_guild(guild_id)
                if guild is None:
                    continue
                if job["kind"] == "file":
                    path, cleanup = job["path"], job.get("cleanup", True)
                    if not os.path.exists(path):
                        continue
                else:
                    text = job["text"]
                    fd, path = tempfile.mkstemp(suffix=".mp3")
                    os.close(fd)
                    await asyncio.to_thread(
                        lambda: gTTS(text=text, lang=VOICE.get("language", "en"),
                                     slow=VOICE.get("slow", False)).save(path)
                    )
                for vc_name in self._targets(target):
                    channel = discord.utils.get(guild.voice_channels, name=vc_name)
                    if channel is None:
                        print(f"[tts] no voice channel named '{vc_name}'")
                        continue
                    vc = await self._ensure_connected(guild, channel)
                    if vc is None:
                        continue
                    for _ in range(repeat):
                        while vc.is_playing():
                            await asyncio.sleep(0.15)
                        done = asyncio.Event()

                        def _after(err, ev=done):
                            if err:
                                print(f"[tts] playback: {err}")
                            bot.loop.call_soon_threadsafe(ev.set)

                        vc.play(discord.PCMVolumeTransformer(
                            discord.FFmpegPCMAudio(path, options="-loglevel quiet"),
                            volume=1.0), after=_after)
                        try:
                            await asyncio.wait_for(done.wait(), timeout=90)
                        except asyncio.TimeoutError:
                            vc.stop()
                        await asyncio.sleep(0.4)
            except Exception:
                traceback.print_exc()
            finally:
                if cleanup and path and os.path.exists(path):
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
                self.queue.task_done()


tts = TTSEngine()


# --------------------------------------------------------------------------
# Speech to text — optional. Lets a spoken message also move the prep board.
# --------------------------------------------------------------------------

class Transcriber:
    """
    Wraps faster-whisper if it's installed. Runs entirely on the laptop — no
    account, no API key, no audio leaving the building. If it isn't installed,
    voice messages still play in the kitchen; they just don't update the board.
    """

    def __init__(self) -> None:
        self.model = None
        self.available = False
        self.reason = "not enabled in config.json"
        if not VIN.get("transcribe", True):
            return
        try:
            from faster_whisper import WhisperModel  # noqa: F401
            self.available = True
            self.reason = ""
        except ImportError:
            self.reason = ("faster-whisper not installed — run  "
                           "./.venv/bin/pip install faster-whisper")

    async def load(self) -> None:
        if not self.available or self.model is not None:
            return
        from faster_whisper import WhisperModel
        size = VIN.get("model", "base.en")
        print(f"[..] Loading speech model '{size}' (first run downloads ~150 MB)…")
        try:
            self.model = await asyncio.to_thread(
                WhisperModel, size, device="cpu", compute_type="int8")
            print("[ok] Speech-to-text ready — spoken messages will update the board.")
        except Exception as exc:
            self.available = False
            self.reason = f"model failed to load: {exc}"
            print(f"[warn] {self.reason}")

    async def transcribe(self, path: str) -> str:
        if not self.available or self.model is None:
            return ""

        def _run() -> str:
            segments, _ = self.model.transcribe(
                path, language=VIN.get("language", "en"),
                vad_filter=True, beam_size=1)
            return " ".join(s.text.strip() for s in segments).strip()

        try:
            return await asyncio.to_thread(_run)
        except Exception:
            traceback.print_exc()
            return ""


stt = Transcriber()


def is_voice_note(msg: discord.Message) -> Optional[discord.Attachment]:
    """A Discord voice message, or any audio file someone dropped in."""
    for a in msg.attachments:
        ct = (a.content_type or "").lower()
        if ct.startswith("audio/") or a.filename.lower().endswith(
                (".ogg", ".m4a", ".mp3", ".wav", ".webm", ".opus")):
            return a
    return None


# --------------------------------------------------------------------------
# Status changes
# --------------------------------------------------------------------------

def prep_minutes(item_id: str) -> int:
    """Prep time, honouring any live override set with /preptime."""
    ov = STATE.get("prep_overrides", {}).get(item_id)
    if ov:
        return int(ov)
    return int(ITEM_BY_ID[item_id].get("prep_min", 20))


def _join_names(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def compose_announcement(results: list[dict]) -> str:
    """
    Turn a batch into one sentence a cook can actually follow.
      -> "Kitchen. Need Mac Bechamel, Ful Medames, and Koushary. Koushary, 3 trays."
    """
    prefix = VOICE.get("attention_prefix", "").strip()
    cap = int(BEH.get("max_spoken_items", 5))
    parts: list[str] = []

    for lvl, verb in (("out", "We are out of"), ("need", "Need"), ("low", "Getting low on")):
        group = [r for r in results if r["level"] == lvl][:cap]
        if not group:
            continue
        names = [ITEM_BY_ID[r["item"]]["name"].title() for r in group]
        parts.append(f"{verb} {_join_names(names)}.")

    # Read out concrete amounts once, after the headline.
    amounts = [f"{ITEM_BY_ID[r['item']]['name'].title()}, {r['detail']}"
               for r in results if r.get("detail")][:cap]
    if amounts:
        parts.append(" ".join(a + "." for a in amounts))

    extra = len(results) - cap
    if extra > 0:
        parts.append(f"And {extra} more on the screen.")

    return " ".join([prefix] + parts).strip()


def ago(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    mins = int((now() - datetime.fromisoformat(iso)).total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins}m ago"
    return f"{mins // 60}h {mins % 60}m ago"


async def set_level(guild: Optional[discord.Guild], item_id: str, level: str,
                    who: str, detail: str = "", text: str = "",
                    speak: bool = True, eta_minutes: int = 0) -> dict[str, Any]:
    item = ITEM_BY_ID[item_id]
    async with _lock:
        rec = STATE["items"].setdefault(item_id, blank_item())
        prev = rec.get("level", "good")
        rec.update({"level": level, "detail": detail, "by": who,
                    "at": now().isoformat()})
        if level in ("need", "out", "low"):
            rec["ack_by"], rec["ack_at"], rec["eta"] = "", None, None
            rec["nags"] = 0
            rec["overdue_called"] = False
        if level == "prepping":
            rec["eta"] = (now() + timedelta(minutes=eta_minutes or
                                            prep_minutes(item_id))).isoformat()
            rec["overdue_called"] = False
        STATE["feed"].insert(0, {"at": now().isoformat(), "who": who, "item": item_id,
                                 "name": item["name"], "level": level,
                                 "detail": detail, "text": text, "prev": prev})
        del STATE["feed"][300:]
        save_state()
    log_row("status", who, item["name"], level, text)

    if speak and guild and level in VOICE.get("speak_levels", []):
        prefix = VOICE.get("attention_prefix", "")
        if level == "out":
            line = f"{prefix} {item['name']} is out. We are out of {item['name']}."
        elif level == "need":
            line = f"{prefix} Need {item['name']} now."
            if detail:
                line += f" {detail} left."
        else:
            line = f"{prefix} {item['name']} is getting low."
            if detail:
                line += f" {detail} left."
        repeat = VOICE.get("repeat_urgent", 1) if level in ("need", "out") else 1
        await tts.speak(guild.id, line, target="kitchen", repeat=repeat)
    return STATE["items"][item_id]


# --------------------------------------------------------------------------
# Acknowledgment card — this is what removes the relay person
# --------------------------------------------------------------------------

class AckView(discord.ui.View):
    def __init__(self, item_id: str = "") -> None:
        super().__init__(timeout=None)
        self.item_id = item_id

    def _iid(self, interaction: discord.Interaction) -> Optional[str]:
        if self.item_id:
            return self.item_id
        emb = interaction.message.embeds[0] if interaction.message.embeds else None
        if emb and emb.footer and emb.footer.text:
            tag = emb.footer.text.split("id:")[-1].strip()
            if tag in ITEM_BY_ID:
                return tag
        return None

    @discord.ui.button(label="On it — prepping", style=discord.ButtonStyle.primary,
                       emoji="🔵", custom_id="ack_prepping")
    async def prepping(self, interaction: discord.Interaction, _b: discord.ui.Button):
        iid = self._iid(interaction)
        if not iid:
            await interaction.response.send_message("Couldn't match that item.", ephemeral=True)
            return
        await claim_prepping(interaction, iid)

    @discord.ui.button(label="Ready now", style=discord.ButtonStyle.success,
                       emoji="✅", custom_id="ack_ready")
    async def ready(self, interaction: discord.Interaction, _b: discord.ui.Button):
        iid = self._iid(interaction)
        if not iid:
            await interaction.response.send_message("Couldn't match that item.", ephemeral=True)
            return
        await mark_ready(interaction, iid)

    @discord.ui.button(label="Set time", style=discord.ButtonStyle.secondary,
                       emoji="⏱️", custom_id="ack_settime")
    async def settime(self, interaction: discord.Interaction, _b: discord.ui.Button):
        iid = self._iid(interaction)
        if not iid:
            await interaction.response.send_message("Couldn't match that item.", ephemeral=True)
            return
        await interaction.response.send_modal(EtaModal(iid))

    @discord.ui.button(label="Say it again", style=discord.ButtonStyle.secondary,
                       emoji="🔁", custom_id="ack_repeat")
    async def repeat(self, interaction: discord.Interaction, _b: discord.ui.Button):
        emb = interaction.message.embeds[0] if interaction.message.embeds else None
        line = (emb.description if emb else "") or "No message to repeat."
        line = re.sub(r"🎙️ \*heard:\*\s*", "", line).strip("“”\" ")
        await interaction.response.send_message("🔁 Repeating in the kitchen.", ephemeral=True)
        await tts.speak(interaction.guild.id,
                        f"{VOICE.get('attention_prefix', '')} {line}", target="kitchen")


async def claim_prepping(interaction: discord.Interaction, iid: str,
                         minutes: int = 0) -> None:
    item = ITEM_BY_ID[iid]
    mins = minutes or prep_minutes(iid)
    rec = await set_level(interaction.guild, iid, "prepping",
                          interaction.user.display_name, speak=False,
                          eta_minutes=mins)
    eta = datetime.fromisoformat(rec["eta"]).astimezone().strftime("%-I:%M %p")
    msg = (f"🔵 **{item['name']}** — {interaction.user.display_name} is on it. "
           f"Ready around **{eta}** (~{mins} min).")
    if interaction.response.is_done():
        await interaction.followup.send(msg)
    else:
        await interaction.response.send_message(msg)
    await refresh_board(interaction.guild)


async def mark_ready(interaction: discord.Interaction, iid: str) -> None:
    item = ITEM_BY_ID[iid]
    await set_level(interaction.guild, iid, "good",
                    interaction.user.display_name, speak=False)
    msg = f"✅ **{item['name']}** is ready — come get it."
    if interaction.response.is_done():
        await interaction.followup.send(msg)
    else:
        await interaction.response.send_message(msg)
    await tts.speak(interaction.guild.id,
                    f"{item['name']} is ready for pickup.", target="foh")
    await refresh_board(interaction.guild)


class EtaModal(discord.ui.Modal, title="How long until it's ready?"):
    def __init__(self, item_id: str) -> None:
        super().__init__()
        self.item_id = item_id
        self.minutes = discord.ui.TextInput(
            label=f"Minutes for {ITEM_BY_ID[item_id]['name']}",
            default=str(prep_minutes(item_id)), max_length=4, required=True)
        self.remember = discord.ui.TextInput(
            label="Make this the new default? yes / no",
            default="no", max_length=4, required=False)
        self.add_item(self.minutes)
        self.add_item(self.remember)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            mins = max(1, min(600, int(str(self.minutes).strip())))
        except ValueError:
            await interaction.response.send_message(
                "That wasn't a number of minutes.", ephemeral=True)
            return
        if str(self.remember).strip().lower() in ("y", "yes", "1", "true"):
            STATE.setdefault("prep_overrides", {})[self.item_id] = mins
            save_state()
        await claim_prepping(interaction, self.item_id, minutes=mins)


class BatchAckView(discord.ui.View):
    """One tap to claim every item from a multi-item request."""

    def __init__(self, item_ids: list[str]) -> None:
        super().__init__(timeout=None)
        self.item_ids = item_ids

    @discord.ui.button(label="On it — all of them", style=discord.ButtonStyle.primary,
                       emoji="🔵")
    async def all_prepping(self, interaction: discord.Interaction, _b: discord.ui.Button):
        await interaction.response.defer()
        lines = []
        for iid in self.item_ids:
            mins = prep_minutes(iid)
            rec = await set_level(interaction.guild, iid, "prepping",
                                  interaction.user.display_name, speak=False,
                                  eta_minutes=mins)
            eta = datetime.fromisoformat(rec["eta"]).astimezone().strftime("%-I:%M %p")
            lines.append(f"🔵 **{ITEM_BY_ID[iid]['name']}** — ready ~**{eta}**")
        await interaction.followup.send(
            f"**{interaction.user.display_name}** is on all of it:\n" + "\n".join(lines))
        await refresh_board(interaction.guild)

    @discord.ui.button(label="All ready", style=discord.ButtonStyle.success, emoji="✅")
    async def all_ready(self, interaction: discord.Interaction, _b: discord.ui.Button):
        await interaction.response.defer()
        for iid in self.item_ids:
            await set_level(interaction.guild, iid, "good",
                            interaction.user.display_name, speak=False)
        names = _join_names([ITEM_BY_ID[i]["name"].title() for i in self.item_ids])
        await interaction.followup.send(f"✅ All ready: **{names}**")
        await tts.speak(interaction.guild.id, f"{names} ready for pickup.", target="foh")
        await refresh_board(interaction.guild)

    @discord.ui.button(label="Pick one", style=discord.ButtonStyle.secondary, emoji="🔽")
    async def pick(self, interaction: discord.Interaction, _b: discord.ui.Button):
        v = discord.ui.View(timeout=300)
        v.add_item(ItemPick(self.item_ids))
        await interaction.response.send_message(
            "Which one are you starting?", view=v, ephemeral=True)


class ItemPick(discord.ui.Select):
    def __init__(self, item_ids: list[str]) -> None:
        super().__init__(placeholder="Choose an item…", min_values=1, max_values=1,
                         options=[discord.SelectOption(
                             label=ITEM_BY_ID[i]["name"],
                             description=f"~{prep_minutes(i)} min", value=i)
                             for i in item_ids[:25]])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EtaModal(self.values[0]))


# --------------------------------------------------------------------------
# The Discord prep board (the web dashboards are the main screens)
# --------------------------------------------------------------------------

def board_embed() -> discord.Embed:
    worst = max((LEVELS[STATE["items"][i["id"]]["level"]]["rank"] for i in ITEMS),
                default=0)
    color = {0: 0x2ECC71, 1: 0x3498DB, 2: 0xF1C40F, 3: 0xE74C3C, 4: 0x992D22}[worst]
    e = discord.Embed(title=f"🍳 {FEST} — PREP BOARD", color=color, timestamp=now())

    attention = [i for i in ITEMS
                 if STATE["items"][i["id"]]["level"] in ("need", "out", "low")]
    working = [i for i in ITEMS if STATE["items"][i["id"]]["level"] == "prepping"]

    if attention:
        lines = []
        for i in sorted(attention,
                        key=lambda x: -LEVELS[STATE["items"][x["id"]]["level"]]["rank"]):
            r = STATE["items"][i["id"]]
            lv = LEVELS[r["level"]]
            extra = f" · {r['detail']}" if r["detail"] else ""
            waited = ""
            if r["level"] in ("need", "out") and not r.get("ack_by") and r.get("at"):
                mins = int((now() - datetime.fromisoformat(r["at"])).total_seconds() // 60)
                if mins >= 5:
                    waited = f"  ⏰ **{mins}m unclaimed**"
            lines.append(f"{lv['emoji']} **{i['name']}** — {lv['label']}{extra} "
                         f"_({ago(r['at'])})_{waited}")
        e.add_field(name="⚠️ NEEDS ATTENTION", value="\n".join(lines[:15]), inline=False)
    else:
        e.add_field(name="✅ ALL CLEAR", value="Nothing is low or out.", inline=False)

    if working:
        grace = int(BEH.get("overdue_grace_minutes", 3))
        lines = []
        for i in working:
            r = STATE["items"][i["id"]]
            if not r.get("eta"):
                lines.append(f"🔵 **{i['name']}** — {r['by']}")
                continue
            left = int((datetime.fromisoformat(r["eta"]) - now()).total_seconds() // 60)
            eta = datetime.fromisoformat(r["eta"]).astimezone().strftime("%-I:%M %p")
            if left <= -grace:
                lines.append(f"⌛ **{i['name']}** — {r['by']} · **{abs(left)}m LATE** "
                             f"(was due {eta})")
            elif left <= 0:
                lines.append(f"🔵 **{i['name']}** — {r['by']} · **ready now**")
            else:
                lines.append(f"🔵 **{i['name']}** — {r['by']} · **{left}m** (~{eta})")
        e.add_field(name="🔵 BEING PREPPED", value="\n".join(lines[:15]), inline=False)

    if tts.muted():
        left = int((datetime.fromisoformat(STATE["mute_until"]) - now()).total_seconds() // 60)
        e.add_field(name="🔇 Speaker muted",
                    value=f"Quiet for another **{left} min**. `/mute 0` to end it early.",
                    inline=False)

    recent = STATE["feed"][:5]
    if recent:
        e.add_field(
            name="🗒️ Last few requests",
            value="\n".join(f"`{ago(f['at'])}` **{f['who']}** — {f.get('text') or f['name']}"[:120]
                            for f in recent),
            inline=False)

    e.set_footer(text="Type in #kitchen-requests — no commands needed. "
                      "Kitchen screen: see /command for the URL")
    return e


async def refresh_board(guild: Optional[discord.Guild]) -> None:
    if guild is None:
        return
    ch = guild.get_channel(STATE.get("board_channel") or 0) or chan(guild, "board")
    if ch is None:
        return
    try:
        if STATE.get("board_message"):
            msg = await ch.fetch_message(STATE["board_message"])
            await msg.edit(embed=board_embed(), view=AckView())
            return
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass
    msg = await ch.send(embed=board_embed(), view=AckView())
    try:
        await msg.pin()
    except discord.HTTPException:
        pass
    STATE["board_channel"], STATE["board_message"] = ch.id, msg.id
    save_state()


# --------------------------------------------------------------------------
# The main event: someone just types in #kitchen-requests
# --------------------------------------------------------------------------

async def handle_voice_note(message: discord.Message,
                            att: discord.Attachment) -> Optional[str]:
    """
    Someone held the mic button and talked. Play it in the kitchen immediately,
    then transcribe it if we can so the prep board moves too.
    Returns the transcript, or None.
    """
    who = message.author.display_name
    suffix = Path(att.filename).suffix or ".ogg"
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        await att.save(Path(path))
    except Exception:
        traceback.print_exc()
        return None

    secs = int(getattr(att, "duration", 0) or 0)
    if secs and secs > VIN.get("max_seconds", 45):
        await message.reply(
            f"⏱️ That clip is {secs}s — too long to hold the kitchen speaker. "
            f"Keep voice notes under {VIN.get('max_seconds', 45)}s.",
            mention_author=False)
        os.unlink(path)
        return None

    # Play the actual recording first — always works, needs nothing installed.
    if VIN.get("play_recording", True):
        await tts.play_file(message.guild.id, path,
                            target=VIN.get("target", "kitchen"), cleanup=False)
        await message.add_reaction("🔊")

    transcript = ""
    if stt.available:
        transcript = await stt.transcribe(path)

    # Free the file once the queue has had a chance to read it.
    async def _cleanup():
        await asyncio.sleep(180)
        if os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass

    asyncio.create_task(_cleanup())

    if not transcript:
        async with _lock:
            STATE["feed"].insert(0, {"at": now().isoformat(), "who": who, "item": "",
                                     "name": "Voice note", "level": "", "detail": "",
                                     "text": f"🎙️ voice message ({secs}s)"})
            del STATE["feed"][300:]
            save_state()
        log_row("voice", who, "", "", f"voice message ({secs}s)")
        if not stt.available and VIN.get("transcribe", True):
            print(f"[info] Voice note played but not transcribed — {stt.reason}")
        return None

    log_row("voice", who, "", "", transcript)
    return transcript


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return
    if message.channel.name != CHANS["requests"]:
        await bot.process_commands(message)
        return

    text = message.content.strip()
    spoken = False

    att = is_voice_note(message)
    if att is not None:
        transcript = await handle_voice_note(message, att)
        if not transcript:
            await refresh_board(message.guild)
            return
        text, spoken = transcript, True

    if not text:
        return

    who = message.author.display_name
    results = parse_all(text)

    # A phone recording through a kitchen speaker is quiet and easy to miss.
    # For a real alert we follow it with the loud synthesized version too,
    # unless you turn that off in config.json.
    played_raw = spoken and VIN.get("play_recording", True)
    already_heard = played_raw and not VIN.get("announce_after_recording", True)

    if not results:
        # A general message with no item — saying it twice is just noise.
        if not played_raw:
            await tts.speak(message.guild.id,
                            f"{VOICE.get('attention_prefix', '')} {text}", target="kitchen")
        async with _lock:
            STATE["feed"].insert(0, {"at": now().isoformat(), "who": who, "item": "",
                                     "name": "General", "level": "", "detail": "",
                                     "text": text})
            del STATE["feed"][300:]
            save_state()
        log_row("message", who, "", "", text)
        if not spoken:
            await message.add_reaction("🔊")
        return

    # Apply every item silently, then make ONE announcement for the whole
    # message. Three separate alerts back to back is how a kitchen learns to
    # tune the speaker out.
    for r in results:
        await set_level(message.guild, r["item"], r["level"], who,
                        r["detail"], text, speak=False)

    spoken_items = [r for r in results if r["explicit"]
                    and r["level"] in VOICE.get("speak_levels", [])]
    if spoken_items and not already_heard:
        line = compose_announcement(spoken_items)
        urgent = any(r["level"] in ("need", "out") for r in spoken_items)
        await tts.speak(message.guild.id, line, target="kitchen",
                        repeat=VOICE.get("repeat_urgent", 1) if urgent else 1)

    worst = max(results, key=lambda r: LEVELS[r["level"]]["rank"])
    unconfirmed = [r for r in results if not r["explicit"]]

    if len(results) == 1:
        r = results[0]
        item, lv = ITEM_BY_ID[r["item"]], LEVELS[r["level"]]
        e = discord.Embed(
            title=f"{lv['emoji']} {item['name']} — {lv['label']}"
                  + ("" if r["explicit"] else "  (unconfirmed)"),
            description=(f"🎙️ *heard:* “{text}”" if spoken else text),
            color=lv["color"], timestamp=now())
        if r["detail"]:
            e.add_field(name="Amount", value=r["detail"], inline=True)
        e.add_field(name="Prep time", value=f"~{prep_minutes(r['item'])} min", inline=True)
        e.add_field(name="Station", value=item.get("station", "—"), inline=True)
        footer_id = r["item"]
    else:
        e = discord.Embed(
            title=f"📋 {len(results)} items updated",
            description=(f"🎙️ *heard:* “{text}”" if spoken else text),
            color=LEVELS[worst["level"]]["color"], timestamp=now())
        e.add_field(
            name="​",
            value="\n".join(
                f"{LEVELS[r['level']]['emoji']} **{ITEM_BY_ID[r['item']]['name']}** — "
                f"{LEVELS[r['level']]['label']}"
                + (f" · {r['detail']}" if r["detail"] else "")
                + (f"  ·  ~{prep_minutes(r['item'])} min" if r["level"] in ("need", "out") else "")
                + ("" if r["explicit"] else "  _(unconfirmed)_")
                for r in results),
            inline=False)
        footer_id = worst["item"]

    if unconfirmed:
        e.add_field(
            name="Not announced aloud",
            value=("I caught " + ", ".join(ITEM_BY_ID[r["item"]]["name"] for r in unconfirmed)
                   + " but not how urgent, so I didn't interrupt the kitchen. "
                     "Say **low**, **need now**, or **out** — or tap a button."),
            inline=False)

    e.set_footer(text=f"{who} · id:{footer_id}")

    show_buttons = any(r["level"] in ("need", "out", "low") for r in results)
    view = AckView(footer_id) if show_buttons else None
    if len(results) > 1 and show_buttons:
        view = BatchAckView([r["item"] for r in results
                             if r["level"] in ("need", "out", "low")])
    await message.reply(embed=e, view=view, mention_author=False)
    await message.add_reaction(LEVELS[worst["level"]]["emoji"])
    await refresh_board(message.guild)

    urgent_items = [r for r in results if r["explicit"] and r["level"] in ("need", "out")]
    if urgent_items:
        kr = role_obj(message.guild, "kitchen")
        kc = chan(message.guild, "kitchen_text")
        if kc and kr:
            body = " · ".join(f"**{ITEM_BY_ID[r['item']]['name']}** {LEVELS[r['level']]['label']}"
                              for r in urgent_items)
            await kc.send(f"{kr.mention} {body}  ({who})")


# --------------------------------------------------------------------------
# Slash commands
# --------------------------------------------------------------------------

async def item_ac(interaction: discord.Interaction, current: str):
    cur = current.lower()
    out = []
    for i in ITEMS:
        hay = i["name"].lower() + " " + " ".join(i.get("aliases", []))
        if cur in hay:
            lv = LEVELS[STATE["items"][i["id"]]["level"]]
            out.append(app_commands.Choice(
                name=f"{lv['emoji']} {i['name']} — {lv['label']}"[:100], value=i["id"]))
    return out[:25]


@bot.tree.command(name="set", description="Set an item's status directly")
@app_commands.describe(item="Which item", status="New status", note="Optional detail")
@app_commands.autocomplete(item=item_ac)
@app_commands.choices(status=[
    app_commands.Choice(name="🟢 Good", value="good"),
    app_commands.Choice(name="🟡 Getting low", value="low"),
    app_commands.Choice(name="🔴 Need now", value="need"),
    app_commands.Choice(name="🔵 Prepping", value="prepping"),
    app_commands.Choice(name="⚫ Out", value="out"),
])
async def set_cmd(interaction: discord.Interaction, item: str,
                  status: app_commands.Choice[str], note: str = ""):
    if item not in ITEM_BY_ID:
        await interaction.response.send_message("Unknown item.", ephemeral=True)
        return
    await set_level(interaction.guild, item, status.value,
                    interaction.user.display_name, note, note)
    await interaction.response.send_message(
        f"{LEVELS[status.value]['emoji']} **{ITEM_BY_ID[item]['name']}** → "
        f"{LEVELS[status.value]['label']}", ephemeral=True)
    await refresh_board(interaction.guild)


@bot.tree.command(name="preptime", description="Change how long an item takes to make")
@app_commands.describe(item="Which item", minutes="New prep time in minutes")
@app_commands.autocomplete(item=item_ac)
async def preptime(interaction: discord.Interaction, item: str, minutes: int):
    if item not in ITEM_BY_ID:
        await interaction.response.send_message("Unknown item.", ephemeral=True)
        return
    minutes = max(1, min(600, minutes))
    was = prep_minutes(item)
    STATE.setdefault("prep_overrides", {})[item] = minutes
    # Keep any in-flight ETA honest.
    rec = STATE["items"].get(item, {})
    if rec.get("level") == "prepping" and rec.get("at"):
        rec["eta"] = (datetime.fromisoformat(rec["at"])
                      + timedelta(minutes=minutes)).isoformat()
        rec["overdue_called"] = False
    save_state()
    log_row("preptime", str(interaction.user), ITEM_BY_ID[item]["name"], "", f"{was} -> {minutes}")
    await interaction.response.send_message(
        f"⏱️ **{ITEM_BY_ID[item]['name']}** prep time: **{was} → {minutes} min**. "
        "Sticks until you change it again.", ephemeral=True)
    await refresh_board(interaction.guild)


@bot.tree.command(name="preptimes", description="See and sanity-check every prep time")
async def preptimes(interaction: discord.Interaction):
    by_station: dict[str, list[str]] = {}
    for i in ITEMS:
        base = int(i.get("prep_min", 20))
        cur = prep_minutes(i["id"])
        mark = f"**{cur}**" + (f" _(was {base})_" if cur != base else "")
        by_station.setdefault(i.get("station", "—"), []).append(f"{i['name']} — {mark} min")
    e = discord.Embed(title="⏱️ Prep times", color=0x5865F2,
                      description="Change any with `/preptime`. Bold values with a "
                                  "_(was …)_ note are your overrides.")
    for st, rows in by_station.items():
        e.add_field(name=st, value="\n".join(rows)[:1024], inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name="mute", description="Silence the kitchen speaker for a few minutes")
@app_commands.describe(minutes="How long to stay quiet (0 to unmute now)")
async def mute(interaction: discord.Interaction, minutes: int = 10):
    if minutes <= 0:
        STATE["mute_until"] = None
        save_state()
        await interaction.response.send_message("🔊 Speaker back on.", ephemeral=False)
        return
    minutes = min(minutes, 180)
    STATE["mute_until"] = (now() + timedelta(minutes=minutes)).isoformat()
    save_state()
    until = (datetime.now() + timedelta(minutes=minutes)).strftime("%-I:%M %p")
    log_row("mute", str(interaction.user), "", "", f"{minutes} min")
    await interaction.response.send_message(
        f"🔇 Kitchen speaker muted until **{until}**. The board and screens keep "
        "updating — only the audio stops. `/mute 0` to bring it back early.")


@bot.tree.command(name="undo", description="Undo the last status change")
async def undo(interaction: discord.Interaction):
    entry = next((f for f in STATE["feed"] if f.get("item") and f.get("prev")), None)
    if not entry:
        await interaction.response.send_message("Nothing to undo.", ephemeral=True)
        return
    iid, prev = entry["item"], entry["prev"]
    await set_level(interaction.guild, iid, prev, interaction.user.display_name,
                    "", f"undo of {entry.get('level')}", speak=False)
    await interaction.response.send_message(
        f"↩️ **{ITEM_BY_ID[iid]['name']}** back to "
        f"{LEVELS[prev]['emoji']} {LEVELS[prev]['label']} "
        f"(was {LEVELS[entry['level']]['label']}).")
    await refresh_board(interaction.guild)


@bot.tree.command(name="status", description="What's low or out right now")
async def status_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(embed=board_embed(), ephemeral=True)


@bot.tree.command(name="history", description="Everything said about one item today")
@app_commands.autocomplete(item=item_ac)
async def history(interaction: discord.Interaction, item: str):
    rows = [f for f in STATE["feed"] if f["item"] == item][:20]
    if not rows:
        await interaction.response.send_message("Nothing logged for that yet.", ephemeral=True)
        return
    e = discord.Embed(title=f"🧠 {ITEM_BY_ID[item]['name']} — today",
                      color=0x95A5A6)
    e.description = "\n".join(
        f"`{ago(f['at'])}` **{f['who']}** — {f.get('text') or LEVELS.get(f['level'], {}).get('label', '')}"[:150]
        for f in rows)
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name="say", description="Speak a message in the kitchen without changing any status")
@app_commands.describe(message="What to say", where="Which speaker")
@app_commands.choices(where=[
    app_commands.Choice(name="Kitchen", value="kitchen"),
    app_commands.Choice(name="Front of House", value="foh"),
    app_commands.Choice(name="Both", value="both"),
])
async def say(interaction: discord.Interaction, message: str,
              where: Optional[app_commands.Choice[str]] = None):
    target = where.value if where else "kitchen"
    await interaction.response.send_message(
        f"🔊 Speaking → {target}" if tts.available
        else f"🔇 Voice unavailable ({tts.reason}) — posted as text.", ephemeral=True)
    await tts.speak(interaction.guild.id,
                    f"{VOICE.get('attention_prefix', '')} {message}", target=target)
    kc = chan(interaction.guild, "kitchen_text")
    if kc:
        await kc.send(f"🔊 **{interaction.user.display_name}**: {message}")
    log_row("say", str(interaction.user), "", "", message)


@bot.tree.command(name="board", description="Post / re-post the prep board here")
async def board_cmd(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Leads only.", ephemeral=True)
        return
    STATE["board_channel"], STATE["board_message"] = interaction.channel_id, None
    save_state()
    await interaction.response.send_message("📌 Posting…", ephemeral=True)
    await refresh_board(interaction.guild)


@bot.tree.command(name="screens", description="Show the kitchen + command center screen URLs")
async def screens(interaction: discord.Interaction):
    ip, port = lan_ip(), DASH["port"]
    e = discord.Embed(title="🖥️ Screen URLs", color=0x5865F2, description=
                      "Open these in any browser on the same Wi-Fi. "
                      "Press **F11** for fullscreen.")
    e.add_field(name="Kitchen screen (big text)",
                value=f"```http://{ip}:{port}/kitchen```", inline=False)
    e.add_field(name="Command center (everything)",
                value=f"```http://{ip}:{port}/```", inline=False)
    e.set_footer(text="If these don't load, the laptop's firewall is blocking the port.")
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name="allclear", description="Reset every item back to Good (start of a day)")
async def allclear(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Leads only.", ephemeral=True)
        return
    async with _lock:
        for i in ITEMS:
            STATE["items"][i["id"]] = blank_item()
        STATE["feed"].insert(0, {"at": now().isoformat(),
                                 "who": interaction.user.display_name, "item": "",
                                 "name": "System", "level": "", "detail": "",
                                 "text": "— day reset, all items back to Good —"})
        save_state()
    log_row("reset", str(interaction.user), "", "", "day reset")
    await interaction.response.send_message("🔄 Everything reset to Good.", ephemeral=True)
    await refresh_board(interaction.guild)


@bot.tree.command(name="export", description="Download today's full request log")
async def export(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await interaction.response.send_message("⛔ Leads only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time_utc", "who", "item", "level", "detail", "message"])
    for f in reversed(STATE["feed"]):
        w.writerow([f["at"], f["who"], f["name"], f["level"], f["detail"], f.get("text", "")])
    buf.seek(0)
    counts: dict[str, int] = {}
    for f in STATE["feed"]:
        if f["item"] and f["level"] in ("need", "out"):
            counts[f["name"]] = counts.get(f["name"], 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:10]
    e = discord.Embed(title="🧠 Memory bank — today", color=0x95A5A6,
                      description="Items that hit *Need now* or *Out* most often. "
                                  "This is your prep list for next year.")
    e.add_field(name="Ran short most", value="\n".join(
        f"{n}. **{k}** — {v}×" for n, (k, v) in enumerate(top, 1)) or "Nothing ran short.",
        inline=False)
    e.add_field(name="Total requests", value=str(len(STATE["feed"])), inline=True)
    files = [discord.File(io.BytesIO(buf.getvalue().encode()), filename="today_requests.csv")]
    if LOG_PATH.exists():
        files.append(discord.File(str(LOG_PATH), filename="full_log_all_days.csv"))
    await interaction.followup.send(embed=e, files=files, ephemeral=True)


@bot.tree.command(name="incident", description="Flag a problem to the leads")
@app_commands.describe(what="What's happening", where="Where")
@app_commands.choices(severity=[
    app_commands.Choice(name="🔴 Critical", value="critical"),
    app_commands.Choice(name="🟠 Urgent", value="urgent"),
    app_commands.Choice(name="🟡 Heads up", value="info"),
])
async def incident(interaction: discord.Interaction,
                   severity: app_commands.Choice[str], what: str, where: str = ""):
    ic = chan(interaction.guild, "incidents") or interaction.channel
    pings = " ".join(r.mention for r in
                     (role_obj(interaction.guild, "admin"),
                      role_obj(interaction.guild, "manager")) if r)
    e = discord.Embed(title=severity.name, description=what,
                      color={"critical": 0xE74C3C, "urgent": 0xE67E22,
                             "info": 0xF1C40F}[severity.value], timestamp=now())
    if where:
        e.add_field(name="Where", value=where)
    e.set_footer(text=f"Reported by {interaction.user.display_name}")
    await ic.send(content=pings if severity.value != "info" else None, embed=e)
    STATE["incidents"].append({"at": now().isoformat(), "sev": severity.value,
                               "what": what, "where": where,
                               "by": interaction.user.display_name})
    save_state()
    log_row("incident", str(interaction.user), "", severity.value, f"{what} @ {where}")
    await interaction.response.send_message(f"🚨 Sent to {ic.mention}.", ephemeral=True)
    if VOICE.get("announce_incidents") and severity.value in ("critical", "urgent"):
        await tts.speak(interaction.guild.id,
                        f"Attention. {what}. {('Location ' + where) if where else ''}",
                        target="both", repeat=2)


@bot.tree.command(name="checkin", description="Clock in for your shift")
async def checkin(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    rec = STATE["shifts"].setdefault(uid, {"in": None, "total_seconds": 0,
                                           "name": interaction.user.display_name})
    if rec.get("in"):
        await interaction.response.send_message("Already clocked in.", ephemeral=True)
        return
    rec["in"] = now().isoformat()
    rec["name"] = interaction.user.display_name
    save_state()
    await interaction.response.send_message("✅ Clocked in. Thank you!", ephemeral=True)
    sc = chan(interaction.guild, "shifts")
    if sc:
        await sc.send(f"🟢 **{interaction.user.display_name}** clocked in.")


@bot.tree.command(name="checkout", description="Clock out of your shift")
async def checkout(interaction: discord.Interaction):
    rec = STATE["shifts"].get(str(interaction.user.id))
    if not rec or not rec.get("in"):
        await interaction.response.send_message("You're not clocked in.", ephemeral=True)
        return
    secs = int((now() - datetime.fromisoformat(rec["in"])).total_seconds())
    rec["total_seconds"] = rec.get("total_seconds", 0) + secs
    rec["in"] = None
    save_state()
    await interaction.response.send_message(
        f"👋 Clocked out — {secs // 3600}h {secs % 3600 // 60}m. Thank you!", ephemeral=True)
    sc = chan(interaction.guild, "shifts")
    if sc:
        await sc.send(f"🔴 **{interaction.user.display_name}** clocked out.")


@bot.tree.command(name="setup_server", description="Create all channels, roles and permissions")
async def setup_server(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⛔ Administrator required.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    g = interaction.guild
    made: list[str] = []
    colors = {"admin": 0xE74C3C, "manager": 0xE67E22, "kitchen": 0xF1C40F,
              "front": 0x3498DB, "runner": 0x2ECC71, "volunteer": 0x95A5A6,
              "vendor": 0x9B59B6}
    roles: dict[str, discord.Role] = {}
    for key, name in ROLES.items():
        r = discord.utils.get(g.roles, name=name)
        if r is None:
            perms = (discord.Permissions(manage_messages=True, mention_everyone=True)
                     if key in ("admin", "manager") else discord.Permissions.none())
            r = await g.create_role(name=name, colour=discord.Colour(colors.get(key, 0)),
                                    permissions=perms, hoist=key in ("admin", "manager", "kitchen"),
                                    mentionable=True, reason="Festival setup")
            made.append(f"role **{name}**")
        roles[key] = r

    everyone = g.default_role
    staff = [roles[k] for k in ("admin", "manager", "kitchen", "front", "runner", "volunteer")]

    def ov(read=True, send=True, allow=None):
        o = {everyone: discord.PermissionOverwrite(view_channel=read, send_messages=send)}
        for r in (allow or []):
            o[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        return o

    layout = [
        ("📢 INFO", [("welcome", ov(True, False)), ("announcements", ov(True, False))]),
        ("🍳 KITCHEN", [
            ("requests", ov(True, True)),          # everyone can post here — that's the point
            ("board", ov(True, False)),
            ("kitchen_text", ov(False, allow=staff)),
        ]),
        ("🛠️ OPS", [
            ("incidents", ov(False, allow=staff)),
            ("supply", ov(False, allow=staff)),
            ("shifts", ov(False, allow=staff)),
            ("ops", ov(False, allow=[roles["admin"], roles["manager"]])),
        ]),
        ("🗄️ RECORDS", [("log", ov(False, allow=[roles["admin"], roles["manager"]]))]),
    ]
    for cat_name, items in layout:
        cat = discord.utils.get(g.categories, name=cat_name) or \
            await g.create_category(cat_name, reason="Festival setup")
        for key, overwrites in items:
            cname = CHANS[key]
            if discord.utils.get(g.text_channels, name=cname) is None:
                await g.create_text_channel(cname, category=cat, overwrites=overwrites,
                                            reason="Festival setup")
                made.append(f"#{cname}")

    vcat = discord.utils.get(g.categories, name="🔊 SPEAKERS") or \
        await g.create_category("🔊 SPEAKERS", reason="Festival setup")
    for vname in (VOICE["kitchen_vc"], VOICE["foh_vc"]):
        if discord.utils.get(g.voice_channels, name=vname) is None:
            await g.create_voice_channel(vname, category=vcat, reason="Festival setup")
            made.append(f"🔊 {vname}")

    ip, port = lan_ip(), DASH["port"]
    await interaction.followup.send(
        "✅ **Server built.**\n" + ("\n".join(f"➕ {m}" for m in made) or "Everything already existed.") +
        f"\n\n**Next:**\n`/board` in #{CHANS['board']}\n`/tts_join`\n"
        f"Kitchen screen → `http://{ip}:{port}/kitchen`\n"
        f"Command center → `http://{ip}:{port}/`", ephemeral=True)


@bot.tree.command(name="tts_join", description="Connect the bot to the kitchen speaker channel")
async def tts_join(interaction: discord.Interaction):
    v = discord.utils.get(interaction.guild.voice_channels, name=VOICE["kitchen_vc"])
    if v is None:
        await interaction.response.send_message(
            f"❌ No voice channel named **{VOICE['kitchen_vc']}**.", ephemeral=True)
        return
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.move_to(v)
    else:
        await v.connect(reconnect=True)
    await interaction.response.send_message(f"🎙️ Connected to **{v.name}**.", ephemeral=True)


@bot.tree.command(name="audio", description="Diagnose why the kitchen speaker isn't talking")
async def audio(interaction: discord.Interaction):
    g = interaction.guild
    vc = g.voice_client
    kitchen = discord.utils.get(g.voice_channels, name=VOICE["kitchen_vc"])

    lines = []
    ok = True

    lines.append(f"{'✅' if shutil.which('ffmpeg') else '❌'} **FFmpeg** — "
                 + ("installed" if shutil.which("ffmpeg")
                    else "MISSING. No audio at all until you `brew install ffmpeg`."))
    if not shutil.which("ffmpeg"):
        ok = False

    if kitchen is None:
        lines.append(f"❌ **Voice channel** — no channel named `{VOICE['kitchen_vc']}`. "
                     "Run `/setup_server`.")
        ok = False
    elif vc is None:
        lines.append(f"❌ **Connection** — bot is NOT connected. Run `/tts_join`.")
        ok = False
    elif vc.channel.id != kitchen.id:
        lines.append(f"⚠️ **Connection** — bot is in `{vc.channel.name}`, "
                     f"not `{kitchen.name}`. Run `/tts_join`.")
        ok = False
    else:
        lines.append(f"✅ **Connection** — connected to `{kitchen.name}`")

    if kitchen is not None:
        listeners = [m for m in kitchen.members if not m.bot]
        if listeners:
            lines.append(f"✅ **Listeners** — {len(listeners)} device(s) in the channel: "
                         + ", ".join(m.display_name for m in listeners[:5]))
        else:
            lines.append("❌ **Listeners** — nobody is in the channel. The bot is "
                         "talking to an empty room. Join from the kitchen device.")
            ok = False

    if kitchen is not None and vc is not None and vc.is_connected():
        me = g.me
        perms = kitchen.permissions_for(me)
        if not perms.speak:
            lines.append("❌ **Permission** — the bot lacks **Speak** in that channel. "
                         "Channel settings → Permissions → allow Speak for the bot's role.")
            ok = False
        if me.voice and (me.voice.mute or me.voice.suppress):
            lines.append("❌ **Server-muted** — someone muted the bot. Right-click it in "
                         "the voice channel → uncheck Mute.")
            ok = False

    lines.append(f"{'✅' if stt.available else '⚠️'} **Speech-to-text** — "
                 + ("ready" if stt.available else f"off ({stt.reason})"))
    if tts.muted():
        left = int((datetime.fromisoformat(STATE["mute_until"]) - now()).total_seconds() // 60)
        lines.append(f"🔇 **Muted** — quiet for another {left} min (`/mute 0` to end)")
        ok = False
    lines.append(f"🔊 **Queue** — {tts.queue.qsize()} clip(s) waiting")
    lines.append(f"🎙️ **Voice messages** — play recording: "
                 f"`{VIN.get('play_recording', True)}` · "
                 f"then announce: `{VIN.get('announce_after_recording', True)}`")

    e = discord.Embed(
        title="🔎 Audio check",
        description="\n".join(lines),
        color=discord.Color.green() if ok else discord.Color.red())
    e.set_footer(text="Then run /say testing one two three to confirm end to end.")
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name="tts_leave", description="Disconnect the bot from voice")
async def tts_leave(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect(force=True)
        await interaction.response.send_message("👋 Disconnected.", ephemeral=True)
    else:
        await interaction.response.send_message("Not connected.", ephemeral=True)


@bot.tree.command(name="help_festival", description="How this works")
async def help_festival(interaction: discord.Interaction):
    e = discord.Embed(title=f"🍳 {FEST} — how this works", color=0x5865F2)
    e.description = (
        f"**Just type in #{CHANS['requests']}.** No commands.\n"
        "*\"two trays of koshary left\"* · *\"we're out of falafel\"* · "
        "*\"need more tawook asap\"*")
    e.add_field(
        name="🎙️ Or just talk",
        value="**Hold the microphone button** in the message box, say it, let go. "
              "Your recording plays through the kitchen speaker and the board "
              "updates itself.\n"
              "Prefer typing? Tap the **mic key on your phone keyboard** — it "
              "types what you say.\n"
              "Either way nobody opens a live mic, so there's no echo.",
        inline=False)
    e.add_field(
        name="Say several things at once",
        value="*\"we need 2 bechamel, 2 foul sandwich and 3 koshary trays\"* — all three "
              "land separately on the board, and the kitchen hears **one** clear "
              "announcement instead of three.",
        inline=False)
    e.add_field(name="Kitchen taps back",
                value="**On it — prepping** · **Ready now** · **⏱️ Set time** if it'll "
                      "take longer than usual. Multi-item requests get **On it — all "
                      "of them**. Front of house sees it instantly. No shouting, no relay.",
                inline=False)
    e.add_field(
        name="It chases things for you",
        value=f"Nothing claimed within **{BEH.get('nag_minutes', 7)} min**? It re-announces "
              "and pings the kitchen. Prep running past its ready time? It says so. "
              "Requests stop falling through the cracks.",
        inline=False)
    e.add_field(name="Commands (all optional)",
                value="`/status` what's low · `/set` status directly · `/history` one item's day\n"
                      "`/preptime` change how long something takes · `/preptimes` see them all\n"
                      "`/mute 10` silence the speaker for a speech · `/undo` fix a mistake\n"
                      "`/say` speak without changing status · `/screens` · `/audio` troubleshoot\n"
                      "`/incident` · `/checkin` `/checkout` · `/export` · `/allclear`",
                inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)


# --------------------------------------------------------------------------
# Web dashboards
# --------------------------------------------------------------------------

def dashboard_payload() -> dict[str, Any]:
    stale = DASH.get("stale_minutes", 45)
    grace = int(BEH.get("overdue_grace_minutes", 3))
    out = []
    for i in ITEMS:
        r = STATE["items"][i["id"]]
        lv = LEVELS[r["level"]]
        eta_txt, eta_mins, overdue = "", None, False
        if r.get("eta"):
            eta_mins = int((datetime.fromisoformat(r["eta"]) - now()).total_seconds() // 60)
            if eta_mins <= -grace:
                overdue, eta_txt = True, f"{abs(eta_mins)} min late"
            elif eta_mins <= 0:
                eta_txt = "ready now"
            else:
                eta_txt = f"{eta_mins} min"
        waiting = None
        if r.get("at") and r["level"] in ("need", "out", "low"):
            waiting = int((now() - datetime.fromisoformat(r["at"])).total_seconds() // 60)
        out.append({
            "id": i["id"], "name": i["name"], "station": i.get("station", ""),
            "screen": bool(i.get("screen")), "level": r["level"],
            "label": lv["label"], "emoji": lv["emoji"], "rank": lv["rank"],
            "detail": r.get("detail", ""), "by": r.get("by", ""),
            "ago": ago(r.get("at")), "eta": eta_txt, "eta_mins": eta_mins,
            "overdue": overdue, "waiting": waiting,
            "unclaimed": bool(r["level"] in ("need", "out") and not r.get("ack_by")),
            "stale": bool(r.get("at") and
                          (now() - datetime.fromisoformat(r["at"])).total_seconds() > stale * 60),
            "prep_min": prep_minutes(i["id"]),
        })
    muted_for = 0
    if STATE.get("mute_until"):
        muted_for = max(0, int((datetime.fromisoformat(STATE["mute_until"])
                                - now()).total_seconds() // 60))
    return {
        "festival": FEST,
        "clock": datetime.now().strftime("%-I:%M %p"),
        "muted_minutes": muted_for,
        "items": out,
        "feed": [{"ago": ago(f["at"]), "who": f["who"], "name": f["name"],
                  "level": f["level"], "text": f.get("text", "")} for f in STATE["feed"][:25]],
        "counts": {k: sum(1 for o in out if o["level"] == k) for k in LEVELS},
        "on_shift": [s["name"] for s in STATE["shifts"].values() if s.get("in")],
        "refresh": DASH.get("refresh_seconds", 2),
        "columns": DASH.get("kitchen_columns", 4),
    }


async def start_web() -> None:
    if not DASH.get("enabled", True):
        return

    token = str(DASH.get("access_token", "") or os.getenv("SMSM_DASH_TOKEN", ""))

    def authorised(req) -> bool:
        """
        Off by default (empty token) so local Wi-Fi use is unchanged. Set
        dashboard.access_token — or the SMSM_DASH_TOKEN env var — once this is
        reachable from the public internet.
        """
        if not token:
            return True
        return req.query.get("k") == token or req.headers.get("X-Access-Token") == token

    async def api(req):
        if not authorised(req):
            return web.json_response({"error": "unauthorised"}, status=401)
        return web.json_response(dashboard_payload())

    async def page(name):
        async def handler(req):
            if not authorised(req):
                return web.Response(text="Add ?k=<access_token> to this URL.", status=401)
            f = WEB_DIR / name
            if not f.exists():
                return web.Response(text=f"Missing {f}", status=500)
            return web.Response(text=f.read_text(encoding="utf-8"), content_type="text/html")
        return handler

    app = web.Application()
    app.router.add_get("/api/state", api)
    app.router.add_get("/", await page("command.html"))
    app.router.add_get("/kitchen", await page("kitchen.html"))
    runner = web.AppRunner(app)
    await runner.setup()

    # If another copy of the bot is still holding the port, don't die — step to
    # the next one and say so loudly. A festival can't afford a dead screen.
    base = int(os.getenv("PORT") or DASH["port"])
    for port in (base, base + 1, base + 2, base + 3):
        try:
            await web.TCPSite(runner, "0.0.0.0", port).start()
        except OSError as exc:
            if exc.errno in (48, 98, 10048):  # address already in use
                print(f"[warn] Port {port} is busy — trying {port + 1}…")
                continue
            raise
        ip = lan_ip()
        if port != base:
            print(f"[warn] Another bot is still running on port {base}.")
            print(f"[warn] Close it, or these screens will move again on restart.")
        print(f"[ok] Kitchen screen   →  http://{ip}:{port}/kitchen")
        print(f"[ok] Command center   →  http://{ip}:{port}/")
        DASH["port"] = port          # so /screens reports the truth
        return

    print("[error] Could not open a port for the screens. Something else is using "
          f"{base}–{base + 3}. Close the other bot window and restart.")


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------

@tasks.loop(seconds=BEH.get("board_refresh_seconds", 20))
async def ticker():
    for g in bot.guilds:
        try:
            await refresh_board(g)
        except Exception:
            traceback.print_exc()


@ticker.before_loop
async def _wait():
    await bot.wait_until_ready()


@tasks.loop(minutes=1)
async def watchdog():
    """
    Two jobs, both about requests that quietly die:
      1. Nag — something is NEED/OUT and nobody has claimed it.
      2. Overdue — someone claimed it but the ETA has come and gone.
    This is the difference between a system people trust and one they don't.
    """
    nag_after = int(BEH.get("nag_minutes", 7))
    nag_max = int(BEH.get("nag_max", 3))
    grace = int(BEH.get("overdue_grace_minutes", 3))

    for g in bot.guilds:
        nags: list[str] = []
        overdue: list[str] = []
        try:
            async with _lock:
                for it in ITEMS:
                    rec = STATE["items"].get(it["id"])
                    if not rec or not rec.get("at"):
                        continue
                    age = (now() - datetime.fromisoformat(rec["at"])).total_seconds() / 60

                    if (rec["level"] in ("need", "out") and not rec.get("ack_by")
                            and age >= nag_after * (rec.get("nags", 0) + 1)
                            and rec.get("nags", 0) < nag_max):
                        rec["nags"] = rec.get("nags", 0) + 1
                        nags.append(it["id"])

                    if (rec["level"] == "prepping" and rec.get("eta")
                            and not rec.get("overdue_called")):
                        late = (now() - datetime.fromisoformat(rec["eta"])).total_seconds() / 60
                        if late >= grace:
                            rec["overdue_called"] = True
                            overdue.append(it["id"])
                if nags or overdue:
                    save_state()

            if nags:
                names = _join_names([ITEM_BY_ID[i]["name"].title() for i in nags])
                mins = int((now() - datetime.fromisoformat(
                    STATE["items"][nags[0]]["at"])).total_seconds() / 60)
                await tts.speak(g.id,
                                f"{VOICE.get('attention_prefix', '')} Still waiting on "
                                f"{names}. Nobody has picked this up.",
                                target="kitchen", repeat=2)
                kr, kc = role_obj(g, "kitchen"), chan(g, "kitchen_text")
                if kc:
                    e = discord.Embed(
                        title="⏰ Still unclaimed",
                        description="\n".join(
                            f"{LEVELS[STATE['items'][i]['level']]['emoji']} "
                            f"**{ITEM_BY_ID[i]['name']}** — asked for "
                            f"{ago(STATE['items'][i]['at'])}" for i in nags),
                        color=discord.Color.red(), timestamp=now())
                    e.set_footer(text="Tap a button on the request, or say you're on it.")
                    await kc.send(content=kr.mention if kr else None, embed=e,
                                  view=BatchAckView(nags))

            if overdue:
                names = _join_names([ITEM_BY_ID[i]["name"].title() for i in overdue])
                if BEH.get("announce_overdue", True):
                    await tts.speak(g.id,
                                    f"{VOICE.get('attention_prefix', '')} {names} "
                                    f"past the ready time. Status check please.",
                                    target="kitchen")
                kc = chan(g, "kitchen_text")
                if kc:
                    await kc.send(embed=discord.Embed(
                        title="⌛ Past its ready time",
                        description="\n".join(
                            f"🔵 **{ITEM_BY_ID[i]['name']}** — was due "
                            f"{ago(STATE['items'][i]['eta'])}, "
                            f"{STATE['items'][i].get('by', '')}" for i in overdue),
                        color=discord.Color.orange(), timestamp=now()),
                        view=BatchAckView(overdue))
        except Exception:
            traceback.print_exc()


@watchdog.before_loop
async def _wait2():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f"[ok] Logged in as {bot.user} — {FEST}")
    bot.add_view(AckView())
    try:
        print(f"[ok] Synced {len(await bot.tree.sync())} slash commands.")
    except Exception:
        traceback.print_exc()
    tts.start()
    if not ticker.is_running():
        ticker.start()
    if not watchdog.is_running():
        watchdog.start()
    await start_web()
    await stt.load()
    if not stt.available:
        print(f"[info] Spoken messages will play but not update the board — {stt.reason}")
    if VOICE.get("auto_join_on_start"):
        for g in bot.guilds:
            v = discord.utils.get(g.voice_channels, name=VOICE["kitchen_vc"])
            if v and g.voice_client is None:
                try:
                    await v.connect(reconnect=True)
                    print(f"[ok] Joined voice: {v.name}")
                except Exception as exc:
                    print(f"[warn] voice join failed: {exc}")


async def on_tree_error(interaction: discord.Interaction, error: Exception):
    traceback.print_exception(type(error), error, error.__traceback__)
    msg = "⚠️ Something went wrong — it's logged. Try again."
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


bot.tree.on_error = on_tree_error


def main() -> None:
    if not TOKEN:
        raise SystemExit(
            "No DISCORD_TOKEN found.\n"
            "Create a file named .env next to bot.py containing:\n"
            "  DISCORD_TOKEN=your_token_here")
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
