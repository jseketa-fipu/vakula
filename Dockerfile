FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

COPY service-gateway ./service-gateway
COPY service-station ./service-station
COPY service-broker ./service-broker
COPY service-degrader ./service-degrader
COPY service-telegram ./service-telegram
COPY service-orchestrator ./service-orchestrator
COPY vakula_common ./vakula_common

RUN pip install --no-cache-dir "fastapi>=0.122.0,<0.123.0"     "uvicorn[standard]>=0.38.0,<0.39.0"     "aiohttp>=3.9.5,<4.0.0"
