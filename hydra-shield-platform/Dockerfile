# HydraShield production image.
# Both the Dash dashboard (wsgi:dash_server) and the REST API (wsgi:api_app)
# run from this single image under gunicorn; the entrypoint is chosen in
# docker-compose.

FROM python:3.12-slim

# geopandas / shapely / pyproj / fiona ship prebuilt manylinux wheels that
# bundle GDAL/GEOS/PROJ, so no system GIS packages are needed.
# If a future version fails to build, uncomment the fallback below:
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     gdal-bin libgdal-dev libgeos-dev libproj-dev && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /code

# Install dependencies first for better layer caching.
COPY requirements-prod.txt ./
RUN pip install -r requirements-prod.txt

# Copy the full application source.
COPY . /code

# Dash (8050) and API (8051) are exposed; Caddy routes to them internally.
EXPOSE 8050 8051

# Default command runs the Dash dashboard via gunicorn; compose overrides it.
CMD ["gunicorn", "--workers", "2", "--threads", "2", "--timeout", "180", "--bind", "0.0.0.0:8050", "wsgi:dash_server"]