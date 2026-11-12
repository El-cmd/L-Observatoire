"""Versions nettoyées du texte d'une page, pour comparer et préparer un futur RAG. Aucun modèle de langage.

Une seule lecture réseau ; les autres versions viennent du HTML déjà reçu, retraité par Crawl4AI (« raw: ») :
- brut         : Markdown de la page entière (lecture réseau) ;
- structure    : sans menus, en-têtes, pieds de page, barres latérales, formulaires ni bandeaux de cookies ;
- sans_liens   : la même, sans les adresses des liens ni les images (le texte des liens reste) — version recommandée ;
- pruning      : filtre natif PruningContentFilter (fit_markdown) ; peut retirer le texte de liens (« trous ») ;
- bm25         : passages proches de la recherche (BM25ContentFilter, sans modèle), si une recherche est donnée.
"""
import math
import re
from urllib.parse import urljoin

EXCLUS = ["nav", "header", "footer", "aside", "form", "script", "style", "noscript", "iframe", "svg"]
# Bandeaux de cookies courants (Orejime sur ameli.fr, tarteaucitron, Didomi, OneTrust, Axeptio, Cookiebot, Klaro…).
BANDEAUX = ("[class*=orejime], #orejime, #tarteaucitronRoot, #didomi-host, #onetrust-banner-sdk, #onetrust-consent-sdk, "
            "#axeptio_overlay, #CybotCookiebotDialog, #klaro, .klaro, #usercentrics-root, .cc-window, "
            "[id*=cookie], [class*=cookie], [id*=consent], [class*=consent]")
PRUNING = {"threshold": 0.48, "threshold_type": "dynamic", "min_word_threshold": 5}
BM25_SEUIL = 1.0
SANS_LIENS = {"ignore_links": True, "ignore_images": True}
CARACTERES_PAR_JETON = 4          # estimation pour le français ; pas de compteur exact sans le modèle
MINIMUM = 500                     # en dessous (ou sous 20 % du brut), la version recommandée retombe sur le brut
PART_MINIMUM = 0.20
LIENS_MAX = 200
HTML_MAX = 6 * 1024 * 1024        # Crawl4AI accepte 8 Mio par demande (config.yml)

LIBELLES = {
    "sans_liens": "Nettoyé, sans liens",
    "structure": "Nettoyé, avec liens",
    "bm25": "Passages pertinents (BM25)",
    "pruning": "Pruning (Crawl4AI)",
    "brut": "Brut",
}
ORDRE = ["sans_liens", "structure", "bm25", "pruning", "brut"]

_TROU = re.compile(r"(?<![\w’'])(?:du|de la|des|de|le|la|les|l’|l'|avec|voir|par|au|aux|un|une|en)\s+[.,;:)]", re.IGNORECASE)


def configuration_lecture() -> dict:
    """Lecture réseau : Markdown brut et, au passage, la version Pruning (même page, aucun appel de plus)."""
    return {"markdown_generator": {"type": "DefaultMarkdownGenerator", "params": {
        "content_filter": {"type": "PruningContentFilter", "params": PRUNING}}}}


def configuration_structure() -> dict:
    return {"excluded_tags": EXCLUS, "remove_forms": True, "excluded_selector": BANDEAUX}


def configuration_sans_liens(requete: str) -> dict:
    generateur = {"options": SANS_LIENS}
    if requete:
        generateur["content_filter"] = {"type": "BM25ContentFilter", "params": {"user_query": requete, "bm25_threshold": BM25_SEUIL, "language": "french"}}
    return {**configuration_structure(), "markdown_generator": {"type": "DefaultMarkdownGenerator", "params": generateur}}


def trous(texte: str) -> int:
    """Liens dont le texte a disparu (« voir . », « du . ») : estimation, pour le français."""
    return len(_TROU.findall(texte))


def version(texte: str, brut: str, maximum: int, trous_brut: int) -> dict:
    texte = texte.strip()
    n = len(texte)
    return {
        "texte": texte[:maximum],
        "caracteres": n,
        "jetons_estimes": math.ceil(n / CARACTERES_PAR_JETON),
        "reduction": round(100 * (1 - n / len(brut)), 1) if brut else 0.0,
        "trous": max(0, trous(texte) - trous_brut),
        "tronque": n > maximum,
    }


def liens(resultat: dict, base: str) -> list[dict]:
    """Liens du contenu (menus et pieds de page déjà retirés) : texte et adresse absolue (relative à la page), http(s), sans doublon."""
    vus, sortie = set(), []
    brut = resultat.get("links") if isinstance(resultat.get("links"), dict) else {}
    for genre in ("internal", "external"):
        for lien in brut.get(genre) or []:
            if not isinstance(lien, dict):
                continue
            url = str(lien.get("href") or "").strip()
            url = urljoin(base, url) if url and not url.startswith(("javascript:", "data:", "mailto:", "tel:", "#")) else ""
            if not re.match(r"https?://", url) or url in vus:
                continue
            vus.add(url)
            texte = " ".join(str(lien.get("text") or "").split())[:200]
            sortie.append({"texte": texte, "url": url[:2048], "externe": genre == "external"})
            if len(sortie) >= LIENS_MAX:
                return sortie
    return sortie


