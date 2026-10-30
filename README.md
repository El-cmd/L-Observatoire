# L’Observatoire

L’Observatoire est une interface de chat en français pour `qwen3.8-27b-abliterated`, livrée avec Dockerfile, Docker Compose et Makefile. Les bibliothèques de rendu sont embarquées dans `public/vendor` (KaTeX et Highlight.js). Aucun paquet applicatif à installer : le backend utilise Python 3.11+ et sa bibliothèque standard ; le frontend utilise HTML, CSS et JavaScript.

## Démarrer avec Docker

Prérequis : Docker avec le plugin Compose, et Make.

```sh
cd chatbot_perso
make init
```

Renseigner `QWEN_BASE_URL` (adresse de votre API compatible, terminée par `/v1`) et `QWEN_API_KEY` dans `.env`, puis :

```sh
make up
```

Ouvrir **http://localhost:8080**. Par défaut, le port Docker est accessible uniquement depuis l’ordinateur local. `PORT` dans `.env` permet de choisir un autre port. Si le tunnel Cloudflare change, modifier `QWEN_BASE_URL`, en conservant le suffixe `/v1`, puis exécuter `make restart`.

La clé reste côté serveur. `.env` est exclu de Git et du contexte de construction Docker. Le modèle et l’adresse du serveur sont fixés par la configuration backend, pas par le navigateur.

## Commandes

| Commande | Action |
| --- | --- |
| `make up` | Construire et démarrer |
| `make down` | Arrêter le projet |
| `make restart` | Recréer le conteneur et relire `.env` |
| `make logs` | Suivre les logs |
| `make status` | Afficher l’état |
| `make dev` | Lancer avec Python, sans Docker |
| `make test` | Tests du proxy avec une API simulée |
| `make clean` | Supprimer le conteneur et l’image locale du projet |

`make dev` lit `.env` comme un fichier shell : entourer les valeurs contenant des espaces ou caractères spéciaux de guillemets simples. Sans Make : exporter les variables puis lancer `python3 server.py`.

## Fonctionnalités

- Interface sobre sur fond noir, avec conversations dans la barre latérale.
- Nouveau chat, navigation et suppression des conversations ; historique conservé dans ce navigateur.
- Réponses en streaming SSE, arrêt de génération et nouvelle tentative.
- Texte formaté, code coloré avec numéros de ligne et copie sans les numéros.
- Formules LaTeX rendues avec KaTeX : `$…$`, `$$…$$`, `\(…\)` et `\[…\]`.
- Interface adaptée aux mobiles ; Entrée envoie, Maj+Entrée ajoute une ligne.

Le bouton de réglages dans la saisie permet de choisir la température (0 à 2) et la réflexion (désactivée, légère, intermédiaire ou approfondie). Les réglages sont mémorisés dans ce navigateur et appliqués aux prochaines requêtes. Valeurs initiales : réflexion désactivée, température 0,7 ; limite de réponse de 4 096 tokens.

Les requêtes envoyées à Qwen contiennent l’historique du fil actif. Le raisonnement reçu n’est pas réinjecté dans l’historique transmis. Le chat gère les messages texte ; l’envoi d’images et d’audio n’est pas inclus. L’affichage Markdown couvre paragraphes, titres, listes, gras, blocs de code colorés et formules mathématiques ; le HTML du modèle est échappé.

## Configuration

| Variable | Valeur par défaut |
| --- | --- |
| `QWEN_BASE_URL` | `https://votre-api.example/v1` |
| `QWEN_API_KEY` | À renseigner |
| `QWEN_MODEL` | `qwen3.8-27b-abliterated` |
| `PORT` | `8080` |
| `CHAT_USER` | `vloth` |
| `CHAT_PASSWORD` | Vide : authentification HTTP désactivée |

Pour un accès réseau ultérieur, configurer `CHAT_PASSWORD` et placer le service derrière un proxy HTTPS. Le Compose livré reste lié à `127.0.0.1`. La configuration ne crée aucun compte utilisateur et les historiques ne sont pas synchronisés entre appareils.

Le contexte maximal côté Qwen est de 32 768 tokens. Le serveur Qwen signale un dépassement ; ouvrir un nouveau fil si nécessaire. Le raisonnement partage la limite de sortie avec la réponse finale. Après un arrêt, la fermeture du flux est demandée à l’API ; la libération immédiate du calcul dépend de cette API.

## Vérification

`make test` vérifie le transfert des paramètres, le streaming, les erreurs, le filtrage des origines et l’absence de clé dans les réponses. Les tests utilisent une API simulée et ne consomment pas de tokens Qwen.
