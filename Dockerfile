FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip \
    && python -m pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cu132 \
    && python -m pip install openai-whisper==20250625 \
    && python -c "import torch, whisper; print(torch.__version__, whisper.__version__)"

WORKDIR /app
COPY container/worker.py /app/worker.py
