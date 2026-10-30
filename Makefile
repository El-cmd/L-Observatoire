SHELL := /bin/sh
.PHONY: help init build up down restart logs status dev test clean
help:
	@printf '%s\n' 'make init     Créer .env sans écraser la configuration' 'make up       Construire et lancer sur http://localhost:8080' 'make down     Arrêter les conteneurs du projet' 'make restart  Recharger la configuration' 'make logs     Suivre les logs' 'make status   État du conteneur' 'make dev      Lancer sans Docker (Python 3.11+)' 'make test     Tester le proxy' 'make clean    Retirer le conteneur et son image locale'
init:
	@test -f .env || (umask 077; cp .env.example .env)
build: init
	docker compose build
up: init
	docker compose up -d --build
down:
	docker compose down
restart: init
	docker compose up -d --force-recreate
logs:
	docker compose logs -f --tail=100
status:
	docker compose ps
dev: init
	@set -a; . ./.env; set +a; exec python3 server.py
test:
	python3 -m unittest discover -s tests -v
clean:
	docker compose down --rmi all
