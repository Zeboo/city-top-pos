FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# The server image deliberately excludes the PySide desktop/build toolchain.
COPY requirements-web.txt ./
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements-web.txt

COPY app ./app

# Allow the SQLite development fallback to create /app/data while keeping the
# production process unprivileged. Railway production should use PostgreSQL.
RUN addgroup --system pos && adduser --system --ingroup pos pos \
    && mkdir -p /app/data \
    && chown -R pos:pos /app

USER pos
EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app.web:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
