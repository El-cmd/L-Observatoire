"""Outil MCP « recherche_web » de L'Observatoire (serveur MCP, transport HTTP sans session).

L'orchestrateur le découvre et le propose à Qwen ; Qwen l'appelle avec une question autonome et une profondeur. La
recherche elle-même est celle du labo (graphe.py : modes web, approfondie, tres_approfondie, SearXNG et Crawl4AI par
le service de recherche, citations vérifiées). Pendant qu'elle avance, chaque étape part en notification de
progression : son message est un événement JSON réduit à ce qu'affiche le chat (voir compacter) ; les morceaux de la
réponse en cours d'écriture sont des événements « texte ». Le résultat final est un objet JSON (réponse, sources,
limites, statistiques, ou erreur).

Accès : jeton RECHERCHE_TOKEN (en-tête Authorization), réseau interne seulement. Une recherche à la fois.
"""
import asyncio
import hmac
import json
import os
from typing import Annotated, Any, Literal

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

import graphe

QWEN_URL = os.environ.get('QWEN_BASE_URL', '').rstrip('/')
QWEN_CLE = os.environ.get('QWEN_API_KEY', '')
QWEN_MODELE = os.environ.get('QWEN_MODEL', 'qwen3.8-27b-abliterated')
SERVICE_URL = os.environ.get('SERVICE_URL', 'http://recherche-service:8080')
JETON = os.environ.get('RECHERCHE_TOKEN', '')
OCCUPE = 'Une recherche web est déjà en cours : réessaie quand elle sera finie.'
PAGES_AFFICHEES = 12

DESCRIPTION = (
    'Cherche sur Internet (pages réellement lues) et rédige une réponse en français, avec ses sources citées [n]. À '
    'utiliser quand la question demande une information récente, précise ou à vérifier (versions, dates, actualité, '
    'documentation, chiffres, avis) ; jamais pour écrire du code, raisonner, reformuler ou une connaissance générale '
    'stable. La réponse rendue est montrée telle quelle à l’utilisateur.')
QUESTION = ('La question complète et autonome, en français, avec le contexte utile de la conversation (pas de « ça », '
            '« il », « le point 2 ») ; garder tels quels les noms propres, sigles et messages d’erreur.')
PROFONDEUR = ('« web » : une information précise qui tient en une recherche (environ 30 s) ; « approfondie » : un sujet à '
              'croiser sur plusieurs sources, expliquer un fonctionnement, résoudre un problème, comment faire (environ '
              '1 min) ; « tres_approfondie » : une question large ou à plusieurs volets, comparaison, choix entre des '
              'options, état des lieux (environ 3 min). En cas de doute, la plus légère.')

# Le SDK n'accepte par défaut que les requêtes adressées à localhost (protection contre le « DNS rebinding ») :
# l'orchestrateur appelle ce serveur sous son nom sur le réseau Docker, « recherche ». Aucun navigateur ne l'appelle.
SECURITE = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=['recherche:*', '127.0.0.1:*', 'localhost:*'],
                                     allowed_origins=[])
serveur = FastMCP('recherche', stateless_http=True, log_level='WARNING', transport_security=SECURITE)
place = asyncio.Semaphore(1)
_clients: dict[str, httpx.AsyncClient] = {}


def clients() -> tuple[httpx.AsyncClient, httpx.AsyncClient]:
    """Clients HTTP partagés (créés au premier appel, dans la boucle du serveur)."""
    if not _clients:
        _clients['qwen'] = httpx.AsyncClient(follow_redirects=False)
        _clients['web'] = httpx.AsyncClient(base_url=SERVICE_URL, trust_env=False)
    return _clients['qwen'], _clients['web']


def _pages(liste: Any) -> list[dict]:
    return [{'url': str(p.get('url') or ''), 'titre': str(p.get('titre') or '')[:200], 'etat': p.get('etat'),
             'source': p.get('source'), 'favorisee': bool(p.get('favorisee'))}
            for p in (liste or [])[:PAGES_AFFICHEES] if isinstance(p, dict)]


_GARDER = {
    'planification': ('requetes',),
    'recherche': ('iteration', 'requetes', 'passages', 'avertissements'),
    'lecture': ('iteration', 'lot'),
    'verification': ('decision', 'raison', 'nouvelles_requetes'),
    'arret': ('raison',),
    'cahier': ('objectif', 'criteres'),
    'chercheur_debut': ('id', 'question', 'tour'),
    'chercheur': ('id', 'question', 'tour', 'requetes', 'passages'),
    'supervision': ('tour', 'decision', 'raison'),
    'compression': ('id',),
    'section': ('id', 'texte'),   # texte : affiché dans la réponse pendant que les autres parties s'écrivent
    'redaction_debut': (),
    'redaction': (),
    'erreur': ('message',),
}


