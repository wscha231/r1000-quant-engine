FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY tools/product_analytics_collector/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

RUN mkdir -p /app/tools /app/data_static /app/tools/product_analytics_collector
COPY tools/aggregate_product_analytics.py /app/tools/aggregate_product_analytics.py
COPY data_static/product_analytics_event_contract_v1.json /app/data_static/product_analytics_event_contract_v1.json
COPY tools/product_analytics_collector/__init__.py /app/tools/product_analytics_collector/__init__.py
COPY tools/product_analytics_collector/app.py /app/tools/product_analytics_collector/app.py
COPY tools/product_analytics_collector/firestore_store.py /app/tools/product_analytics_collector/firestore_store.py

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 8 --timeout 30 --max-requests 10000 --max-requests-jitter 500 tools.product_analytics_collector.app:app"]
