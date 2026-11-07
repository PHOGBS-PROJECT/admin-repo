# One image for the web app and the background worker.
#   web:    docker run ... phogbs            (Gunicorn, the default command)
#   worker: docker run ... phogbs celery -A config worker --loglevel=info
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app

COPY requirements.txt .
# colorama is Windows-only tooling that ended up in the frozen requirements.
RUN grep -viE "^(colorama)==" requirements.txt > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

COPY . .

# Static files are collected at build time so file names can carry content
# hashes (STATIC_MANIFEST=True) and be cached by a CDN for a year.
RUN SECRET_KEY=build-only DATABASE_URL=sqlite:////tmp/build.db ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput

RUN useradd --create-home --uid 1000 app && chown -R app /app
USER app

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--config", "gunicorn.conf.py"]
