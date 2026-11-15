"""Clients de SearXNG et de Crawl4AI. Réponses normalisées ; aucun texte de requête ni adresse lue dans les journaux."""
import asyncio
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

import nettoyage

RESULTATS_MAX = 10
TITRE_MAX = 300
EXTRAIT_MAX = 600
CONTENU_MAX = 200_000
DELAI_RECHERCHE = 15.0
DELAI_LECTURE = 95.0          # Crawl4AI borne lui-même chaque lecture à 90 s
DELAI_SANTE = 3.0
DELAI_RETRAITEMENT = 30.0     # retraitement du HTML déjà reçu (« raw: »), sans réseau
DELAI_CONNEXION = 3.0       # réseau interne : un conteneur arrêté ne refuse pas, il ne répond plus
MEMOIRE_ETAT = 600            # un échec récent rend l'état « dégradé » pendant 10 min


class Indisponible(Exception):
    """Moteur injoignable, en erreur ou trop lent : statut HTTP et message à montrer."""

    def __init__(self, statut: int, code: str, message: str):
        super().__init__(message)
        self.statut = statut
        self.code = code
        self.message = message


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Etat:
    """Dernier échec du moteur lui-même (pas d'une page) : sert à l'état « dégradé »."""

    def __init__(self):
        self.echec = 0.0
        self.raison = ""

    def noter_echec(self, raison: str):
        self.echec, self.raison = time.monotonic(), raison

    def noter_succes(self):
        self.echec, self.raison = 0.0, ""

    def degrade(self) -> str | None:
        return self.raison if self.echec and time.monotonic() - self.echec < MEMOIRE_ETAT else None


def _texte(valeur, maximum: int) -> str:
    texte = " ".join(str(valeur or "").split())
    return texte if len(texte) <= maximum else texte[: maximum - 1] + "…"


# Écart minimal entre deux requêtes à SearXNG, toutes recherches confondues : chaque requête part vers tous les moteurs,
# et Brave ou DuckDuckGo refusent les rafales (une recherche très approfondie en envoyait une douzaine d'un coup).
INTERVALLE = float(os.environ.get("SEARXNG_INTERVALLE", "1.5"))


class Searxng:
    def __init__(self, url: str, client: httpx.AsyncClient):
        self.url = url.rstrip("/")
        self.client = client
        self.etat = Etat()
        self.intervalle = INTERVALLE
        self._rythme = asyncio.Lock()
        self._derniere = 0.0

    async def _a_son_tour(self):
        """Attend que l'écart minimal depuis la requête précédente soit passé (les requêtes partent une à une)."""
        async with self._rythme:
            attente = self._derniere + self.intervalle - time.monotonic()
            if attente > 0:
                await asyncio.sleep(attente)
            self._derniere = time.monotonic()

    async def sante(self) -> dict:
        try:
            r = await self.client.get(self.url + "/healthz", timeout=DELAI_SANTE)
            ok = r.status_code == 200
        except httpx.HTTPError:
            ok = False
        if not ok:
            return {"etat": "offline", "detail": "SearXNG ne répond pas."}
        raison = self.etat.degrade()
        return {"etat": "degraded", "detail": raison} if raison else {"etat": "online", "detail": "SearXNG répond."}

    async def rechercher(self, requete: str, limite: int) -> dict:
        await self._a_son_tour()
        try:
            r = await self.client.get(self.url + "/search", timeout=httpx.Timeout(DELAI_RECHERCHE, connect=DELAI_CONNEXION),
                                      params={"q": requete, "format": "json", "language": "fr-FR", "safesearch": 1, "pageno": 1})
        except httpx.ConnectTimeout:
            raise Indisponible(503, "searxng_injoignable", "SearXNG est injoignable.")
        except httpx.TimeoutException:
            self.etat.noter_echec("Dernière recherche trop lente.")
            raise Indisponible(504, "delai_depasse", "SearXNG n'a pas répondu à temps.")
        except httpx.HTTPError:
            raise Indisponible(503, "searxng_injoignable", "SearXNG est injoignable.")
        if r.status_code != 200:
            self.etat.noter_echec(f"Dernière recherche refusée (statut {r.status_code}).")
            raise Indisponible(502, "erreur_searxng", f"SearXNG a refusé la recherche (statut {r.status_code}).")
        try:
            corps = r.json()
            bruts = corps["results"]
        except (ValueError, KeyError, TypeError):
            self.etat.noter_echec("Dernière réponse illisible.")
            raise Indisponible(502, "reponse_invalide", "Réponse illisible de SearXNG.")
        resultats, vues = [], set()
        for brut in bruts if isinstance(bruts, list) else []:
            if not isinstance(brut, dict):
                continue
            url = str(brut.get("url") or "")
            if urlsplit(url).scheme not in ("http", "https") or url in vues:
                continue
            vues.add(url)
            moteurs = brut.get("engines") if isinstance(brut.get("engines"), list) else [brut.get("engine")]
            resultats.append({"position": len(resultats) + 1, "titre": _texte(brut.get("title") or url, TITRE_MAX), "url": url,
                              "extrait": _texte(brut.get("content"), EXTRAIT_MAX),
                              "moteurs": sorted({str(m) for m in moteurs if m})})
            if len(resultats) >= limite:
                break
        muets = sorted({str(m[0]) for m in corps.get("unresponsive_engines") or [] if isinstance(m, (list, tuple)) and m})
        if not resultats and muets:
            self.etat.noter_echec("Aucun moteur public n'a répondu à la dernière recherche.")
        else:
            self.etat.noter_succes()
        return {"resultats": resultats, "moteurs_muets": muets, "date": maintenant()}


