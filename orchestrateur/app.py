"""Orchestrateur de L'Observatoire : entre le backend et Qwen, pour les réponses du chat.

POST /v1/chat/completions, compatible OpenAI (le backend l'appelle comme il appelait Qwen), jeton ORCHESTRATEUR_TOKEN.
- Sans outil demandé (le cas de tous les messages ordinaires), ou pour continuer une réponse coupée : la requête part
  telle quelle chez Qwen et sa réponse revient octet pour octet (même statut, même flux).
- Avec des outils demandés par le backend (extension « observatoire » : {"outils": {"recherche_web": "auto"}}), pour
  un compte qui y a droit : boucle d'outils LangGraph (boucle.py), outils découverts sur les serveurs MCP d'outils.toml.
GET /sante : état, et outils joignables.
"""
import asyncio
from contextlib import asynccontextmanager
import hmac
import logging
import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

import boucle
from outils import Registre, charger

logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')
QWEN_URL = os.environ.get('QWEN_BASE_URL', '').rstrip('/')
QWEN_CLE = os.environ.get('QWEN_API_KEY', '')
JETON = os.environ.get('ORCHESTRATEUR_TOKEN', '')
MODES = {'auto', 'web', 'approfondie', 'tres_approfondie'}
ENTETES_FLUX = {'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}


@asynccontextmanager
async def cycle(app: FastAPI):
    # trust_env=False : Qwen est joint directement, jamais par un proxy de l'environnement.
    async with httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=httpx.Timeout(60, read=boucle.DELAI_QWEN)) as http:
        app.state.http, app.state.registre = http, Registre(charger())
        yield


app = FastAPI(lifespan=cycle, docs_url=None, redoc_url=None, openapi_url=None)
_FIN = object()


BATTEMENT = 15.0   # s : commentaire SSE envoyé quand rien d'autre n'est parti (longues phases silencieuses des outils)


async def jusqu_a_deconnexion(request: Request, source, battement: float = BATTEMENT):
    """Flux de `source`, arrêté dès que le backend coupe la connexion (l'utilisateur a cliqué sur Stop) : la production
    est annulée, ce qui ferme la requête à Qwen ou prévient l'outil en cours. Starlette ne le fait plus de lui-même et
    uvicorn ignore en silence les écritures vers une connexion fermée : sans cela, Qwen écrirait jusqu'au bout.
    Sans rien à envoyer pendant `battement` secondes, un commentaire SSE (ignoré par le backend) garde la connexion
    vivante."""
    file: asyncio.Queue = asyncio.Queue()

    async def produire():
        try:
            async for bloc in source:
                file.put_nowait(bloc)
        finally:
            file.put_nowait(_FIN)

    async def surveiller():
        while (await request.receive())['type'] != 'http.disconnect':
            pass
        producteur.cancel()

    producteur = asyncio.create_task(produire())
    veilleur = asyncio.create_task(surveiller())
    try:
        while True:
            try:
                bloc = await asyncio.wait_for(file.get(), battement)
            except TimeoutError:
                yield b': keep-alive\n\n'
                continue
            if bloc is _FIN:
                break
            yield bloc
        await producteur   # erreur éventuelle de la production
    finally:
        veilleur.cancel()
        if not producteur.done():
            producteur.cancel()


def autorise(request: Request) -> bool:
    fourni = request.headers.get('authorization', '')
    return bool(JETON) and hmac.compare_digest(fourni.encode(), f'Bearer {JETON}'.encode())


def demandes_valides(extension) -> dict:
    """Outils demandés par le backend (qui a vérifié les droits du compte) ; tout le reste est ignoré."""
    outils = extension.get('outils') if isinstance(extension, dict) else None
    if not isinstance(outils, dict):
        return {}
    return {str(nom): mode for nom, mode in outils.items() if isinstance(mode, str) and mode in MODES}


async def relais(request: Request, corps: dict) -> Response:
    """La requête telle quelle chez Qwen ; la réponse revient sans transformation (flux compris)."""
    http: httpx.AsyncClient = request.app.state.http
    requete = http.build_request('POST', QWEN_URL + '/chat/completions', json=corps,
                                 headers={'Authorization': f'Bearer {QWEN_CLE}'})
    try:
        r = await http.send(requete, stream=True)
    except httpx.HTTPError:
        return JSONResponse({'error': {'message': 'Le serveur Qwen est inaccessible.'}}, status_code=502)
    type_ = r.headers.get('content-type', 'application/json')
    if r.status_code != 200 or 'text/event-stream' not in type_:
        contenu = await r.aread()
        await r.aclose()
        return Response(contenu, status_code=r.status_code, media_type=type_)

    async def octets():
        try:
            # Décompressé si Qwen compresse (les en-têtes ne sont pas recopiés) ; sinon octet pour octet.
            async for bloc in r.aiter_bytes():
                yield bloc
        finally:
            await r.aclose()
    return StreamingResponse(jusqu_a_deconnexion(request, octets()), media_type=type_, headers=ENTETES_FLUX)


@app.post('/v1/chat/completions')
async def completions(request: Request):
    if not autorise(request):
        return JSONResponse({'error': {'message': 'Accès refusé.'}}, status_code=401)
    if not (QWEN_URL and QWEN_CLE):
        return JSONResponse({'error': {'message': 'Qwen n’est pas configuré.'}}, status_code=503)
    try:
        corps = await request.json()
    except ValueError:
        return JSONResponse({'error': {'message': 'Requête illisible.'}}, status_code=400)
    if not isinstance(corps, dict):
        return JSONResponse({'error': {'message': 'Requête illisible.'}}, status_code=400)
    demandes = demandes_valides(corps.pop('observatoire', None))
    if not demandes or not corps.get('stream') or corps.get('continue_final_message'):
        return await relais(request, corps)
    flux = boucle.flux(corps, demandes, request.app.state.http, QWEN_URL, QWEN_CLE, request.app.state.registre)
    return StreamingResponse(jusqu_a_deconnexion(request, flux), media_type='text/event-stream; charset=utf-8', headers=ENTETES_FLUX)


@app.get('/sante')
async def sante(request: Request):
    registre: Registre = request.app.state.registre
    return {'ok': True, 'qwen': bool(QWEN_URL and QWEN_CLE), 'serveurs': {s.nom: sorted(s.outils) for s in registre.serveurs}}
