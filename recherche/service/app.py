"""web-search-service : seul point d'entrée du Labo recherche web vers SearXNG et Crawl4AI.

Appelé par l'agent du Labo recherche de L'Observatoire, sur le réseau Docker interne. Aucune fonction LLM.
Routes : GET /sante, POST /rechercher, POST /lire, POST /lire-page, POST /recherche-complete, POST /recherche-multi. Erreurs : {"erreur": {"code", "message"}}.
Journal : route, statut, durée et nombres seulement ; jamais la requête, l'adresse lue ni le contenu.
"""
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from importlib.metadata import version
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

import garde
from icones import Icones
import multi
import nettoyage
import qualite
from moteurs import RESULTATS_MAX, Crawl4ai, Indisponible, Searxng, maintenant

LECTURES_SIMULTANEES = 2
REQUETES_MAX = 3
EXCLURE_MAX = 50
SOURCES_COMPLETE = 3
ESSAIS_COMPLETE = 5
ICONES_DELAI = 3.0                 # attente au plus, après les lectures, des icônes encore en route

journal = logging.getLogger("web-search")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def cycle(app: FastAPI):
    # trust_env=False : le service parle aux moteurs sur le réseau interne, jamais par un proxy de l'environnement.
    client = httpx.AsyncClient(trust_env=False, follow_redirects=False, limits=httpx.Limits(max_connections=10))
    app.state.searxng = Searxng(os.environ.get("SEARXNG_URL", "http://searxng:8080"), client)
    # Icônes des sites et lecture simple des pages (sans navigateur) : par le proxy de sortie (SORTIE_PROXY), le seul
    # chemin de ce service vers Internet. Redirections suivies une à une, chaque adresse contrôlée (telechargement.py).
    proxy = os.environ.get("SORTIE_PROXY", "")
    sortie = httpx.AsyncClient(proxy=proxy, trust_env=False, follow_redirects=False) if proxy else None
    app.state.crawl4ai = Crawl4ai(os.environ.get("CRAWL4AI_URL", "http://crawl4ai:11235"), os.environ.get("CRAWL4AI_API_TOKEN", ""), client, sortie)
    app.state.lectures = asyncio.Semaphore(LECTURES_SIMULTANEES)
    app.state.icones = Icones(sortie)
    yield
    await client.aclose()
    if sortie is not None:
        await sortie.aclose()


app = FastAPI(title="web-search-service", docs_url=None, redoc_url=None, openapi_url=None, lifespan=cycle)


def erreur(statut: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"erreur": {"code": code, "message": message}}, status_code=statut)


@app.exception_handler(garde.Refus)
async def refus(_: Request, e: garde.Refus):
    return erreur(422 if e.code in ("donnees_personnelles", "url_refusee") else 400, e.code, e.message)


@app.exception_handler(Indisponible)
async def indisponible(_: Request, e: Indisponible):
    return erreur(e.statut, e.code, e.message)


@app.exception_handler(RequestValidationError)
async def invalide(_: Request, __: RequestValidationError):
    return erreur(400, "requete_invalide", "Requête illisible.")


@app.middleware("http")
async def journaliser(request: Request, suivant):
    debut = time.monotonic()
    reponse = await suivant(request)
    if request.url.path != "/sante" or reponse.status_code != 200:
        journal.info("route=%s statut=%s duree_ms=%d", request.url.path, reponse.status_code, (time.monotonic() - debut) * 1000)
    return reponse


async def corps(request: Request) -> dict:
    try:
        donnees = await request.json()
    except ValueError:
        raise garde.Refus("requete_invalide", "Requête illisible.")
    if not isinstance(donnees, dict):
        raise garde.Refus("requete_invalide", "Requête illisible.")
    return donnees


def limite(valeur) -> int:
    if valeur is None:
        return RESULTATS_MAX
    if not isinstance(valeur, int) or isinstance(valeur, bool) or not 1 <= valeur <= RESULTATS_MAX:
        raise garde.Refus("limite_invalide", f"Nombre de résultats entre 1 et {RESULTATS_MAX}.")
    return valeur


