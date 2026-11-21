# Build Dolce's documented headless engraving entry from a pinned upstream revision.
# The renderer is TypeScript/Node; the transcription service remains Python.
FROM node:20-bookworm-slim AS dolce-build
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/dolce
RUN git init \
    && git remote add origin https://github.com/lodebar2026/dolce.git \
    && git fetch --depth=1 origin defb7594b00a42cda8030cdf68baa61e3b562b72 \
    && git checkout --detach FETCH_HEAD
RUN npm install --no-audit --no-fund --package-lock=false \
    && npm run build:cli

# Build-time smoke test: exercise the real MusicXML -> Dolce SVG headless path.
ENV DOLCE_CLI_ENTRY=/opt/dolce/out/cli/engrave.js
COPY scripts/dolce_render.mjs /tmp/dolce_render.mjs
COPY tests/fixtures/dolce-smoke.musicxml /tmp/dolce-smoke.musicxml
RUN node /tmp/dolce_render.mjs /tmp/dolce-smoke.musicxml /tmp/dolce-smoke-output > /tmp/dolce-smoke-result.json \
    && node -e 'const r=JSON.parse(require("fs").readFileSync("/tmp/dolce-smoke-result.json","utf8")); if(r.page_count < 2) throw new Error("Expected multi-page output: " + JSON.stringify(r))' \
    && test -s /tmp/dolce-smoke-output/jianpu-dolce-2.svg \
    && grep -q '春' /tmp/dolce-smoke-output/jianpu-dolce-1.svg

# Main CPU service. Dolce's SVG pages are converted to PNG/PDF by librsvg.
FROM python:3.11-slim-bookworm AS dolce-runtime-check
ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    MUSICMASTER_HOST=0.0.0.0 \
    DOLCE_CLI_ENTRY=/opt/dolce/out/cli/engrave.js

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      fonts-dejavu-core fonts-noto-cjk fontconfig libatomic1 libstdc++6 \
      librsvg2-bin poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Reuse the exact Node runtime and built headless package; no extra Render service.
COPY --from=dolce-build /usr/local/bin/node /usr/local/bin/node
COPY --from=dolce-build /opt/dolce /opt/dolce
RUN mkdir -p /usr/local/share/fonts/dolce \
    && cp /opt/dolce/public/redist/Bravura.otf /usr/local/share/fonts/dolce/ \
    && cp /opt/dolce/public/redist/BravuraText.otf /usr/local/share/fonts/dolce/ \
    && fc-cache -f

COPY . /app
RUN mkdir -p /app/musicmaster/web/static/fonts/dolce \
    && cp /opt/dolce/public/redist/Bravura.woff2 /app/musicmaster/web/static/fonts/dolce/ \
    && cp /opt/dolce/public/redist/BravuraText.otf /app/musicmaster/web/static/fonts/dolce/

# Runtime smoke test: the copied Node binary, Bravura fonts and librsvg must work together.
RUN node /app/scripts/dolce_render.mjs /app/tests/fixtures/dolce-smoke.musicxml /tmp/dolce-runtime-smoke > /tmp/dolce-runtime-result.json \
    && node -e 'const r=JSON.parse(require("fs").readFileSync("/tmp/dolce-runtime-result.json","utf8")); if(r.page_count < 2) throw new Error("Expected multi-page output, got " + r.page_count)' \
    && test -s /tmp/dolce-runtime-smoke/jianpu-dolce-2.svg \
    && grep -q '春' /tmp/dolce-runtime-smoke/jianpu-dolce-1.svg \
    && rsvg-convert -f png -d 192 -p 192 -b white -o /tmp/dolce-runtime-smoke-1.png /tmp/dolce-runtime-smoke/jianpu-dolce-1.svg \
    && rsvg-convert -f pdf -o /tmp/dolce-runtime-smoke-1.pdf /tmp/dolce-runtime-smoke/jianpu-dolce-1.svg \
    && rsvg-convert -f pdf -o /tmp/dolce-runtime-smoke-2.pdf /tmp/dolce-runtime-smoke/jianpu-dolce-2.svg \
    && pdfunite /tmp/dolce-runtime-smoke-1.pdf /tmp/dolce-runtime-smoke-2.pdf /tmp/dolce-runtime-smoke.pdf \
    && test -s /tmp/dolce-runtime-smoke-1.png \
    && pdfinfo /tmp/dolce-runtime-smoke.pdf | grep -Eq 'Pages:[[:space:]]+2'

# Only the final application stage installs the heavier transcription stack and CREPE weights.
FROM dolce-runtime-check AS final
ARG CREPE_MODEL_URL

RUN apt-get update && apt-get install -y --no-install-recommends \
      lilypond libsndfile1 libgomp1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir tensorflow==2.15.0 \
    && python -m pip install --no-cache-dir --no-build-isolation --no-deps ./vendor/crepe \
    && if [ -n "$CREPE_MODEL_URL" ]; then CREPE_MODEL_URL="$CREPE_MODEL_URL" python scripts/prepare_crepe_model.py; else python scripts/prepare_crepe_model.py; fi \
    && python -m pip install --no-cache-dir -r requirements/requirements-core.txt \
    && python -m pip install --no-cache-dir -e .

EXPOSE 7860

# Render and other container platforms supply PORT at runtime.
CMD ["sh", "-c", "export MUSICMASTER_PORT=${PORT:-7860}; exec python -m musicmaster.web.server"]
