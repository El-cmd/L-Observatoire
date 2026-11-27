"""Lecture simple d'une page : un téléchargement du HTML par le proxy de sortie, sans navigateur.

Ouvrir chaque page dans le navigateur de Crawl4AI prenait de 5 à 18 s sur le serveur (mesuré le 15/11/2026) ; le même
HTML se télécharge en moins d'une seconde, et son nettoyage par Crawl4AI (« raw: », sans navigateur) prend 1 à 3 s.
Le navigateur ne sert plus qu'aux pages qui en ont besoin : refus du téléchargement simple (403 d'un anti-robot),
autre chose que du HTML, page trop lourde, ou presque aucun texte sans JavaScript (application web, page d'attente).

Sécurité : chaque adresse, redirections comprises, passe par garde.url_publique, et le proxy de sortie refuse toute
destination interne (il résout lui-même le nom et vérifie l'adresse obtenue). Taille bornée pendant la réception
(texte décompressé), délai total borné. Nom de robot honnête : Wikipédia refuse un faux navigateur, pas un robot qui
se présente.
"""
import asyncio
import re
from urllib.parse import urljoin

import httpx

import garde

AGENT = "LObservatoire/1.0 (+https://observatoire.vloth.tech)"
ENTETES = {"User-Agent": AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
           "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8", "Accept-Encoding": "gzip, deflate"}
DELAI = 10.0                     # téléchargement entier, redirections comprises
DELAI_CONNEXION = 5.0
REDIRECTIONS_MAX = 5
OCTETS_MAX = 6 * 1024 * 1024     # au-delà, le nettoyage « raw: » est refusé de toute façon (nettoyage.HTML_MAX)
TYPES = ("text/html", "application/xhtml+xml")
# PDF (barèmes officiels, notes de version…) : rendus tels quels, leur texte est lu par doc-guard (voir moteurs.py).
TYPES_PDF = ("application/pdf", "application/x-pdf")
TEXTE_MIN = 800                  # Markdown plus court : page probablement remplie par JavaScript
COURT = 5000                     # en dessous, une page qui demande JavaScript ou fait patienter est relue au navigateur
_JAVASCRIPT = re.compile(r"(enable|activer|activez|autoriser|autorisez)\s+(le\s+)?javascript|javascript\s+(is\s+)?(disabled|required|est\s+désactivé)|"
                         r"just a moment|checking your browser|vérification de (votre )?navigateur|attention required|"
                         r"verify you are (a )?human|vérifiez que vous (n'|n’)?êtes (pas )?(un robot|humain)", re.IGNORECASE)
_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([\w.:-]+)""", re.IGNORECASE)


class Pdf(bytes):
    """Contenu d'un PDF téléchargé (commence par %PDF), à faire lire par doc-guard."""


class Echec(Exception):
    """Téléchargement simple impossible ou insuffisant : la page sera lue par le navigateur."""

    def __init__(self, raison: str):
        super().__init__(raison)
        self.raison = raison


def _decoder(contenu: bytes, entete_type: str) -> str:
    """Texte du HTML : jeu de caractères de l'en-tête, sinon de la balise <meta>, sinon UTF-8 (caractères illisibles remplacés)."""
    m = re.search(r"charset\s*=\s*[\"']?([\w.:-]+)", entete_type, re.IGNORECASE)
    noms = [m.group(1)] if m else []
    if (meta := _CHARSET.search(contenu[:4096])) is not None:
        noms.append(meta.group(1).decode("ascii", "ignore"))
    for nom in [*noms, "utf-8"]:
        try:
            return contenu.decode(nom, errors="replace")
        except LookupError:
            continue
    return contenu.decode("utf-8", errors="replace")


async def _recevoir(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    for _ in range(REDIRECTIONS_MAX + 1):
        async with client.stream("GET", url, headers=ENTETES, timeout=httpx.Timeout(DELAI, connect=DELAI_CONNEXION)) as r:
            if r.status_code in (301, 302, 303, 307, 308):
                cible = r.headers.get("location", "")
                try:
                    url = garde.url_publique(urljoin(url, cible))
                except (garde.Refus, ValueError):
                    raise Echec("redirection vers une adresse refusée")
                continue
            if r.status_code != 200:
                raise Echec(f"statut HTTP {r.status_code}")
            genre = r.headers.get("content-type", "")
            nature = genre.split(";")[0].strip().lower()
            if nature not in TYPES and nature not in TYPES_PDF:
                raise Echec("pas une page HTML")
            if int(r.headers.get("content-length") or 0) > OCTETS_MAX:
                raise Echec("page trop lourde")
            morceaux, taille = [], 0
            async for morceau in r.aiter_bytes():
                taille += len(morceau)
                if taille > OCTETS_MAX:
                    raise Echec("page trop lourde")
                morceaux.append(morceau)
            contenu = b"".join(morceaux)
            if nature in TYPES_PDF:
                if not contenu.startswith(b"%PDF"):
                    raise Echec("PDF illisible")
                return Pdf(contenu), url
            return _decoder(contenu, genre), url
    raise Echec("trop de redirections")


async def telecharger(client: httpx.AsyncClient, url: str) -> tuple[str | Pdf, str]:
    """(HTML ou Pdf, adresse finale) de la page, ou Echec. `url` a déjà passé garde.url_publique."""
    try:
        return await asyncio.wait_for(_recevoir(client, url), DELAI)
    except TimeoutError:
        raise Echec("téléchargement trop lent")
    except httpx.HTTPError as e:
        raise Echec(f"téléchargement impossible ({type(e).__name__})")


def besoin_navigateur(markdown: str) -> str | None:
    """Raison de relire la page au navigateur d'après le texte obtenu sans lui ; None : le texte suffit."""
    texte = markdown.strip()
    if len(texte) < TEXTE_MIN:
        return "presque aucun texte sans JavaScript"
    if len(texte) < COURT and _JAVASCRIPT.search(texte):
        return "page qui demande JavaScript ou fait patienter"
    return None
