"""Faux outil MCP « recherche_web » pour les tests d'intégration : même interface que recherche/outil, sans Internet.
Rejoue une recherche : progression (étapes, texte en cours d'écriture), puis un rapport vérifié avec une source."""
import hmac
import json
import os

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

JETON = os.environ['RECHERCHE_TOKEN']
serveur = FastMCP('recherche', stateless_http=True, log_level='WARNING',
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=['outil-factice:*'], allowed_origins=[]))


@serveur.tool(name='recherche_web', description='Cherche sur Internet et rédige une réponse citée.')
async def recherche_web(question: str, profondeur: str, ctx: Context) -> dict:
    await ctx.report_progress(1, None, json.dumps({'type': 'planification', 'requetes': [question]}))
    await ctx.report_progress(2, None, json.dumps({'type': 'recherche', 'iteration': 1, 'requetes': [question], 'passages': 3,
                                                   'pages': [{'url': 'https://exemple.fr', 'titre': 'Exemple', 'etat': 'lue', 'source': 1}]}))
    for morceau in ('Rapport ', 'en cours [1][7].'):
        await ctx.report_progress(3, None, json.dumps({'type': 'texte', 'delta': morceau}))
    return {'mode': profondeur, 'reponse': f'Rapport vérifié sur « {question} » ({profondeur}) [1].\n\n**Sources**\n\n- [1] [Exemple](<https://exemple.fr>)',
            'sources': [{'numero': 1, 'url': 'https://exemple.fr', 'titre': 'Exemple'}], 'limites': [], 'duree_s': 1.0, 'appels': 2,
            'pages_lues': 1, 'arret': 'réponse rédigée'}


class Jeton(BaseHTTPMiddleware):
    async def dispatch(self, request, suivant):
        if not hmac.compare_digest(request.headers.get('authorization', '').encode(), f'Bearer {JETON}'.encode()):
            return JSONResponse({'erreur': 'Accès refusé.'}, status_code=401)
        return await suivant(request)


app = serveur.streamable_http_app()
app.add_middleware(Jeton)
uvicorn.run(app, host='0.0.0.0', port=8080, log_level='warning', access_log=False)
