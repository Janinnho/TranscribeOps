FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Download vendor assets for offline operation
RUN mkdir -p /app/app/static/vendor/bootstrap/css \
             /app/app/static/vendor/bootstrap/js \
             /app/app/static/vendor/bootstrap-icons/fonts \
             /app/app/static/vendor/marked \
    && curl -sL -o /app/app/static/vendor/bootstrap/css/bootstrap.min.css \
       https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css \
    && curl -sL -o /app/app/static/vendor/bootstrap/js/bootstrap.bundle.min.js \
       https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js \
    && curl -sL -o /app/app/static/vendor/bootstrap-icons/bootstrap-icons.css \
       https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css \
    && curl -sL -o /app/app/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff \
       https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff \
    && curl -sL -o /app/app/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2 \
       https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff2 \
    && curl -sL -o /app/app/static/vendor/marked/marked.min.js \
       https://cdn.jsdelivr.net/npm/marked@15.0.7/marked.min.js

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/app/static/uploads

ENV FLASK_APP=run.py
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "600", "run:app"]
