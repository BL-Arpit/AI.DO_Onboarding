FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /project
COPY requirements.txt requirements-advo.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-advo.txt
COPY . .
RUN useradd --create-home onboarding && mkdir -p /data && chown onboarding /data
USER onboarding
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
