"""Registre des outils de l'orchestrateur : des serveurs MCP (transport HTTP), déclarés dans outils.toml.

Chaque serveur décrit lui-même ses outils (nom, description, paramètres) ; l'orchestrateur les découvre et les propose
à Qwen. Un serveur injoignable rend simplement ses outils indisponibles (nouvel essai au bout de RETENTE secondes).
Un appel ouvre sa propre connexion MCP (serveurs sans session) ; la progression de l'outil arrive par `progression`.
"""
import asyncio
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import time
import tomllib
from typing import Any, Awaitable, Callable

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

journal = logging.getLogger('orchestrateur.outils')
CONFIGURATION = Path(os.environ.get('OUTILS', Path(__file__).parent / 'outils.toml'))
VALIDITE = 300.0          # liste des outils d'un serveur gardée 5 minutes
RETENTE = 30.0            # serveur injoignable : nouvel essai au bout de 30 s
DELAI_LISTE = 10.0
DELAI_APPEL = 15 * 60.0   # une recherche très approfondie prend jusqu'à ~10 min


class OutilErreur(Exception):
    """Outil indisponible ou en échec : message montré à Qwen (et dans le déroulé)."""


@dataclass
class Serveur:
    nom: str
    url: str
    jeton: str = ''
    annuler: str = ''          # adresse appelée quand un appel est abandonné (sans session MCP, rien d'autre ne l'arrête)
    outils: dict[str, dict] = field(default_factory=dict)   # nom -> définition au format OpenAI (type function)
    expire: float = 0.0

    def entetes(self) -> dict:
        return {'Authorization': f'Bearer {self.jeton}'} if self.jeton else {}


def charger(chemin: Path = CONFIGURATION) -> list[Serveur]:
    """outils.toml : [[serveurs]] nom, url, jeton (nom de la variable d'environnement qui contient le jeton), annuler
    (facultatif : adresse POST qui arrête le travail en cours du serveur)."""
    brut = tomllib.loads(chemin.read_text(encoding='utf-8')) if chemin.is_file() else {}
    return [Serveur(nom=str(s['nom']), url=str(s['url']), jeton=os.environ.get(str(s.get('jeton') or ''), ''),
                    annuler=str(s.get('annuler') or '')) for s in brut.get('serveurs') or []]


_annulations: set = set()


async def _annuler(serveur: Serveur):
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=5) as http:
            await http.post(serveur.annuler, headers=serveur.entetes())
    except httpx.HTTPError:
        journal.warning('annulation impossible sur le serveur d’outils %s', serveur.nom)


def definition(outil: Any) -> dict:
    """Outil MCP -> définition d'outil pour Qwen (API compatible OpenAI)."""
    return {'type': 'function', 'function': {'name': outil.name, 'description': outil.description or '',
                                             'parameters': outil.inputSchema or {'type': 'object', 'properties': {}}}}


class Registre:
    def __init__(self, serveurs: list[Serveur], connecter: Callable = streamablehttp_client):
        self.serveurs = serveurs
        self.connecter = connecter

    async def _lister(self, serveur: Serveur):
        async with self.connecter(serveur.url, headers=serveur.entetes(), timeout=DELAI_LISTE) as (lire, ecrire, _):
            async with ClientSession(lire, ecrire) as session:
                await session.initialize()
                return (await session.list_tools()).tools

    async def disponibles(self) -> dict[str, dict]:
        """Outils de tous les serveurs joignables : nom -> définition."""
        tous: dict[str, dict] = {}
        maintenant = time.monotonic()
        for serveur in self.serveurs:
            if maintenant >= serveur.expire:
                try:
                    serveur.outils = {o.name: definition(o) for o in await self._lister(serveur)}
                    serveur.expire = maintenant + VALIDITE
                except BaseException as erreur:   # noqa: BLE001 — ExceptionGroup d'anyio compris
                    if isinstance(erreur, (KeyboardInterrupt, SystemExit)):
                        raise
                    journal.warning('serveur d’outils %s injoignable : %s', serveur.nom, type(erreur).__name__)
                    serveur.outils, serveur.expire = {}, maintenant + RETENTE
            tous.update(serveur.outils)
        return tous

    def serveur_de(self, nom: str) -> Serveur | None:
        return next((s for s in self.serveurs if nom in s.outils), None)

    async def appeler(self, nom: str, arguments: dict, progression: Callable[[str], Awaitable[None]], meta: dict | None = None) -> dict:
        """Appelle l'outil ; rend son résultat JSON (objet). Chaque message de progression est passé à `progression`.
        `meta` : réglages de l'utilisateur pour l'outil (métadonnées MCP de l'appel, hors des arguments écrits par Qwen)."""
        serveur = self.serveur_de(nom)
        if serveur is None:
            raise OutilErreur(f'outil inconnu : {nom}')

        async def recue(_avance, _total, message):
            if message:
                await progression(message)
        try:
            async with self.connecter(serveur.url, headers=serveur.entetes(), timeout=DELAI_LISTE,
                                      sse_read_timeout=DELAI_APPEL) as (lire, ecrire, _):
                async with ClientSession(lire, ecrire) as session:
                    await session.initialize()
                    r = await session.call_tool(nom, arguments, progress_callback=recue, meta=meta)
        except asyncio.CancelledError:
            # Réponse abandonnée (l'utilisateur a arrêté) : le serveur est prévenu, en arrière-plan.
            if serveur.annuler:
                tache = asyncio.get_running_loop().create_task(_annuler(serveur))
                _annulations.add(tache)
                tache.add_done_callback(_annulations.discard)
            raise
        except BaseException as erreur:   # noqa: BLE001
            if isinstance(erreur, (KeyboardInterrupt, SystemExit)) or type(erreur).__name__ == 'CancelledError':
                raise
            serveur.expire = 0.0   # rafraîchir la liste au prochain message
            raise OutilErreur(f'l’outil {nom} est injoignable') from None
        texte = ''.join(getattr(c, 'text', '') for c in r.content or [])
        if r.isError:
            raise OutilErreur(texte[:300] or f'l’outil {nom} a échoué')
        try:
            sortie = json.loads(texte)
        except ValueError:
            sortie = {'reponse': texte}
        return sortie if isinstance(sortie, dict) else {'reponse': texte}
