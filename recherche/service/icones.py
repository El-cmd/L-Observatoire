"""Icônes des sites lus (favicons), pour la liste des sources de la réponse.

L'icône d'un domaine vient du service d'icônes de DuckDuckGo (la meilleure icône connue du site), demandée par ce service
à travers le proxy de sortie, jamais par le navigateur de l'utilisateur (aucun tiers ne voit les sites consultés, et la
page n'accepte que ses propres images). L'image reçue (64 Ko au plus, formats matriciels seulement : jamais de SVG) est
redessinée en PNG de 32 × 32 et rendue en adresse « data: » de quelques Ko. Cache en mémoire par domaine (7 jours ;
1 jour pour un domaine sans icône).
"""
import asyncio
import base64
from collections import OrderedDict
import io
import re
import time
from urllib.parse import urlsplit

import httpx
from PIL import Image

SOURCE = "https://icons.duckduckgo.com/ip3/{domaine}.ico"
TAILLE = 32
OCTETS_MAX = 64 * 1024
PIXELS_MAX = 512 * 512
FORMATS = {"ICO", "PNG", "GIF", "JPEG", "WEBP", "BMP"}
DUREE, DUREE_ABSENTE = 7 * 24 * 3600.0, 24 * 3600.0
CACHE_MAX = 2000
DELAI = 4.0
DOMAINE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

Image.MAX_IMAGE_PIXELS = PIXELS_MAX


def domaine(url: str) -> str | None:
    """Domaine d'une adresse publique (sans « www. ») ; None pour une adresse IP ou un nom invalide."""
    hote = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    return hote if DOMAINE.match(hote) else None


def en_png(donnees: bytes) -> str | None:
    """Image reçue -> PNG 32 × 32 en adresse data: ; None si ce n'est pas une petite image matricielle lisible."""
    if not donnees or len(donnees) > OCTETS_MAX:
        return None
    try:
        with Image.open(io.BytesIO(donnees)) as image:
            if image.format not in FORMATS or image.width * image.height > PIXELS_MAX:
                return None
            if image.format == "ICO":   # plusieurs tailles dans un .ico : la plus proche de 32 px, au-dessus si possible
                tailles = sorted(image.info.get("sizes") or [image.size], key=lambda t: (t[0] < TAILLE, abs(t[0] - TAILLE)))
                image.size = tailles[0]
            image.load()
            dessin = image.convert("RGBA")
            dessin.thumbnail((TAILLE, TAILLE), Image.Resampling.LANCZOS)
            sortie = io.BytesIO()
            dessin.save(sortie, format="PNG", optimize=True)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None
    return "data:image/png;base64," + base64.b64encode(sortie.getvalue()).decode()


class Icones:
    def __init__(self, client: httpx.AsyncClient | None):
        self.client = client          # client passant par le proxy de sortie ; None : icônes désactivées
        self.cache: OrderedDict[str, tuple[float, str | None]] = OrderedDict()
        self.en_vol: dict[str, asyncio.Task] = {}

    async def _chercher(self, nom: str) -> str | None:
        try:
            r = await self.client.get(SOURCE.format(domaine=nom), timeout=DELAI)
        except httpx.HTTPError:
            return None
        if r.status_code != 200 or len(r.content) > OCTETS_MAX:
            return None
        return await asyncio.to_thread(en_png, r.content)

    async def pour(self, url: str) -> str | None:
        """Icône du site de l'adresse (cache, puis une seule demande à la fois par domaine)."""
        nom = domaine(url)
        if self.client is None or nom is None:
            return None
        maintenant = time.monotonic()
        if nom in self.cache and self.cache[nom][0] > maintenant:
            self.cache.move_to_end(nom)
            return self.cache[nom][1]
        tache = self.en_vol.get(nom)
        if tache is None:
            tache = self.en_vol[nom] = asyncio.ensure_future(self._chercher(nom))
        try:
            icone = await asyncio.shield(tache)
        finally:
            if tache.done():
                self.en_vol.pop(nom, None)
        self.cache[nom] = (maintenant + (DUREE if icone else DUREE_ABSENTE), icone)
        while len(self.cache) > CACHE_MAX:
            self.cache.popitem(last=False)
        return icone
