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