@app.get("/sante")
async def sante(request: Request):
    searxng, crawl4ai = await asyncio.gather(request.app.state.searxng.sante(), request.app.state.crawl4ai.sante())
    return {"searxng": searxng, "crawl4ai": crawl4ai, "limites": {"resultats": RESULTATS_MAX, "requete": garde.REQUETE_MAX,
            "lectures_simultanees": LECTURES_SIMULTANEES, "sources_recherche_complete": SOURCES_COMPLETE,
            "essais_recherche_complete": ESSAIS_COMPLETE},
            "versions": {"service": "1", "fastapi": version("fastapi"), "httpx": version("httpx")}}


def filtre_demande(donnees: dict) -> bool:
    """Filtre des données personnelles des requêtes : activé sauf demande explicite (« filtre »: false)."""
    filtre = donnees.get("filtre", True)
    if not isinstance(filtre, bool):
        raise garde.Refus("filtre_invalide", "Filtre : vrai ou faux.")
    return filtre


@app.post("/rechercher")
async def rechercher(request: Request):
    donnees = await corps(request)
    requete = garde.requete(donnees.get("requete"), filtre_demande(donnees))
    return await request.app.state.searxng.rechercher(requete, limite(donnees.get("limite")))


async def lecture(request: Request, url: str, requete: str = "") -> dict:
    async with request.app.state.lectures:
        return await request.app.state.crawl4ai.lire(url, requete)


def requete_bm25(valeur) -> str:
    """Recherche facultative pour la version BM25 : traitée sur le serveur seulement, jamais envoyée dehors."""
    if not isinstance(valeur, str):
        return ""
    valeur = " ".join(valeur.split())
    return valeur if 0 < len(valeur) <= garde.REQUETE_MAX else ""


@app.post("/lire")
async def lire(request: Request):
    donnees = await corps(request)
    url = garde.url_publique(donnees.get("url"))
    return await lecture(request, url, requete_bm25(donnees.get("requete")))


def texte_de(lue: dict) -> tuple[str | None, str]:
    """(version, texte) d'une page lue pour le modèle : « sans liens » dès qu'elle a un peu de texte (le brut garde menus,
    logos et liens), sinon la version recommandée, sinon le brut ; appels de note des wikis retirés."""
    versions = lue.get("versions") or {}
    if (versions.get("sans_liens") or {}).get("caracteres", 0) >= 200:
        version = "sans_liens"
    else:
        version = lue.get("recommandee") if lue.get("recommandee") in versions else None
    texte = versions[version]["texte"] if version else str(lue.get("markdown") or "")
    return version, nettoyage.sans_appels_de_note(texte)


@app.post("/lire-page")
async def lire_page(request: Request):
    """Une page donnée par l'utilisateur (outil lire_page), prête pour le modèle : texte nettoyé entier s'il tient dans
    le budget ; sinon, avec une question, les passages les plus proches d'elle (BM25) dans l'ordre de la page ; sans
    question, le début de la page. Avec l'icône du site, pour la liste des sources."""
    donnees = await corps(request)
    url = garde.url_publique(donnees.get("url"))
    question = requete_bm25(donnees.get("question"))
    budget = borne(donnees.get("budget"), multi.PAGE_BUDGET_DEFAUT, multi.BUDGET_MIN, multi.PAGE_BUDGET_MAX, "budget_invalide",
                   f"Budget entre {multi.BUDGET_MIN} et {multi.PAGE_BUDGET_MAX} jetons.")
    debut = time.monotonic()
    icone = asyncio.ensure_future(request.app.state.icones.pour(url))
    try:
        lue = await lecture(request, url, question)
    except BaseException:
        icone.cancel()
        raise
    sortie = {"url": url, "url_finale": lue.get("url_finale") or url, "date_consultation": lue.get("date_consultation") or maintenant(),
              "lecture": lue.get("lecture")}
    if not lue.get("succes"):
        icone.cancel()
        return {**sortie, "succes": False, "erreur": lue.get("erreur") or "La page n'a rien donné de lisible."}
    _, texte = texte_de(lue)
    texte, _ = multi.preparer(texte, True)
    page = await asyncio.to_thread(multi.extrait_page, texte, url, lue.get("titre") or "", question, budget)
    # Mur payant, CAPTCHA, page coupée : signalé au modèle (une page courte, elle, n'a rien d'anormal ici).
    raison = qualite.incomplete(str(lue.get("markdown") or "") + "\n" + texte, texte)
    if raison and raison.startswith("texte trop court"):
        raison = None
    try:
        sortie["icone"] = await asyncio.wait_for(asyncio.shield(icone), ICONES_DELAI)
    except Exception:   # noqa: BLE001 — délai dépassé ou échec : une icône manquante ne fait pas échouer la lecture
        sortie["icone"] = None
    return {**sortie, "succes": True, "titre": lue.get("titre") or "", "site": lue.get("site") or "",
            "description": lue.get("description") or "", **page,
            **({"avertissement": raison} if raison else {}), "duree_s": round(time.monotonic() - debut, 1)}


