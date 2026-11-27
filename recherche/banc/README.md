# Banc d'essai de la recherche web

Mesure la qualité du bouton Web de L'Observatoire (mode Automatique) sur des questions dont la réponse est connue.

- `questions.toml` : les questions, la réponse attendue (expressions régulières) et les domaines des sources officielles.
  Réponses vérifiées à la source le 26/11/2026 : à revoir quand elles changent (SMIC, plafonds, versions…).
- `banc.py` : pose chaque question à la version locale (ou `ORIGIN=…`), note la réponse sur 10, écrit les réponses et
  `resume.md` dans `resultats/<date>/` (non versionné).

Note sur 10 : réponse juste 5, source officielle citée 3, source officielle lue 1, réponse en moins de 60 s 1.

```sh
docker compose --profile recherche up -d          # la recherche web en local
python3 recherche/banc/banc.py <compte> <fichier du mot de passe> [id …]
```

Le compte doit avoir la recherche web (ouverte par défaut). Si le proxy du bureau est défini, lancer avec
`env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY`.

Les consignes de Qwen (`recherche/outil/consignes/prompts.toml`) sont relues à chaque recherche : ne pas les modifier
pendant un passage du banc.

## Mesures du 26/11/2026

| | Moyenne | Sous 9 |
|---|---|---|
| Avant (sources favorisées : wikis et développement seulement) | 8,2/10 | 6 questions sur 12 |
| Thèmes et sources officielles (`service/sources.toml`), requêtes `site:`, PDF lus par doc-guard, sites officiels proposés par Qwen | 10,0 puis 9,8/10 | 0 puis 1 |

Les 12 réponses étaient justes dès le départ : l'écart venait des sources. La question encore fragile (Coupe du monde)
dépend des moteurs : l'article officiel du résultat ne remonte pas à chaque fois.
