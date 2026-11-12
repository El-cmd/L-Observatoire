"""Qualité des passages de la recherche multi-sources : règles visibles, sans modèle.

- lignes parasites (notifications, menus, partage, abonnement, bandeaux) retirées des pages, et comptées ;
- passages pauvres en vraies phrases (listes de liens, menus restants) pénalisés ;
- pages incomplètes (mur payant, CAPTCHA, page de blocage, texte trop court) repérées, pour être remplacées ;
- fautes de la question corrigées d'après le vocabulaire des pages lues (« rinner » → « riner »), corrections affichées ;
- passages presque identiques repérés par suites de 5 mots (« shingles ») : même site écarté, autre site cité en appui.
"""
import re
import unicodedata

# Lignes courtes reconnues comme de l'interface de site, pas du contenu.
PARASITES = [
    r"afficher toutes les notifications", r"\bnotifications?\b", r"fermer (le menu|la fen[eê]tre)?$", r"^voir plus\b", r"^lire (aussi|la suite)\b",
    r"ajoutez .{0,40} [àa] vos sources", r"suivez la couverture", r"abonnez-vous", r"\bs['’]abonner\b", r"newsletter", r"inscrivez-vous",
    r"se connecter", r"mon compte", r"cr[ée]er un compte", r"t[ée]l[ée]charger l['’]application", r"partager (sur|la page|cet article)",
    r"copier le lien", r"lien copi[ée]", r"ajouter [àa] mes favoris", r"retour en haut", r"aller au contenu", r"^publicit[ée]$",
    r"^(facebook|linkedin|twitter|x|bluesky|whatsapp|instagram|youtube|courriel|e-mail|imprimer)\b", r"\(nouvelle fen[eê]tre\)",
    r"accepter (et fermer|tout)", r"tout refuser", r"param[eé]trer (les )?cookies", r"g[ée]rer (mes|les) (cookies|choix)",
    r"r[ée]agir$", r"^\d+ commentaires?$", r"privil[ée]gier l['’]affichage", r"^menu$", r"^rechercher$", r"^accueil$",
]
_PARASITE = re.compile("|".join(PARASITES), re.IGNORECASE)
PARASITE_MOTS_MAX = 14            # une ligne plus longue est gardée même si elle contient un de ces mots

# Pages incomplètes. Marques sûres : comptent partout. Marques ambiguës (une page libre peut afficher « réservé aux
# abonnés » sur ses liens vers d'autres articles, ou parler d'« accès refusé ») : seulement si la page est courte.
MARQUES_SURES = [
    (r"il vous reste \d+(?:[.,]\d+)? ?% de (cet|l['’])article", "article coupé, suite réservée aux abonnés"),
    (r"la suite (de cet article )?est r[ée]serv[ée]e", "article coupé, suite réservée aux abonnés"),
    (r"abonnez-vous pour (lire|continuer|acc[ée]der)", "article réservé aux abonnés"),
    (r"subscribe to (continue|keep) reading|to continue reading,? (please )?subscribe", "article réservé aux abonnés"),
    (r"just a moment\.\.\.|checking (if the site connection is secure|your browser)", "page de blocage anti-robot"),
    (r"enable javascript and cookies to continue", "page de blocage anti-robot"),
]
MARQUES_SI_COURT = [
    (r"r[ée]serv[ée]e? (aux|à nos) abonn[ée]s", "réservé aux abonnés"), (r"\bcaptcha\b", "CAPTCHA"),
    (r"v[ée]rifi(ez|cation) que vous (n['’][êe]tes pas un robot|[êe]tes (un )?humain)", "CAPTCHA"),
    (r"are you a robot|verify you are human", "CAPTCHA"), (r"\baccess denied\b|acc[eè]s refus[ée]", "page de blocage"),
]
COURT = 3000                      # caractères de phrases : en dessous, les marques ambiguës comptent
TEXTE_MIN = 400                   # caractères de phrases en dessous desquels une page n'a pas de contenu (pages
                                  # officielles courtes mais utiles, ex. « carte Vitale » d'ameli.fr : 516)
PHRASE_MOTS_MIN = 8
PART_PHRASES_MIN = 0.35           # part du texte d'un passage faite de vraies phrases ; en dessous, pénalité
PENALITE_PEU_DE_PHRASES = 0.5
SHINGLE = 5
QUASI_IDENTIQUE = 0.5             # part de suites de 5 mots communes (Jaccard) à partir de laquelle deux passages se répètent


