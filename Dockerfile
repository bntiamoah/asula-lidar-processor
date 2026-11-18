FROM python:3.13-slim AS emulator
RUN python -m pip install --no-cache-dir "moto[server]>=5.1,<6"
CMD ["moto_server", "-H", "0.0.0.0", "-p", "5000"]

FROM python:3.13-slim AS app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY pointcloud ./pointcloud
COPY migrations ./migrations
RUN python -m pip install --no-cache-dir .
