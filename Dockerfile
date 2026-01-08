FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY vakula ./vakula

RUN pip install --no-cache-dir "fastapi>=0.122.0,<0.123.0"     "uvicorn[standard]>=0.38.0,<0.39.0"     "httpx>=0.27.0,<0.28.0"

CMD ["python", "-m", "vakula.weather_broker"]
