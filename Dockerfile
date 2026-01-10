FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY README.md ./
COPY service-gateway ./service-gateway
COPY service-station ./service-station
COPY service-broker ./service-broker
COPY service-degrader ./service-degrader
COPY service-telegram ./service-telegram
COPY service-orchestrator ./service-orchestrator

RUN pip install --no-cache-dir "fastapi>=0.122.0,<0.123.0"     "uvicorn[standard]>=0.38.0,<0.39.0"     "httpx>=0.27.0,<0.28.0"

CMD ["python", "/app/service-broker/server.py"]
