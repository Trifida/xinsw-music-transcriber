FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    MUSICMASTER_HOST=0.0.0.0

WORKDIR /app

# LilyPond renders the original jianpu-ly output; Noto CJK supplies Chinese glyphs.
RUN apt-get update && apt-get install -y --no-install-recommends \
      fonts-dejavu-core fonts-noto-cjk fontconfig libatomic1 libstdc++6 \
      lilypond libsndfile1 libgomp1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

ARG CREPE_MODEL_URL
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir tensorflow==2.15.0 \
    && python -m pip install --no-cache-dir --no-build-isolation --no-deps ./vendor/crepe \
    && if [ -n "$CREPE_MODEL_URL" ]; then CREPE_MODEL_URL="$CREPE_MODEL_URL" python scripts/prepare_crepe_model.py; else python scripts/prepare_crepe_model.py; fi \
    && python -m pip install --no-cache-dir -r requirements/requirements-core.txt \
    && python -m pip install --no-cache-dir -e .

EXPOSE 7860

# Render and other container platforms supply PORT at runtime.
CMD ["sh", "-c", "export MUSICMASTER_PORT=${PORT:-7860}; exec python -m musicmaster.web.server"]
