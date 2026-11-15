"""Outils MCP « recherche_web » et « lire_page » de L'Observatoire (serveur MCP, transport HTTP sans session).

L'orchestrateur le découvre et le propose à Qwen ; Qwen l'appelle avec une question autonome et une profondeur. La
recherche elle-même est celle du labo (graphe.py : modes web, approfondie, tres_approfondie, SearXNG et Crawl4AI par
le service de recherche, citations vérifiées). Pendant qu'elle avance, chaque étape part en notification de
progression : son message est un événement JSON réduit à ce qu'affiche le chat (voir compacter) ; les morceaux de la
réponse en cours d'écriture sont des événements « texte ». Le résultat final est un objet JSON (réponse, sources,
limites, statistiques, ou erreur).

lire_page lit une seule page donnée par l'utilisateur (service de recherche, /lire-page) et rend son texte nettoyé :
ce n'est pas une réponse finale, Qwen rédige ensuite à partir de lui, en citant la page [n].

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
OCCUPE = 'La recherche web est très demandée en ce moment : réessaie dans quelques minutes.'
ATTENTE = 'Une autre recherche est en cours : celle-ci attend son tour.'
# Une recherche à la fois (Qwen, moteurs et Crawl4AI sont partagés) ; les suivantes attendent leur tour, au plus
# ATTENTE_MAX secondes (l'orchestrateur abandonne un appel au bout de 15 min, une très approfondie en prend ~10).
ATTENTE_MAX = 240.0
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
    'attente': ('message',),
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
              'sources': [{'numero': x.get('numero'), 'url': x.get('url'), 'titre': x.get('titre'),
                           **({'icone': x['icone']} if x.get('icone') else {}), **({'site': x['site']} if x.get('site') else {})}
                          for x in res.get('sources') or []],
              'duree_s': s.get('duree_s'), 'appels': s.get('appels_qwen'), 'pages_lues': s.get('pages_lues'),
              'arret': s.get('raison_arret')}
    if not sortie['reponse']:
        sortie['erreur'] = str(s.get('raison_arret') or 'la recherche n’a rien produit')
    return sortie


def _observatoire(ctx: Context) -> dict:
    """Métadonnées de l'appel posées par l'orchestrateur (_meta.observatoire), jamais écrites par Qwen."""
    try:
        meta = ctx.request_context.meta
    except (AttributeError, LookupError, ValueError):
        return {}
    extra = getattr(meta, 'model_extra', None) or {}
    valeur = extra.get('observatoire')
    return valeur if isinstance(valeur, dict) else {}


def reflexion_demandee(ctx: Context) -> bool:
    """Réflexion de Qwen pendant la recherche : réglage de l'utilisateur, transmis par l'orchestrateur."""
    return _observatoire(ctx).get('reflexion') is True


def identifiant_appel(ctx: Context) -> str:
    """Identifiant de l'appel donné par l'orchestrateur : /annuler n'arrête que cet appel."""
    appel = _observatoire(ctx).get('appel')
    return appel if isinstance(appel, str) and 0 < len(appel) <= 64 else ''


@serveur.tool(name='recherche_web', description=DESCRIPTION)
async def recherche_web(question: Annotated[str, Field(description=QUESTION)],
                        profondeur: Annotated[Literal['web', 'approfondie', 'tres_approfondie'], Field(description=PROFONDEUR)],
                        ctx: Context) -> dict:
    question = ' '.join(str(question).split())[:graphe.QUESTION_MAX]
    if not question:
        return {'mode': profondeur, 'erreur': 'Question vide.'}
    if not (QWEN_URL and QWEN_CLE):
        return {'mode': profondeur, 'erreur': 'Qwen n’est pas configuré pour la recherche.'}
    numero = 0

    async def emettre(evenement: dict):
        nonlocal numero
        if (c := compacter(evenement)) is not None:
            numero += 1
            await ctx.report_progress(numero, None, json.dumps(c, ensure_ascii=False))

    # Retenue pour /annuler dès l'attente : sans session MCP, l'abandon de l'appel par l'orchestrateur n'arrête pas ce
    # travail. Sans identifiant (appel direct), la recherche ne peut pas être annulée à distance.
    cle = identifiant_appel(ctx) or f'sans-identifiant-{id(asyncio.current_task())}'
    en_cours[cle] = asyncio.current_task()
    try:
        if place.locked():
            await emettre({'type': 'attente', 'message': ATTENTE})
        try:
            await asyncio.wait_for(place.acquire(), ATTENTE_MAX)
        except TimeoutError:
            return {'mode': profondeur, 'erreur': OCCUPE}
        try:
            qwen, web = clients()
            rctx = graphe.RechercheContext(qwen_url=QWEN_URL, qwen_cle=QWEN_CLE, modele=QWEN_MODELE, http=qwen, web=web,
                                           reflexion=reflexion_demandee(ctx), filtre=True, clarifier=False,
                                           compteurs=graphe.Compteurs(debut=asyncio.get_running_loop().time()))
            res = await graphe.executer(profondeur, rctx, question, emettre)
        finally:
            place.release()
    finally:
        en_cours.pop(cle, None)
    return resultat_outil(res, profondeur)


