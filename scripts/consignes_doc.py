"""Écrit docs/consignes-systeme.md : toutes les consignes des modèles, lues dans les fichiers sources.
Usage : python3 scripts/consignes_doc.py . > docs/consignes-systeme.md"""
import re, sys, tomllib
from pathlib import Path
R = Path(sys.argv[1])

def rust_const(path, name):
    s = (R / path).read_text()
    m = re.search(r'const ' + name + r': &str = r#"(.*?)"#;', s, re.S)
    if m: return m.group(1).strip()
    m = re.search(r'const ' + name + r': &str = "((?:[^"\\]|\\.)*)";', s, re.S)
    return m.group(1).replace('\\"', '"').replace('\\n', '\n').strip()

def rust_inline(path, start):
    s = (R / path).read_text()
    i = s.index(start)
    m = re.match(r'"((?:[^"\\]|\\.)*)"', s[i:])
    return m.group(1).replace('\\"', '"').strip()

def py_const(path, name):
    s = (R / path).read_text()
    m = re.search(r'^' + name + r' = \((.*?)\)\n', s, re.S | re.M) or re.search(r'^' + name + r" = ('(?:[^'\\]|\\.)*')\n", s, re.M)
    return ''.join(re.findall(r"'((?:[^'\\]|\\.)*)'", m.group(1)))

orch = tomllib.loads((R / 'orchestrateur/consignes.toml').read_text())
rech = tomllib.loads((R / 'recherche/outil/consignes/prompts.toml').read_text())
def bloc(t): return '```text\n' + t.strip() + '\n```\n'

# Repères de la recherche, montrés tels quels puis définis une fois.
out = []
w = out.append
w("""# Consignes données aux modèles de L’Observatoire

Toutes les consignes (« prompts système ») envoyées à Qwen et au modèle d’images, rangées par fonctionnalité.
Généré depuis les fichiers sources par `python3 scripts/consignes_doc.py . > docs/consignes-systeme.md` (à relancer après un changement de consigne) : en cas de doute, c’est le fichier indiqué qui fait foi.

- **Système** : message `system` en tête de la conversation envoyée au modèle.
- **Utilisateur** : la consigne est dans le message `user`, avec une image (le modèle multimodal la lit avec).
- **Outil** : description d’un outil MCP, lue par Qwen pour décider de l’appeler.

Le chat ordinaire (bouton Web éteint, chat éphémère compris) n’a **aucune** consigne système : Qwen reçoit la conversation seule,
plus la mémoire résumée quand elle existe.

## Carte

```mermaid
flowchart TB
    subgraph CHAT["Chat"]
        direction LR
        C0([Message]) -->|sans consigne| CQ[(Qwen)]
        C0 -->|1er message| C1[Titre<br/>TITLE_PROMPT]:::sys
        C0 -->|mémoire pleine| C2[Transcription des images<br/>TRANSCRIBE_PROMPT]:::usr
        C2 --> C3[Résumé<br/>mémoire compacte]:::sys
        C3 -->|ensuite, en tête| C4[Préfixe de mémoire<br/>MEMORY_PREFIX]:::sys
    end

    subgraph WEB["Bouton Web : orchestrateur"]
        direction LR
        W0([Message avec Web]) --> W1[outils<br/>+ outil_impose si profondeur choisie]:::sys
        W1 --> W2[[recherche_web]]:::outil
        W1 --> W3[[lire_page]]:::outil
        W3 --> W4[outil_resultat]:::sys
        W1 -->|outil en échec| W5[outil_echec]:::sys
    end

    subgraph RECH["Recherche (recherche_web)"]
        direction LR
        R0{aiguillage<br/>Automatique}:::sys -->|direct| R1[direct]:::sys
        R0 -->|web| R2[plan → redaction_web]:::sys
        R0 -->|approfondie| R3[plan → lecture →<br/>verification → redaction]:::sys
        R0 -->|tres_approfondie| R4[cahier → lecture → superviseur →<br/>compression → section → synthese]:::sys
        R0 -. si ambigu .-> R5[clarification]:::sys
        R2 & R3 & R4 -. filtre actif .-> R6[plan_filtre]:::sys
    end

    subgraph DOCS["Documents (bouton +)"]
        direction LR
        D0([Fichier]) -->|page de PDF avec texte| D1[Structure<br/>ANNOTATE]:::usr
        D0 -->|page scannée| D2[Transcription<br/>READ]:::usr
    end

    subgraph IMG["Onglet Images"]
        direction LR
        I0([Description]) -->|Améliorer| I1[IMPROVE<br/>+ règle du style]:::sys
        I3([Créer un style]) -->|Proposer les mots| I2[SUGGEST]:::sys
        I2 -->|Enregistrer| I5[Sujet de l’exemple<br/>EXAMPLE_SCENE]:::sys
        I5 --> I4
        I0 -->|Créer| I4[(qwen-image-turbo<br/>description + Style: mots)]
        I1 --> I4
        I6([Image de départ]) -->|Améliorer| I7[IMPROVE_FROM_IMAGE<br/>+ image + règle du style]:::sys
        I6 -->|Transformer + force| I4
        I6 -->|Retoucher| I8[EDIT_INSTRUCTION<br/>+ image]:::sys
        I8 -->|sans force ni style| I4
        I7 --> I4
    end

    subgraph EVAL["Évaluation du labo (make evaluer)"]
        direction LR
        E1[eval_generation → eval_qualite<br/>→ eval_citations]:::sys
    end

    W2 --> R0

    classDef sys fill:#e8f0ff,stroke:#5b7bd5,color:#111
    classDef usr fill:#fff3df,stroke:#d59a3b,color:#111
    classDef outil fill:#e9f8ec,stroke:#3e9b57,color:#111
```

Légende : bleu = consigne **système**, orange = consigne dans le message **utilisateur** (avec une image), vert = description d’**outil**.

""")

