SHELL := /bin/sh
.PHONY: help init build up down restart logs status user first-user reset-password recherche-web test test-frontend test-recherche backup
help:
	@printf '%s\n' 'make init            Initialiser la configuration locale' 'make up              Construire et lancer les services' 'make user            Créer un compte' 'make reset-password  Réinitialiser un mot de passe' 'make recherche-web   Ouvrir ou fermer la recherche web à un compte' 'make backup          Sauvegarder PostgreSQL' 'make down            Arrêter sans effacer les données' 'make logs            Suivre les logs' 'make test            Tests Rust et intégration'
init:
	python3 scripts/init_env.py
build: init
	docker compose build
up: init
	docker compose up -d --build --remove-orphans
down:
	docker compose down
restart: init
	docker compose up -d --force-recreate --remove-orphans
logs:
	docker compose logs -f --tail=100
status:
	docker compose ps
user:
	python3 scripts/user.py
first-user:
	python3 scripts/first_user.py
reset-password:
	python3 scripts/user.py --reset
recherche-web:
	python3 scripts/user.py --recherche-web
backup:
	python3 scripts/backup.py
test-frontend:
	docker build --target build -f frontend/Dockerfile .
# Orchestrateur, et recherche web (service et outil MCP) : tests unitaires sans réseau. Les images de la recherche
# sont construites ici, car leur profil n'est pas actif par défaut.
test-recherche:
	docker run --rm --network none --read-only --tmpfs /tmp:size=4m observatoire-orchestrateur:local python -m unittest discover -s tests
	docker build -q -t observatoire-recherche-service:local recherche/service >/dev/null
	docker build -q -t observatoire-recherche:local recherche/outil >/dev/null
	docker run --rm --network none --read-only --tmpfs /tmp:size=4m observatoire-recherche-service:local python -m unittest discover -s tests
	docker run --rm --network none --read-only --tmpfs /tmp:size=4m observatoire-recherche:local python -m unittest discover -s tests
test: test-frontend test-recherche
	docker run --rm -v "$(CURDIR)/backend:/app" -v observatoire-cargo-registry:/usr/local/cargo/registry -v observatoire-cargo-target:/app/target -w /app rust:1-slim-trixie cargo test --locked
	docker run --rm -v "$(CURDIR)/image-guard:/app" -v observatoire-cargo-registry:/usr/local/cargo/registry -v observatoire-guard-target:/app/target -w /app rust:1-slim-trixie cargo test --locked
	docker run --rm -v "$(CURDIR)/doc-guard:/t:ro" -w /t -e PYTHONDONTWRITEBYTECODE=1 observatoire-doc-guard:local python -m unittest test_lecteur
	python3 tests/integration/run.py
