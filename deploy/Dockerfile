# SMSM Festival Ops
# Python 3.12 on purpose: 3.13 removed the audioop stdlib module that
# discord.py's voice support needs.
FROM python:3.12-slim

# ffmpeg is not optional — without it there is no audio at all.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the speech model into the image so the first voice message of the
# festival isn't waiting on a 150 MB download.
ARG WHISPER_MODEL=base.en
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8')" || \
    echo "model prefetch skipped — it will download on first use"

COPY bot.py config.json ./
COPY web/ ./web/

# state.json and request_log.csv live here. Mount a volume.
ENV SMSM_STATE_DIR=/data
RUN mkdir -p /data && useradd -r -u 10001 smsm && chown -R smsm /data /app
USER smsm
VOLUME ["/data"]

EXPOSE 8080
CMD ["python", "-u", "bot.py"]
