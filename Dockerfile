FROM python:3.11-slim

# чуть стабильности вывода/кэширования
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# компилятор для некоторых колёс может пригодиться
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

# сначала requirements — лучше кэшируется
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# затем всё приложение
COPY . /app
