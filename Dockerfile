FROM python:3.12-slim

WORKDIR /srv/fishlog

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app
COPY config config

ENV FISHLOG_DB_PATH=/data/fishlog.db
VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "app.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