en_cours: dict[str, asyncio.Task] = {}   # identifiant de l'appel -> recherche en cours ou en attente


DESCRIPTION_PAGE = (
    'Lit une page web précise dont l’adresse (http ou https) figure dans la conversation, et rend son texte nettoyé '
    '(menus et publicités retirés). À utiliser quand l’utilisateur donne un lien et demande de le lire, le résumer, '
    'l’expliquer, le traduire ou d’y trouver quelque chose. Ne sert pas à chercher sur Internet : pour cela, '
    'recherche_web.')
URL_PAGE = 'L’adresse complète de la page, telle qu’elle figure dans la conversation (http:// ou https://).'
QUESTION_PAGE = ('Ce que l’utilisateur veut savoir de cette page, en français (vide pour un résumé) : sur une page longue, '
                 'les passages les plus proches sont gardés.')
DELAI_PAGE = 150.0   # le service lit la page (téléchargement simple, ou navigateur jusqu'à 95 s) puis la nettoie


def premier_numero(ctx: Context) -> int:
    """Numéro de citation de la page : l'orchestrateur numérote les pages lues pendant une même réponse."""
    n = _observatoire(ctx).get('premier_numero')
    return n if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= 100 else 1


def resultat_page(page: dict, numero: int) -> dict:
    """Réponse du service (/lire-page) -> résultat de l'outil : le texte pour Qwen, la source pour la liste des sources."""
    if not page.get('succes'):
        return {'erreur': 'La page n’a pas pu être lue : ' + str(page.get('erreur') or 'rien de lisible')[:300]}
    titre = str(page.get('titre') or '')[:300] or str(page.get('url_finale') or page.get('url'))
    source = {'numero': numero, 'url': page.get('url_finale') or page.get('url'), 'titre': titre,
              **({'icone': page['icone']} if page.get('icone') else {}), **({'site': page['site']} if page.get('site') else {})}
    contenu = {'numero': numero, 'url': source['url'], 'titre': titre, 'date_consultation': page.get('date_consultation'),
               'texte': str(page.get('texte') or '')}
    if page.get('extrait'):
        contenu['extrait'] = page['extrait']
    if page.get('avertissement'):
        contenu['avertissement'] = 'page peut-être incomplète : ' + str(page['avertissement'])
    return {'page': contenu, 'sources': [source], 'pages_lues': 1, 'duree_s': page.get('duree_s'),
            'lecture': page.get('lecture'), 'entier': bool(page.get('entier'))}


@serveur.tool(name='lire_page', description=DESCRIPTION_PAGE)
async def lire_page(url: Annotated[str, Field(description=URL_PAGE)], ctx: Context,
                    question: Annotated[str, Field(description=QUESTION_PAGE)] = '') -> dict:
    """Une page, sans Qwen ni file d'attente : quelques secondes, le service borne lui-même ses lectures simultanées."""
    url = str(url).strip()
    question = ' '.join(str(question or '').split())[:500]
    _, web = clients()
    try:
        r = await web.post('/lire-page', json={'url': url, **({'question': question} if question else {})}, timeout=DELAI_PAGE)
    except httpx.HTTPError:
        return {'erreur': 'La lecture de pages est injoignable pour le moment.'}
    try:
        corps = r.json()
    except ValueError:
        corps = {}
    if r.status_code != 200:
        message = (corps.get('erreur') or {}).get('message') if isinstance(corps, dict) and isinstance(corps.get('erreur'), dict) else None
        return {'erreur': 'La page n’a pas pu être lue : ' + (message or f'statut {r.status_code}')}
    return resultat_page(corps if isinstance(corps, dict) else {}, premier_numero(ctx))


@serveur.custom_route('/annuler', methods=['POST'])
async def annuler(request: Request) -> JSONResponse:
    """Appelé par l'orchestrateur quand l'utilisateur arrête la réponse, avec l'identifiant de l'appel ({"appel": …}) :
    cette recherche-là s'arrête (ou quitte la file d'attente) et libère sa place ; celles des autres continuent."""
    try:
        corps = await request.json()
    except ValueError:
        corps = {}
    appel = corps.get('appel') if isinstance(corps, dict) else None
    tache = en_cours.get(appel) if isinstance(appel, str) and appel else None
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
