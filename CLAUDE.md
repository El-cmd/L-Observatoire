# L'Observatoire

## Nouveautés

Toute modification visible par les utilisateurs (nouvelle possibilité, amélioration, correction
qu'ils remarqueront) ajoute une entrée **en tête** de `NEWS` dans `frontend/src/lib/news.ts`, dans
le même commit. Les changements purement techniques (CI, déploiement, refactorisation) n'en ont pas.

- `id` : `AAAA-MM-JJ-mot-cle`, unique ; `date` : jour du déploiement.
- `level` : `major` (grosse nouveauté), `improvement` (quelque chose marche mieux), `fix` (souci réglé).
- `title` et `text` : en français simple, au vouvoiement, sans jargon (pas de « token », « API »,
  « backend »…). Dire ce que l'utilisateur peut faire et où cliquer.

Le point « non lu » réapparaît dès que la première entrée change.

## Worktrees (plusieurs agents en même temps)

Dans un worktree Git (`.claude/worktrees/<nom>`), le Makefile nomme les images `observatoire-*:wt-<nom>` et le cache
Rust `observatoire-cargo-target-<nom>` : chaque worktree teste son propre code sans gêner les autres.

- Dans un worktree : `make build` puis `make test` seulement (tests d'intégration :
  `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY make test` si le proxy du bureau est défini).
  `make up`, `restart` et `down` sont refusés : la pile de dev (nom, port 8080, base) appartient au dépôt principal.
- Travailler sur une branche, ne jamais pousser `main` ni déployer depuis un worktree. La fusion, le dernier
  `make test` et le déploiement se font depuis le dépôt principal.
- `frontend/src/lib/news.ts` : chaque branche ajoute son entrée en tête, d'où un conflit attendu à la fusion
  (garder les deux entrées, la plus récente en premier).
- Worktree terminé : `make clean-worktree` (efface ses images et son cache Rust), puis `git worktree remove`.
