FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BIND_HOST=0.0.0.0 OMP_THREAD_LIMIT=1 DOCUMENT_MODE=google_vision
WORKDIR /project
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.lock requirements-gguf.txt ./
ARG INSTALL_GGUF=1
ARG GGUF_MODEL_URL=https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF/resolve/main/SmolLM2-135M-Instruct-Q4_K_S.gguf
ARG GGUF_MODEL_SHA256=a8654d8eb14c45ef3c6170b3f0c6ccd02ba3e1a6b406ca02f4ffadf0b1b222a0
ENV GGUF_MODEL_PATH=/project/model/replies.gguf GGUF_CONTEXT_TOKENS=1024 GGUF_THREADS=1 GGUF_MAX_REPLY_TOKENS=128
ENV OPENBLAS_NUM_THREADS=1

RUN pip install --no-cache-dir -r requirements.lock
RUN if [ "$INSTALL_GGUF" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends build-essential cmake && \
      CMAKE_BUILD_PARALLEL_LEVEL=2 CMAKE_ARGS="-DGGML_NATIVE=OFF" pip install --no-cache-dir -r requirements-gguf.txt && \
      apt-get purge -y --auto-remove build-essential cmake && rm -rf /var/lib/apt/lists/*; \
    fi
COPY app ./app
COPY --from=frontend /app/static/react ./app/static/react
COPY --from=frontend /app/static/react/index.html ./app/static/workspace.html
COPY config ./config
COPY model ./model
COPY run.py ./
COPY scripts/check_local_model.py ./scripts/check_local_model.py
COPY scripts/fetch_memory_model.py ./scripts/fetch_memory_model.py
RUN python scripts/fetch_memory_model.py /project/model/memory
RUN if [ -n "$GGUF_MODEL_URL" ]; then \
      test "$INSTALL_GGUF" = 1 && test -n "$GGUF_MODEL_SHA256" && \
      python -c 'import sys,urllib.request; urllib.request.urlretrieve(sys.argv[1], "/project/model/replies.gguf")' "$GGUF_MODEL_URL" && \
      printf '%s  %s\n' "$GGUF_MODEL_SHA256" /project/model/replies.gguf | sha256sum -c -; \
    fi
RUN useradd --uid 10001 --create-home onboarding && mkdir -p /project/data && chown -R onboarding:onboarding /project/data
USER onboarding
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live')" || exit 1
CMD ["python","run.py"]