w("## 1. Chat\n\n")
w("### Titre de conversation — Système\n\nAprès la première question. `backend/src/chat.rs` (`TITLE_PROMPT`).\n\n" + bloc(rust_const('backend/src/chat.rs', 'TITLE_PROMPT')))
w("### Mémoire compacte (résumé) — Système\n\nQuand la jauge de mémoire est pleine, les anciens échanges sont résumés. `backend/src/context.rs`.\n\n" + bloc(rust_inline('backend/src/context.rs', '"Tu rédiges la mémoire compacte')))
w("### Préfixe de mémoire — Système\n\nPlacé en tête des conversations résumées, suivi du résumé. `backend/src/context.rs` (`MEMORY_PREFIX`).\n\n" + bloc(rust_const('backend/src/context.rs', 'MEMORY_PREFIX')))
w("### Transcription d’une image pour la mémoire — Utilisateur\n\nAvant le résumé, chaque image des anciens messages est mise en texte. `backend/src/attachments.rs` (`TRANSCRIBE_PROMPT`).\n\n" + bloc(rust_const('backend/src/attachments.rs', 'TRANSCRIBE_PROMPT')))

w("## 2. Bouton Web : orchestrateur\n\nFichier `orchestrateur/consignes.toml`, relu à chaque message. `{jour}` devient la date du jour (heure de Paris).\n\n")
for k, titre, quand in (('outils', 'Outils proposés', 'En tête de la conversation dès que le bouton Web est activé.'),
                        ('outil_impose', 'Outil imposé', 'Ajouté à la précédente quand une profondeur précise est choisie dans le menu du bouton Web.'),
                        ('outil_resultat', 'Résultat d’outil à reprendre', 'Jointe au texte rendu par `lire_page`.'),
                        ('outil_echec', 'Outil en échec', 'Quand la recherche est indisponible ou a échoué.')):
    w(f"### {titre} (`{k}`) — Système\n\n{quand}\n\n" + bloc(orch[k]))

w("### Descriptions des outils — Outil\n\n`recherche/outil/serveur.py`.\n\n")
w("**recherche_web**\n\n" + bloc(py_const('recherche/outil/serveur.py', 'DESCRIPTION')))
w("Paramètre `question` :\n\n" + bloc(py_const('recherche/outil/serveur.py', 'QUESTION')))
w("Paramètre `profondeur` :\n\n" + bloc(py_const('recherche/outil/serveur.py', 'PROFONDEUR')))
w("**lire_page**\n\n" + bloc(py_const('recherche/outil/serveur.py', 'DESCRIPTION_PAGE')))
w("Paramètre `url` :\n\n" + bloc(py_const('recherche/outil/serveur.py', 'URL_PAGE')))
w("Paramètre `question` :\n\n" + bloc(py_const('recherche/outil/serveur.py', 'QUESTION_PAGE')))

w("## 3. Recherche sur Internet (outil recherche_web)\n\nFichier `recherche/outil/consignes/prompts.toml`, relu à chaque recherche. Les repères `{date}`, `{donnees}`, `{citer}` et `{rediger}` sont remplacés par les blocs ci-dessous.\n\n")
w("### Blocs communs\n\n")
for k in ('date', 'donnees', 'citer', 'rediger'):
    w(f"**`{{{k}}}`**\n\n" + bloc(rech[k]))