@app.post("/recherche-complete")
async def recherche_complete(request: Request):
    """Recherche, puis lecture dans l'ordre du moteur jusqu'à 3 pages lues, un site à la fois (pas de score inventé).

    Une page bloquée (anti-robot, erreur, délai) fait passer au résultat suivant : 5 lectures au plus. Toutes les pages
    essayées sont rendues, lues ou non, avec leur erreur.
    """
    donnees = await corps(request)
    requete = garde.requete(donnees.get("requete"))
    recherche = await request.app.state.searxng.rechercher(requete, RESULTATS_MAX)
    candidats, sites = [], set()
    for resultat in recherche["resultats"]:
        site = (urlsplit(resultat["url"]).hostname or "").removeprefix("www.")
        try:
            garde.url_publique(resultat["url"])
        except garde.Refus:
            continue
        if site not in sites:
            sites.add(site)
            candidats.append(resultat)

    async def une(resultat):
        try:
            return {**resultat, "lecture": await lecture(request, resultat["url"], requete)}
        except Indisponible as e:
            return {**resultat, "lecture": {"url": resultat["url"], "succes": False, "erreur": e.message, "code": e.code}}

    essayees, lues = [], 0
    while lues < SOURCES_COMPLETE and candidats and len(essayees) < ESSAIS_COMPLETE:
        lot = candidats[: min(LECTURES_SIMULTANEES, SOURCES_COMPLETE - lues, ESSAIS_COMPLETE - len(essayees))]
        candidats = candidats[len(lot):]
        for source in await asyncio.gather(*(une(r) for r in lot)):
            essayees.append(source)
            lues += bool(source["lecture"].get("succes"))
            if source["lecture"].get("code") == "crawl4ai_injoignable":
                candidats = []
    return {**recherche, "sources": essayees}


def borne(valeur, defaut: int, minimum: int, maximum: int, code: str, message: str) -> int:
    if valeur is None:
        return defaut
    if not isinstance(valeur, int) or isinstance(valeur, bool) or not minimum <= valeur <= maximum:
        raise garde.Refus(code, message)
    return valeur