class Crawl4ai:
    def __init__(self, url: str, jeton: str, client: httpx.AsyncClient):
        self.url = url.rstrip("/")
        self.jeton = jeton
        self.client = client
        self.etat = Etat()

    async def sante(self) -> dict:
        try:
            r = await self.client.get(self.url + "/health", timeout=DELAI_SANTE)
            ok = r.status_code == 200
        except httpx.HTTPError:
            ok = False
        if not ok:
            return {"etat": "offline", "detail": "Crawl4AI ne répond pas."}
        if not self.jeton:
            return {"etat": "degraded", "detail": "Jeton Crawl4AI absent."}
        raison = self.etat.degrade()
        return {"etat": "degraded", "detail": raison} if raison else {"etat": "online", "detail": "Crawl4AI répond."}

    async def _crawl(self, url: str, params: dict, delai: float) -> dict:
        """Un appel /crawl avec une configuration fixée par le service ; erreurs de Crawl4AI normalisées."""
        demande = {"urls": [url], "crawler_config": {"type": "CrawlerRunConfig", "params": {"cache_mode": "bypass", "stream": False, **params}}}
        try:
            r = await self.client.post(self.url + "/crawl", json=demande, timeout=httpx.Timeout(delai, connect=DELAI_CONNEXION),
                                       headers={"Authorization": "Bearer " + self.jeton})
        except httpx.ConnectTimeout:
            raise Indisponible(503, "crawl4ai_injoignable", "Crawl4AI est injoignable.")
        except httpx.TimeoutException:
            raise Indisponible(504, "delai_depasse", "Crawl4AI n'a pas lu la page à temps.")
        except httpx.HTTPError:
            raise Indisponible(503, "crawl4ai_injoignable", "Crawl4AI est injoignable.")
        if r.status_code in (400, 403) and "blocked" in r.text.lower():
            raise Indisponible(422, "url_refusee", "Page refusée par Crawl4AI : site introuvable, ou adresse interne.")
        if r.status_code == 401:
            self.etat.noter_echec("Jeton refusé par Crawl4AI.")
            raise Indisponible(502, "jeton_refuse", "Crawl4AI a refusé le jeton du service.")
        if r.status_code == 504:
            raise Indisponible(504, "delai_depasse", "La page n'a pas pu être lue à temps.")
        if r.status_code == 429:
            raise Indisponible(429, "crawl4ai_sature", "Trop de lectures de pages en ce moment sur le serveur : réessayez dans une minute.")
        if r.status_code != 200:
            if r.status_code >= 500:
                self.etat.noter_echec(f"Dernière lecture en erreur (statut {r.status_code}).")
            raise Indisponible(502, "erreur_crawl4ai", f"Crawl4AI n'a pas pu lire la page (statut {r.status_code}).")
        try:
            resultat = r.json()["results"][0]
            if not isinstance(resultat, dict):
                raise TypeError
        except (ValueError, KeyError, IndexError, TypeError):
            self.etat.noter_echec("Dernière réponse illisible.")
            raise Indisponible(502, "reponse_invalide", "Réponse illisible de Crawl4AI.")
        return resultat

    @staticmethod
    def _markdown(resultat: dict, champ: str = "raw_markdown") -> str:
        markdown = resultat.get("markdown")
        if isinstance(markdown, dict):
            return str(markdown.get(champ) or "")
        return str(markdown or "") if champ == "raw_markdown" else ""

    async def lire(self, url: str, requete: str = "") -> dict:
        """Texte de la page en plusieurs versions (voir nettoyage.py), métadonnées et date de consultation.

        Une seule lecture réseau ; les versions nettoyées viennent du HTML reçu, retraité par Crawl4AI (« raw: »).
        Configuration fixée ici : rien ne vient de l'appelant, sauf la recherche pour BM25 (texte, jamais envoyé dehors).
        """
        # Pas de remove_overlay_elements : il vide certaines pages (ameli.fr lue « script_heavy_shell », 0 caractère).
        date = maintenant()
        resultat = await self._crawl(url, {"page_timeout": 30000, "wait_until": "domcontentloaded", **nettoyage.configuration_lecture()}, DELAI_LECTURE)
        self.etat.noter_succes()
        markdown = self._markdown(resultat)
        meta = resultat.get("metadata") if isinstance(resultat.get("metadata"), dict) else {}
        lue = {
            "url": url,
            "url_finale": str(resultat.get("redirected_url") or resultat.get("url") or url),
            "succes": bool(resultat.get("success")) and bool(markdown.strip()),
            "statut_http": resultat.get("status_code"),
            "titre": _texte(meta.get("title") or meta.get("og:title"), TITRE_MAX),
            # Nom que le site se donne (« GitHub Docs », « Wikipédia ») : celui des puces de citation.
            "site": _texte(meta.get("og:site_name") or meta.get("application-name"), 60),
            "description": _texte(meta.get("description") or meta.get("og:description"), EXTRAIT_MAX),
            "langue": _texte(meta.get("language") or meta.get("lang"), 20),
            "markdown": markdown[:CONTENU_MAX],
            "caracteres": len(markdown),
            "tronque": len(markdown) > CONTENU_MAX,
            "date_consultation": date,
        }
        statut = lue["statut_http"]
        if lue["succes"] and isinstance(statut, int) and statut >= 400:
            lue["succes"] = False
            lue["erreur"] = f"Le site a répondu avec une erreur (statut HTTP {statut})."
        elif not lue["succes"]:
            lue["erreur"] = _texte(resultat.get("error_message") or "La page n'a rien donné de lisible.", 300)
        if not lue["succes"]:
            return lue
        # Versions nettoyées : HTML déjà reçu, retraité sans nouvelle connexion au site.
        structure = sans_liens = bm25 = None
        lue["liens"] = []
        html = nettoyage.liens_absolus(str(resultat.get("html") or ""), lue["url_finale"] or url)
        if html and len(html.encode()) <= nettoyage.HTML_MAX:
            try:
                r1 = await self._crawl("raw:" + html, nettoyage.configuration_structure(), DELAI_RETRAITEMENT)
                r2 = await self._crawl("raw:" + html, nettoyage.configuration_sans_liens(requete), DELAI_RETRAITEMENT)
                structure, sans_liens = self._markdown(r1), self._markdown(r2)
                bm25 = self._markdown(r2, "fit_markdown") if requete else None
                lue["liens"] = nettoyage.liens(r1, lue["url_finale"])
            except Indisponible as e:
                lue["nettoyage_erreur"] = "Versions nettoyées indisponibles : " + e.message
        else:
            lue["nettoyage_erreur"] = "Page trop lourde pour les versions nettoyées." if html else "HTML absent : versions nettoyées indisponibles."
        lue.update(nettoyage.assembler(markdown, self._markdown(resultat, "fit_markdown"), structure, sans_liens, bm25, CONTENU_MAX))
        return lue