def compacter(e: dict) -> dict | None:
    """Événement du graphe réduit à ce qu'affiche le chat (pas les faits ni les notes eux-mêmes : leur nombre).
    None : événement sans intérêt pour le chat."""
    genre = e.get('type')
    if genre == 'texte':
        return {'type': 'texte', 'delta': str(e.get('delta') or '')}
    if genre not in _GARDER:
        return None
    c = {'type': genre, **{k: e.get(k) for k in _GARDER[genre] if e.get(k) is not None}}
    if genre in ('recherche', 'chercheur'):
        c['pages'] = _pages(e.get('pages'))
    if genre in ('lecture', 'chercheur'):
        c['faits'] = len(e.get('faits') or [])
    if genre == 'cahier':
        c['sous_questions'] = [{'id': q.get('id'), 'question': q.get('question')} for q in e.get('sous_questions') or []]
    if genre == 'supervision':
        c['couverture'] = [{'id': x.get('id'), 'statut': x.get('statut')} for x in e.get('couverture') or []]
        c['relances'] = [x.get('id') for x in e.get('relances') or []]
    if genre == 'compression':
        c['notes'] = len(e.get('notes') or [])
    return c


def resultat_outil(res: dict, profondeur: str) -> dict:
    s = res.get('statistiques') or {}
    sortie = {'mode': profondeur, 'reponse': res.get('reponse') or '', 'limites': res.get('limites') or [],
              'sources': [{'numero': x.get('numero'), 'url': x.get('url'), 'titre': x.get('titre')} for x in res.get('sources') or []],
              'duree_s': s.get('duree_s'), 'appels': s.get('appels_qwen'), 'pages_lues': s.get('pages_lues'),
              'arret': s.get('raison_arret')}
    if not sortie['reponse']:
        sortie['erreur'] = str(s.get('raison_arret') or 'la recherche n’a rien produit')
    return sortie


def reflexion_demandee(ctx: Context) -> bool:
    """Réflexion de Qwen pendant la recherche : réglage de l'utilisateur, transmis par l'orchestrateur dans les
    métadonnées de l'appel (_meta.observatoire.reflexion), jamais par Qwen."""
    try:
        meta = ctx.request_context.meta
    except (AttributeError, LookupError, ValueError):
        return False
    extra = getattr(meta, 'model_extra', None) or {}
    return (extra.get('observatoire') or {}).get('reflexion') is True


@serveur.tool(name='recherche_web', description=DESCRIPTION)
async def recherche_web(question: Annotated[str, Field(description=QUESTION)],
                        profondeur: Annotated[Literal['web', 'approfondie', 'tres_approfondie'], Field(description=PROFONDEUR)],
                        ctx: Context) -> dict:
    question = ' '.join(str(question).split())[:graphe.QUESTION_MAX]
    if not question:
        return {'mode': profondeur, 'erreur': 'Question vide.'}
    if not (QWEN_URL and QWEN_CLE):
        return {'mode': profondeur, 'erreur': 'Qwen n’est pas configuré pour la recherche.'}
    if place.locked():
        return {'mode': profondeur, 'erreur': OCCUPE}
    async with place:
        qwen, web = clients()
        rctx = graphe.RechercheContext(qwen_url=QWEN_URL, qwen_cle=QWEN_CLE, modele=QWEN_MODELE, http=qwen, web=web,
                                       reflexion=reflexion_demandee(ctx), filtre=True, clarifier=False,
                                       compteurs=graphe.Compteurs(debut=asyncio.get_running_loop().time()))
        numero = 0

        async def emettre(evenement: dict):
            nonlocal numero
            if (c := compacter(evenement)) is not None:
                numero += 1
                await ctx.report_progress(numero, None, json.dumps(c, ensure_ascii=False))

        # Retenue pour /annuler : sans session MCP, l'abandon de l'appel par l'orchestrateur n'arrête pas ce travail.
        en_cours['tache'] = asyncio.current_task()
        try:
            res = await graphe.executer(profondeur, rctx, question, emettre)
        finally:
            en_cours.pop('tache', None)
    return resultat_outil(res, profondeur)


en_cours: dict[str, asyncio.Task] = {}


@serveur.custom_route('/annuler', methods=['POST'])
async def annuler(_: Request) -> JSONResponse:
    """Appelé par l'orchestrateur quand l'utilisateur arrête la réponse : la recherche en cours s'arrête et libère sa
    place (une seule recherche à la fois)."""
    tache = en_cours.get('tache')
    if tache is not None and not tache.done():
        tache.cancel()
        return JSONResponse({'annulee': True})
    return JSONResponse({'annulee': False})


@serveur.custom_route('/sante', methods=['GET'])
async def sante(_: Request) -> JSONResponse:
    return JSONResponse({'ok': True, 'qwen': bool(QWEN_URL and QWEN_CLE), 'occupe': place.locked()})


class Jeton(BaseHTTPMiddleware):
    """Toute requête MCP doit porter le jeton partagé avec l'orchestrateur (comparaison à temps constant)."""
    async def dispatch(self, request: Request, suivant):
        if request.url.path != '/sante':
            fourni = request.headers.get('authorization', '')
            if not JETON or not hmac.compare_digest(fourni.encode(), f'Bearer {JETON}'.encode()):
                return JSONResponse({'erreur': 'Accès refusé.'}, status_code=401)
        return await suivant(request)


def application():
    app = serveur.streamable_http_app()
    app.add_middleware(Jeton)
    return app


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(application(), host='0.0.0.0', port=8080, log_level='warning', access_log=False, timeout_keep_alive=5)