groupes = (
    ('Mode Automatique et précision', (('aiguillage', 'Choix du mode, avant toute recherche.'), ('clarification', 'Ajoutée quand Qwen peut demander une précision.'), ('direct', 'Réponse sans recherche.'))),
    ('Modes Rapide (web) et Approfondie', (('plan', 'Requêtes de la première recherche.'), ('plan_filtre', 'Ajoutée quand le filtre des données personnelles est actif.'),
        ('lecture', 'Extraction des faits de chaque lot de passages (Approfondie et Très approfondie).'), ('verification', 'Répondre ou chercher encore (Approfondie).'),
        ('redaction', 'Rédaction du mode Approfondie.'), ('redaction_web', 'Rédaction du mode Rapide.'))),
    ('Mode Très approfondie', (('cahier', 'Cahier de recherche : objectif, sous-questions, critères.'), ('superviseur', 'Couverture des sous-questions, relances.'),
        ('compression', 'Faits d’une sous-question rangés en notes.'), ('section', 'Une section du rapport par sous-question.'), ('synthese', 'Synthèse en tête du rapport.'))),
    ('Évaluation (labo, make evaluer)', (('eval_generation', 'Questions de test.'), ('eval_qualite', 'Note de qualité d’une réponse.'), ('eval_citations', 'Vérification des citations.'))),
)
for titre, items in groupes:
    w(f"### {titre}\n\n")
    for k, quand in items:
        w(f"**`{k}`** — Système. {quand}\n\n" + bloc(rech[k]))

w("## 4. Documents (bouton +)\n\n`backend/src/documents.rs`. Chaque page est envoyée en image avec la consigne.\n\n")
w("### Page scannée ou manuscrite (`READ`) — Utilisateur\n\n" + bloc(rust_const('backend/src/documents.rs', 'READ')))
w("### Structure d’une page de PDF (`ANNOTATE`) — Utilisateur\n\nSuivie de la liste numérotée des segments de texte de la page ; réponse en JSON.\n\n" + bloc(rust_const('backend/src/documents.rs', 'ANNOTATE')))

imp = rust_const('backend/src/creation.rs', 'IMPROVE')
w("## 5. Onglet Images\n\n`backend/src/creation.rs`.\n\n")
w("### Améliorer la description (`IMPROVE`) — Système\n\n`{style}` devient l’une des deux règles ci-dessous.\n\n" + bloc(imp))
w("Avec un style qui a des mots :\n\n" + bloc('The style "{name}" ({words}) is added separately after your prompt: describe the scene so it fits this style, but do not name another style or medium.'))
w("Avec le style « Aucun » :\n\n" + bloc('You may suggest an appropriate visual style or medium if the idea calls for one.'))
w("### Améliorer la description d’une image → image (`IMPROVE_FROM_IMAGE`) — Système\n\nAvec une image de départ, Qwen reçoit la description de l’utilisateur et la miniature de l’image (640 px, JPEG). `{style}` devient les mêmes règles que ci-dessus.\n\n" + bloc(rust_const('backend/src/creation.rs', 'IMPROVE_FROM_IMAGE')))
w("### Consigne d’une retouche (`EDIT_INSTRUCTION`) — Système\n\nMode « Retoucher » : Qwen reçoit la demande de l’utilisateur et la miniature de l’image, et écrit une consigne courte. Le modèle d’images la reçoit sans mots de style ni force (modification par référence : seul le changement demandé est fait).\n\n" + bloc(rust_const('backend/src/creation.rs', 'EDIT_INSTRUCTION')))
w("### Proposer les mots d’un style (`SUGGEST`) — Système\n\nBouton « Proposer les mots » de la fenêtre « Créer un style ».\n\n" + bloc(rust_const('backend/src/creation.rs', 'SUGGEST')))
w("### Ce que reçoit le modèle d’images\n\nPas de consigne système : la description (ou sa version améliorée), puis les mots du style. En image → image, la même chose, avec l’image de départ et la force (Fidèle 0,625, Équilibré 0,75, Libre 0,875) :\n\n" + bloc("<description>\n\nStyle: <mots du style>."))
w("### Sujet de l’image d’exemple d’un style (`EXAMPLE_SCENE`) — Système\n\nÀ l’enregistrement d’un style de « Mes styles », Qwen reçoit ses mots. S’ils nomment un personnage ou un univers, il propose une scène qui le montre ; sinon l’exemple garde le sujet habituel.\n\n" + bloc(rust_const('backend/src/creation.rs', 'EXAMPLE_SCENE')))
w("Sujet habituel, avec la graine 42, pour comparer les styles entre eux (`EXAMPLE_SUBJECT`) :\n\n" + bloc(rust_const('backend/src/creation.rs', 'EXAMPLE_SUBJECT')))
w("Les mots des 15 styles fournis sont dans `STYLES`, au début de `backend/src/creation.rs`.\n")
print(''.join(out), end='')
