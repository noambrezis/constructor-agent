FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

STOPSIGNAL SIGTERM

# Shell form so ${PORT} is expanded at runtime (Railway sets $PORT dynamically).
# start.sh runs `alembic upgrade head` before launching uvicorn.
CMD ["bash", "start.sh"]
