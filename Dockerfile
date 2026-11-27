FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BIND_HOST=0.0.0.0 OMP_THREAD_LIMIT=1 DOCUMENT_MODE=google_vision
ENV CHAT_PROVIDER=groq GROQ_MODEL=qwen/qwen3.8-27b GGUF_MODEL_PATH="" OPENBLAS_NUM_THREADS=1
WORKDIR /project
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY app ./app
COPY --from=frontend /app/static/react ./app/static/react
COPY --from=frontend /app/static/react/index.html ./app/static/workspace.html
COPY config ./config
COPY model/doc_classifier.onnx model/labels.json ./model/
COPY run.py ./
COPY scripts/check_groq_model.py ./scripts/check_groq_model.py
COPY scripts/fetch_memory_model.py ./scripts/fetch_memory_model.py
RUN python scripts/fetch_memory_model.py /project/model/memory
RUN useradd --uid 10001 --create-home onboarding && mkdir -p /project/data && chown -R onboarding:onboarding /project/data
USER onboarding
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live')" || exit 1
CMD ["python","run.py"]