def _plat(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texte.lower()) if not unicodedata.combining(c))


def nettoyer(texte: str) -> tuple[str, int]:
    """Retire les lignes courtes reconnues comme de l'interface de site. Rend le texte et le nombre de lignes retirées."""
    gardees, retirees = [], 0
    for ligne in texte.splitlines():
        propre = re.sub(r"^[\s*#>|\-•]+", "", ligne).strip()
        if propre and len(propre.split()) <= PARASITE_MOTS_MAX and _PARASITE.search(propre):
            retirees += 1
            continue
        gardees.append(ligne)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(gardees)).strip(), retirees


def part_phrases(texte: str) -> float:
    """Part des caractères du passage qui sont dans de vraies phrases (au moins 8 mots), titres et tableaux exclus."""
    lignes = [l.strip() for l in texte.splitlines() if l.strip() and not l.strip().startswith(("#", "|"))]
    total = sum(len(l) for l in lignes)
    if not total:
        return 1.0                                   # titre seul ou tableau : jugé ailleurs
    phrases = sum(len(l) for l in lignes if _phrase(l))
    return phrases / total


def _phrase(ligne: str) -> bool:
    """Vraie phrase : au moins 8 mots, dont moins de la moitié commencent par une majuscule (un menu en enfilade,
    « Accessibilité Vidéo Podcasts Jeux Journal », n'en est pas une)."""
    mots = re.sub(r"^[*\-•\d.)\s]+", "", ligne).split()
    if len(mots) < PHRASE_MOTS_MIN:
        return False
    majuscules = sum(1 for m in mots if m[:1].isupper())
    return majuscules < 0.5 * len(mots)


def incomplete(brut: str, net: str) -> str | None:
    """Raison pour laquelle la page n'est pas un article complet, ou None. Marques cherchées dans le texte avant
    nettoyage (« abonnez-vous » est aussi une ligne parasite) ; longueur mesurée après."""
    utile = sum(len(l) for l in net.splitlines() if len(l.split()) >= PHRASE_MOTS_MIN)
    for motifs in (MARQUES_SURES, MARQUES_SI_COURT if utile < COURT else []):
        for motif, raison in motifs:
            trouve = re.search(motif, brut, re.IGNORECASE)
            if trouve:
                return f"{raison} (« {trouve.group(0)[:60]} »)"
    if utile < TEXTE_MIN:
        return f"texte trop court pour un article ({utile} caractères de phrases)"
    return None


def _levenshtein(a: str, b: str, maximum: int) -> int:
    if abs(len(a) - len(b)) > maximum:
        return maximum + 1
    precedente = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        ligne = [i]
        for j, cb in enumerate(b, 1):
            ligne.append(min(precedente[j] + 1, ligne[j - 1] + 1, precedente[j - 1] + (ca != cb)))
        if min(ligne) > maximum:
            return maximum + 1
        precedente = ligne
    return precedente[-1]


def corrections(requete_mots: list[str], textes: list[str], mots_vides: set) -> dict[str, str]:
    """Mots de la question absents des pages, remplacés par le mot des pages le plus proche (1 lettre d'écart jusqu'à
    6 lettres, 2 au-delà) et fréquent (au moins 2 fois) : {mot de la question: mot des pages}. Rien n'est inventé."""
    frequences = {}
    for texte in textes:
        for mot in re.findall(r"[a-z0-9]+", _plat(texte)):
            if len(mot) >= 4:
                frequences[mot] = frequences.get(mot, 0) + 1
    sortie = {}
    for mot in requete_mots:
        plat = _plat(mot)
        if len(plat) < 4 or plat in mots_vides or frequences.get(plat, 0) >= 2:
            continue
        ecart_max = 1 if len(plat) <= 6 else 2
        meilleurs = sorted((d, -n, candidat) for candidat, n in frequences.items() if n >= 2
                           for d in [_levenshtein(plat, candidat, ecart_max)] if 0 < d <= ecart_max)
        if meilleurs:
            sortie[mot] = meilleurs[0][2]
    return sortie


def suites(texte: str) -> set:
    mots = re.findall(r"[a-z0-9]+", _plat(texte))
    return {" ".join(mots[i:i + SHINGLE]) for i in range(max(0, len(mots) - SHINGLE + 1))}


def proximite(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0
