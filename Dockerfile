FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BIND_HOST=0.0.0.0 OMP_THREAD_LIMIT=1 DOCUMENT_MODE=google_vision
WORKDIR /project
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY app ./app
COPY config ./config
COPY model ./model
COPY run.py ./
RUN useradd --uid 10001 --create-home onboarding && mkdir -p /project/data && chown -R onboarding:onboarding /project/data
USER onboarding
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live')" || exit 1
CMD ["python","run.py"]
