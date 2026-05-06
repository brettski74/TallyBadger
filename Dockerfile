FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    libpq5 \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir .

EXPOSE 8080

ENV TALLYBADGER_DATABASE_URL=postgresql://tallybadger:tallybadger@db:5432/tallybadger

CMD ["uvicorn", "tallybadger.main:app", "--host", "0.0.0.0", "--port", "8080"]
