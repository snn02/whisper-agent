FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/huggingface \
    PYANNOTE_METRICS_ENABLED=0

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip \
    && python -m pip install torch==2.13.0 torchaudio==2.11.1 --index-url https://download.pytorch.org/whl/cu132 \
    && python -m pip install openai-whisper==20250625 pyannote.audio==4.0.7 'torch==2.13.0' 'torchaudio==2.11.1' \
    && python -m pip check \
    && python -c "import torch, whisper; from pyannote.audio import Pipeline; print(torch.__version__, whisper.__version__)"

WORKDIR /app
COPY container/worker.py /app/worker.py
COPY container/diarization.py /app/diarization.py
