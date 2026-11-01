FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 HF_HUB_OFFLINE=1
COPY requirements.txt /srv/
RUN pip install --root-user-action=ignore -r /srv/requirements.txt \
    && groupadd --gid 10003 guard && useradd --uid 10003 --gid guard --no-create-home guard
COPY lecteur.py serveur.py /srv/
# No network access, no secrets, no volume: see compose.yaml.
USER 10003:10003
WORKDIR /srv
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"]
CMD ["python", "serveur.py"]
