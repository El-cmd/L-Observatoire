SHELL := /bin/sh
.PHONY: help init build up down restart logs status user first-user reset-password test backup
help:
	@printf '%s\n' 'make init            Initialiser la configuration locale' 'make up              Construire et lancer les trois services' 'make user            Créer un compte' 'make reset-password  Réinitialiser un mot de passe' 'make backup          Sauvegarder PostgreSQL' 'make down            Arrêter sans effacer les données' 'make logs            Suivre les logs' 'make test            Tests Rust et intégration'
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
backup:
	python3 scripts/backup.py
test:
	docker run --rm -v "$(CURDIR)/backend:/app" -v observatoire-cargo-registry:/usr/local/cargo/registry -v observatoire-cargo-target:/app/target -w /app rust:1-slim-trixie cargo test --locked
	python3 tests/integration/run.py