def assembler(brut: str, pruning: str, structure: str | None, sans_liens: str | None, bm25: str | None, maximum: int) -> dict:
    """Versions, statistiques, avertissements et version recommandée (repli sur le brut si le nettoyage vide la page)."""
    brut = brut.strip()
    base = trous(brut)
    versions = {"brut": version(brut, brut, maximum, base), "pruning": version(pruning, brut, maximum, base)}
    if structure is not None:
        versions["structure"] = version(structure, brut, maximum, base)
    if sans_liens is not None:
        versions["sans_liens"] = version(sans_liens, brut, maximum, base)
    if bm25 is not None:
        versions["bm25"] = version(bm25, brut, maximum, base)
    for nom, v in versions.items():
        v["libelle"] = LIBELLES[nom]
        if nom != "brut" and v["trous"]:
            v["avertissement"] = f"{v['trous']} lien(s) semblent avoir perdu leur texte : des mots manquent."
        elif nom == "bm25" and v["caracteres"] < 200:
            v["avertissement"] = "BM25 n'a presque rien gardé : page courte, ou recherche éloignée du contenu."
        elif nom != "brut" and v["caracteres"] == 0:
            v["avertissement"] = "Ce réglage n'a rien gardé."
    recommandee, repli = "brut", None
    candidate = versions.get("sans_liens")
    if candidate is not None:
        if candidate["caracteres"] >= MINIMUM and candidate["caracteres"] >= PART_MINIMUM * versions["brut"]["caracteres"]:
            recommandee = "sans_liens"
        else:
            repli = "Le nettoyage a retiré presque tout le texte : la version brute est proposée."
    return {"versions": {nom: versions[nom] for nom in ORDRE if nom in versions}, "recommandee": recommandee, "repli": repli,
            "caracteres_par_jeton": CARACTERES_PAR_JETON}

# Retraitement « raw: » : Crawl4AI prend « raw:<tout le HTML> » comme adresse de base des liens relatifs, et la recopie
# dans chaque lien du Markdown. Pour une page Wikipédia (milliers de liens, 1 à 2 Mo de HTML), la réponse dépassait
# 400 Mo et le service était tué faute de mémoire. Les liens sont donc rendus absolus avant l'envoi, avec la vraie adresse.
_ATTRIBUT = re.compile(r"""(\s(?:href|src)\s*=\s*)(?:(["'])(.*?)\2|([^\s"'>]+))""", re.IGNORECASE | re.DOTALL)
_SRCSET = re.compile(r"""\ssrcset\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""", re.IGNORECASE)
_SCHEMA = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def liens_absolus(html: str, base: str) -> str:
    """HTML dont les liens et images relatifs pointent vers des adresses complètes (srcset retirés)."""
    def absolu(m: re.Match) -> str:
        guillemet = m.group(2) or '"'
        valeur = (m.group(3) if m.group(2) else m.group(4)).strip()
        if not _SCHEMA.match(valeur):
            try:
                valeur = urljoin(base, valeur)
            except ValueError:
                valeur = ""
        return f"{m.group(1)}{guillemet}{valeur}{guillemet}"
    return _ATTRIBUT.sub(absolu, _SRCSET.sub("", html))


# Texte envoyé au modèle : les appels de note des wikis (« 1992.[12] », « feature,[a] », « [réf. nécessaire] ») ont la
# forme des citations de sources [n] que le modèle doit écrire ; il les recopiait comme des sources. Ils sont retirés, hors
# du code (où « tableau[0] » est du code). Quelques lignes de navigation des wikis partent aussi.
_APPEL_DE_NOTE = re.compile(r"(?<=[^\s\[(])\[(?:\d{1,3}|[a-z]{1,2}|[A-Z]|(?:note|Note|nb|N|n) ?\d{1,3}|réf\. (?:nécessaire|souhaitée)|"
                            r"citation needed|clarification needed|when\?|which\?|who\?|lien mort|archive)\]")
_CODE = re.compile(r"(```.*?```|`[^`\n]*`)", re.DOTALL)
_NAVIGATION = re.compile(r"^\s*(?:Jump to content|Aller au contenu|From Wikipedia, the free encyclopedia|Un article de Wikipédia, "
                         r"l'encyclopédie libre\.?|(?:show|hide)[A-Z][\w ]{0,40}|\[(?:modifier|edit)(?: \| modifier le code)?\])\s*$",
                         re.MULTILINE)


def sans_appels_de_note(texte: str) -> str:
    """Texte d'une page sans appels de note de wiki ni lignes de navigation, le code laissé intact."""
    morceaux = _CODE.split(texte)
    return "".join(m if i % 2 else _NAVIGATION.sub("", _APPEL_DE_NOTE.sub("", m)) for i, m in enumerate(morceaux))