@app.post("/recherche-multi")
async def recherche_multi(request: Request):
    """Recherche multi-sources sous budget de jetons (voir multi.py) : lit jusqu'à « pages » pages (un site à la fois,
    sources favorisées d'abord), découpe, classe tous les morceaux ensemble (BM25), garde les meilleurs
    sous le budget et rend le contexte final cité. Aucun LLM. Une page bloquée fait passer au résultat suivant
    (ESSAIS_EN_PLUS au plus) ; au-delà de DELAI_GLOBAL, les pages non lues sont ignorées et signalées."""
    donnees = await corps(request)
    filtre = filtre_demande(donnees)
    requete = garde.requete(donnees.get("requete"), filtre)
    budget = borne(donnees.get("budget"), multi.BUDGET_DEFAUT, multi.BUDGET_MIN, multi.BUDGET_MAX, "budget_invalide",
                   f"Budget entre {multi.BUDGET_MIN} et {multi.BUDGET_MAX} jetons.")
    nombre = borne(donnees.get("pages"), multi.PAGES_DEFAUT, multi.PAGES_MIN, multi.PAGES_MAX, "pages_invalide",
                   f"Nombre de pages entre {multi.PAGES_MIN} et {multi.PAGES_MAX}.")
    optimise = donnees.get("optimisations", True)
    if not isinstance(optimise, bool):
        raise garde.Refus("optimisations_invalide", "Optimisations : vrai ou faux.")
    # Recherche agentique (labo) : plusieurs requêtes SearXNG pour une même question (classement BM25 sur la question),
    # URL déjà lues exclues, texte complet des passages gardés rendu (« passages »).
    requetes = donnees.get("requetes")
    if requetes is None:
        requetes = [requete]
    elif not isinstance(requetes, list) or not 1 <= len(requetes) <= REQUETES_MAX:
        raise garde.Refus("requetes_invalides", f"De 1 à {REQUETES_MAX} requêtes.")
    else:
        requetes = list(dict.fromkeys(garde.requete(q, filtre) for q in requetes))
    exclure = donnees.get("exclure") or []
    if not isinstance(exclure, list) or len(exclure) > EXCLURE_MAX or not all(isinstance(u, str) for u in exclure):
        raise garde.Refus("exclure_invalide", f"Liste d'adresses à exclure : {EXCLURE_MAX} au plus.")
    exclure = set(exclure)
    avec_passages = donnees.get("passages", False)
    if not isinstance(avec_passages, bool):
        raise garde.Refus("passages_invalide", "Passages : vrai ou faux.")
    debut = time.monotonic()
    recherches = [await request.app.state.searxng.rechercher(q, RESULTATS_MAX) for q in requetes]
    # Résultats entrelacés (1er de chaque requête, puis 2e…), sans doublon d'adresse.
    fusion, vues = [], set()
    for rang in range(RESULTATS_MAX):
        for r in recherches:
            if rang < len(r["resultats"]):
                res = r["resultats"][rang]
                if res["url"] not in vues:
                    vues.add(res["url"])
                    fusion.append({**res, "position": len(fusion) + 1})
    recherche = {"resultats": fusion, "moteurs_muets": sorted({m for r in recherches for m in r["moteurs_muets"]})}
    candidats = []
    pertinents, hors_sujet = multi.pertinents(recherche["resultats"], [requete, *requetes])
    for r in multi.ordonner(pertinents):
        if r["url"] in exclure:
            continue
        try:
            garde.url_publique(r["url"])
            candidats.append(r)
        except garde.Refus:
            continue
    etats = {r["url"]: {"position": r["position"], "url": r["url"], "titre": r["titre"], "groupe": r["groupe"],
                        "libelle_groupe": multi.LIBELLE_GROUPE[r["groupe"]], "etat": "non_essayee"} for r in candidats}
    lues, en_cours, file, essais, arret = {}, {}, list(candidats), 0, False
    # Icônes des sites qui seront peut-être lus : demandées pendant les lectures (cache par domaine).
    icones_en_cours = {r["url"]: asyncio.ensure_future(request.app.state.icones.pour(r["url"]))
                       for r in candidats[:nombre + multi.ESSAIS_EN_PLUS]}

    async def une(r):
        try:
            return r, await lecture(request, r["url"], requete), None
        except Indisponible as e:
            return r, None, e

    while not arret and len(lues) < nombre and (file or en_cours):
        while file and len(en_cours) < LECTURES_SIMULTANEES and len(lues) + len(en_cours) < nombre and essais < nombre + multi.ESSAIS_EN_PLUS:
            r = file.pop(0)
            essais += 1
            etats[r["url"]]["etat"] = "en_cours"
            en_cours[asyncio.ensure_future(une(r))] = r
        if not en_cours:
            break
        reste = multi.DELAI_GLOBAL - (time.monotonic() - debut)
        finies, _ = await asyncio.wait(list(en_cours), timeout=max(0.0, reste), return_when=asyncio.FIRST_COMPLETED)
        if not finies:
            break
        for tache in finies:
            r = en_cours.pop(tache)
            _, lue, erreur = tache.result()
            etat = etats[r["url"]]
            if erreur is not None:
                etat.update(etat="erreur", erreur=erreur.message)
                if erreur.code in ("crawl4ai_injoignable", "jeton_refuse", "crawl4ai_sature"):
                    arret = True
            elif not lue.get("succes"):
                etat.update(etat="erreur", erreur=lue.get("erreur") or "Page non lue.")
            else:
                # Version « sans liens » dès qu'elle a un peu de texte (BM25 et la pertinence minimale écartent le reste),
                # même quand la lecture seule recommande le brut : le brut garde menus, logos et liens.
                version, texte = texte_de(lue)
                # Marques cherchées aussi dans le brut (le nettoyage peut retirer la ligne « il vous reste… »).
                raison = qualite.incomplete(str(lue.get("markdown") or "") + "\n" + texte, multi.preparer(texte, True)[0]) if optimise else None
                if raison:                                   # mur payant, CAPTCHA, page coupée : remplacée par la suivante
                    etat.update(etat="incomplete", erreur=raison, version=version or "brut", caracteres=len(texte))
                    continue
                etat.update(etat="lue", version=version or "brut", caracteres=len(texte), titre=lue.get("titre") or r["titre"],
                            site=lue.get("site") or "")
                lues[r["url"]] = {"url": r["url"], "titre": lue.get("titre") or r["titre"], "groupe": r["groupe"], "texte": texte,
                                  "date_consultation": lue.get("date_consultation") or maintenant()}
    for tache, r in en_cours.items():
        tache.cancel()
        etats[r["url"]].update(etat="delai", erreur=f"Lecture abandonnée : délai global de {int(multi.DELAI_GLOBAL)} s dépassé.")
    attendues = [icones_en_cours[u] for u in lues if u in icones_en_cours]
    if attendues:
        await asyncio.wait(attendues, timeout=ICONES_DELAI)
    for url, tache in icones_en_cours.items():
        if url in lues and tache.done() and not tache.cancelled() and tache.exception() is None and tache.result():
            etats[url]["icone"] = tache.result()
        elif not tache.done():
            tache.cancel()   # la demande elle-même continue et remplit le cache (asyncio.shield dans icones.py)
    # Numéros de source dans l'ordre des candidats (stable, indépendant de l'ordre de fin des lectures).
    pages_lues = []
    for r in candidats:
        if r["url"] in lues:
            lues[r["url"]]["numero"] = len(pages_lues) + 1
            etats[r["url"]]["numero"] = len(pages_lues) + 1
            pages_lues.append(lues[r["url"]])
    selection = await asyncio.to_thread(multi.selectionner, requete, pages_lues, budget, optimise,
                                        [q for q in requetes if q != requete])
    for page in etats.values():
        page["morceaux"] = sum(1 for m in selection["classement"] if m["url"] == page["url"]) if page["etat"] == "lue" else 0
        page["gardes"] = sum(1 for m in selection["classement"] if m["url"] == page["url"] and m["statut"] == "garde")
        page["lignes_parasites"] = selection["lignes_parasites"].get(page.get("numero"), 0)
    if len(pages_lues) < nombre:
        selection["avertissements"].insert(0, f"{len(pages_lues)} page(s) lue(s) sur {nombre} demandée(s).")
    if hors_sujet:
        selection["avertissements"].append(f"{len(hors_sujet)} résultat(s) hors sujet écarté(s) sans être lus "
                                           "(titre et extrait sans les mots de la question).")
    if avec_passages:
        selection["passages"] = [{"id": f"S{m['numero']}.{m['position']}", "numero": m["numero"], "url": m["url"], "titre": m["titre"],
                                  "section": m["section"], "position": m["position"], "jetons": m["jetons"], "texte": m["texte_complet"]}
                                 for m in selection.pop("_gardes")]
    else:
        selection.pop("_gardes", None)
    return {"requete": requete, "requetes": requetes, "budget": budget, "pages_demandees": nombre, "date": maintenant(),
            "pages": [etats[r["url"]] for r in candidats if etats[r["url"]]["etat"] != "non_essayee"],
            "moteurs_muets": recherche["moteurs_muets"], "duree_s": round(time.monotonic() - debut, 1), **selection}
