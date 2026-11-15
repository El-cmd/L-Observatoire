SHELL := /bin/sh
.PHONY: help init build up down restart logs status user first-user reset-password recherche-web test test-frontend test-recherche backup depot-principal clean-worktree

# Dans un worktree Git (plusieurs agents en même temps), les images et le cache de compilation Rust portent le nom du
# worktree : deux worktrees ne s'écrasent pas leurs images, et leurs tests testent bien leur propre code. Dans le dépôt
# principal, en CI et sur le VPS : « local », comme avant.
WORKTREE := $(shell [ "$$(git rev-parse --absolute-git-dir 2>/dev/null)" != "$$(cd "$$(git rev-parse --git-common-dir 2>/dev/null || echo .)" 2>/dev/null && pwd)" ] && basename "$(CURDIR)" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9_.-]/-/g')
TAG ?= $(if $(WORKTREE),wt-$(WORKTREE),local)
export TAG
SUFFIXE := $(if $(WORKTREE),-$(WORKTREE))
help:
	@printf '%s\n' 'make init            Initialiser la configuration locale' 'make up              Construire et lancer les services' 'make user            Créer un compte' 'make reset-password  Réinitialiser un mot de passe' 'make recherche-web   Ouvrir ou fermer la recherche web à un compte' 'make backup          Sauvegarder PostgreSQL' 'make down            Arrêter sans effacer les données' 'make logs            Suivre les logs' 'make test            Tests Rust et intégration' 'make clean-worktree  Dans un worktree : effacer ses images et son cache Rust'
init:
	python3 scripts/init_env.py
build: init
	docker compose build
up: depot-principal init
	docker compose up -d --build --remove-orphans
down: depot-principal
	docker compose down
restart: depot-principal init
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
	docker run --rm --network none --read-only --tmpfs /tmp:size=4m observatoire-orchestrateur:$(TAG) python -m unittest discover -s tests
	docker build -q -t observatoire-recherche-service:$(TAG) recherche/service >/dev/null
	docker build -q -t observatoire-recherche:$(TAG) recherche/outil >/dev/null
	docker run --rm --network none --read-only --tmpfs /tmp:size=4m observatoire-recherche-service:$(TAG) python -m unittest discover -s tests
	docker run --rm --network none --read-only --tmpfs /tmp:size=4m observatoire-recherche:$(TAG) python -m unittest discover -s tests
test: test-frontend test-recherche
	docker run --rm -v "$(CURDIR)/backend:/app" -v observatoire-cargo-registry:/usr/local/cargo/registry -v observatoire-cargo-target$(SUFFIXE):/app/target -w /app rust:1-slim-trixie cargo test --locked
	docker run --rm -v "$(CURDIR)/image-guard:/app" -v observatoire-cargo-registry:/usr/local/cargo/registry -v observatoire-guard-target$(SUFFIXE):/app/target -w /app rust:1-slim-trixie cargo test --locked
	docker run --rm -v "$(CURDIR)/doc-guard:/t:ro" -w /t -e PYTHONDONTWRITEBYTECODE=1 observatoire-doc-guard:$(TAG) python -m unittest test_lecteur
	python3 tests/integration/run.py
# La pile de dev a un nom, un port et une base fixes : la lancer depuis un worktree remplacerait celle du dépôt principal.
depot-principal:
	@if [ -n "$(WORKTREE)" ]; then echo "Worktree « $(WORKTREE) » : make build et make test seulement. La pile se lance depuis le dépôt principal, après fusion." >&2; exit 1; fi
clean-worktree:
	@if [ -z "$(WORKTREE)" ]; then echo "À lancer dans un worktree (rien à effacer ici)." >&2; exit 1; fi
	docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^observatoire-[a-z-]+:$(TAG)$$' | xargs -r docker rmi
	docker volume rm observatoire-cargo-target$(SUFFIXE) observatoire-guard-target$(SUFFIXE) 2>/dev/null || true
