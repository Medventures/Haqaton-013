FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY entrypoint.sh ./entrypoint.sh
RUN pip install --no-cache-dir . && useradd --system --uid 10001 --create-home medhub && mkdir -p /app/storage && chown -R medhub:medhub /app/storage && chmod +x /app/entrypoint.sh
USER medhub
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
