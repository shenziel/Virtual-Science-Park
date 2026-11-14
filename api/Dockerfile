# One image for api, ui and one-off agent runs; the compose command picks the role.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --only-binary :all: --require-hashes -r requirements.txt

# Unprivileged runtime user. /data is the named volume for SQLite and caches.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown app:app /data

# Copy only the source folders, never the whole build context.
# Add agents/ and ui/ here once they are merged into main.
COPY contracts/ contracts/
COPY fixtures/ fixtures/
COPY api/ api/
COPY db/ db/

USER app
