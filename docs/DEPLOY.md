# Deploying to a server

The bot is one long-running process. It needs:

- **Python 3.12** (see the 3.13 `audioop` note in the README)
- **ffmpeg** on PATH — without it there is no audio at all
- **A writable volume** for `state.json` and `request_log.csv`
- **Outbound UDP** for Discord voice
- **One TCP port** (default 8080) for the dashboards
- ~1 GB RAM with speech-to-text enabled, ~256 MB without

## Read this before you pick a host

**Discord voice needs outbound UDP on a wide, dynamic port range.** Plenty of PaaS
tiers either block it or NAT it in a way that breaks RTP while leaving text working
perfectly. You will deploy, see the bot online, watch the board update, and assume
success — then discover on event day that the speaker never worked.

**Test `/say testing` within 60 seconds of your first deploy.** If it's silent, the
host is the problem, not the code. A $5 VPS with a real public IP (Hetzner, DO,
Vultr, Lightsail) avoids the entire question and is what I'd choose.

Second consideration: **faster-whisper is CPU-hungry**. `base.en` on one shared vCPU
takes a few seconds per clip. Either give it 2 vCPUs, drop to `tiny.en`, or set
`voice_input.transcribe: false` and let recordings play without transcription.

## Environment variables

| Var | Purpose |
|---|---|
| `DISCORD_TOKEN` | **Required.** Bot token |
| `SMSM_STATE_DIR` | Where `state.json` and `request_log.csv` live. Point at your volume |
| `SMSM_CONFIG` | Path to `config.json` if you mount it separately |
| `SMSM_DASH_TOKEN` | Dashboard access token. **Set this if the port is public** |
| `PORT` | Overrides `dashboard.port` |

## Docker

```bash
docker build -f deploy/Dockerfile -t smsm-ops .
docker run -d --name smsm-ops --restart unless-stopped \
  -e DISCORD_TOKEN=... \
  -e SMSM_STATE_DIR=/data \
  -e SMSM_DASH_TOKEN=$(openssl rand -hex 16) \
  -v smsm-data:/data \
  -p 8080:8080 \
  smsm-ops
```

Or `docker compose -f deploy/docker-compose.yml up -d` after filling in `.env`.

The image installs ffmpeg and pre-downloads the whisper model at build time, so
first-run latency doesn't land on the festival.

## systemd (plain VPS)

```bash
sudo apt install -y python3.12 python3.12-venv ffmpeg
sudo useradd -r -m -d /opt/smsm smsm
sudo -u smsm git clone <repo> /opt/smsm/app
cd /opt/smsm/app
sudo -u smsm python3.12 -m venv .venv
sudo -u smsm ./.venv/bin/python -m pip install -r requirements.txt
sudo -u smsm cp .env.example .env && sudo -u smsm nano .env   # paste token

sudo cp deploy/smsm-bot.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now smsm-bot
journalctl -u smsm-bot -f
```

## Exposing the dashboards safely

Once the port is reachable from the internet, anyone can watch your kitchen board
and read every request. That's not catastrophic, but it's also not intended.

**Minimum:** set `SMSM_DASH_TOKEN` and use `https://host/kitchen?k=<token>`.

**Better:** put it behind Caddy or nginx with TLS and basic auth, and keep 8080 bound
to localhost.

```caddy
kitchen.example.org {
    reverse_proxy 127.0.0.1:8080
    basicauth { festival $2a$14$... }
}
```

**On the day**, the kitchen TV browser should have the tokenised URL bookmarked so
nobody is typing a secret on a greasy touchscreen.

## Keeping the state

`state.json` is the live board. `request_log.csv` is the year-over-year record.
Both are in `SMSM_STATE_DIR`. Back the volume up between festival days — it's a few
hundred KB and it's the only thing that isn't reproducible from the repo.

`/export` in Discord pulls both out without server access.

## Health checking

There's no `/health` endpoint yet — `GET /api/state` returning 200 is a fine proxy
(add `?k=` if a token is set). Worth adding a real one if you put this behind a
platform that expects it.

## What breaks and what to do

| Symptom | Cause |
|---|---|
| Bot online, board updates, speaker silent | ffmpeg missing, or the host blocks voice UDP. `/audio` in Discord tells you which |
| `PrivilegedIntentsRequired` at boot | Message Content Intent off in the Discord developer portal |
| Screens 401 | Token set but the URL has no `?k=` |
| Screens on an unexpected port | Another instance holds the port; it stepped to base+1 and said so at startup |
| Voice messages play but never move the board | faster-whisper not installed, or the model failed to load. Startup log says which |
| Transcription slow | Underpowered CPU. Drop to `tiny.en` |
