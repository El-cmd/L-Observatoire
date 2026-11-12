FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && pip freeze > /app/versions.txt
COPY graphe.py serveur.py ./
COPY consignes ./consignes
COPY tests ./tests
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=6s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/sante', timeout=4)"]
CMD ["python", "serveur.py"]
