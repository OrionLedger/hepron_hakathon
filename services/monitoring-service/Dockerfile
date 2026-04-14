FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY shared/ /shared/
RUN pip install /shared/

COPY services/monitoring-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/monitoring-service/ .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
