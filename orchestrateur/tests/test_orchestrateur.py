"""Orchestrateur : relais à l'identique, boucle d'outils (faux Qwen en flux, faux registre), et un vrai serveur MCP local."""
import asyncio
import json
import socket
import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient

import app as application
import boucle
from outils import OutilErreur, Registre, Serveur

DEFINITION = {'type': 'function', 'function': {'name': 'recherche_web', 'description': 'Cherche sur Internet.', 'parameters': {
    'type': 'object', 'properties': {'question': {'type': 'string'},
                                     'profondeur': {'type': 'string', 'enum': ['web', 'approfondie', 'tres_approfondie']}},
    'required': ['question', 'profondeur']}}}


def sse(*morceaux) -> bytes:
    return b''.join(f'data: {json.dumps(m, ensure_ascii=False)}\n\n'.encode() for m in morceaux) + b'data: [DONE]\n\n'


def texte_qwen(texte: str, prompt: int = 500) -> bytes:
    return sse(*[{'choices': [{'index': 0, 'delta': {'content': texte[i:i + 4]}}]} for i in range(0, len(texte), 4)],
               {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]},
               {'choices': [], 'usage': {'prompt_tokens': prompt, 'completion_tokens': 7}})


def appel_qwen(*appels, avant: str = '', prompt: int = 500) -> bytes:
    morceaux = [{'choices': [{'index': 0, 'delta': {'content': avant}}]}] if avant else []
    for i, (nom, arguments) in enumerate(appels):
        brut = json.dumps(arguments, ensure_ascii=False)
        morceaux += [{'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': i, 'id': f'id{i}', 'type': 'function', 'function': {'name': nom, 'arguments': ''}}]}}]},
                     {'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': i, 'function': {'arguments': brut[:10]}}]}}]},
                     {'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': i, 'function': {'arguments': brut[10:]}}]}}]}]
    morceaux += [{'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]},
                 {'choices': [], 'usage': {'prompt_tokens': prompt, 'completion_tokens': 5}}]
    return sse(*morceaux)


def faux_qwen(reponses: list, recus: list):
    """Réponses successives de Qwen (octets SSE, ou un statut HTTP) ; les corps reçus sont gardés."""
    suite = iter(reponses)

    def repondre(request: httpx.Request) -> httpx.Response:
        recus.append(json.loads(request.content))
        r = next(suite)
        if isinstance(r, int):
            return httpx.Response(r, json={'error': 'détail privé'})
        return httpx.Response(200, content=r, headers={'Content-Type': 'text/event-stream'})
    return httpx.MockTransport(repondre)


class FauxRegistre(Registre):
    def __init__(self, sortie=None, progression=(), disponibles=True, erreur=None):
        super().__init__([])
        self.sortie, self.progression, self.ok, self.erreur, self.appels = sortie, progression, disponibles, erreur, []

    async def disponibles(self):
        return {'recherche_web': DEFINITION} if self.ok else {}

    async def appeler(self, nom, arguments, progression, meta=None):
        self.appels.append((nom, arguments))
        self.meta = meta
        for message in self.progression:
            await progression(message)
        if self.erreur:
            raise OutilErreur(self.erreur)
        return self.sortie


def lancer(reponses, registre, demandes=None, messages=None, effort='none'):
    async def tout():
        recus = []
        async with httpx.AsyncClient(transport=faux_qwen(reponses, recus)) as http:
            corps = {'model': 'qwen', 'messages': messages or [{'role': 'user', 'content': 'Dernière version de Rust ?'}],
                     'stream': True, 'max_tokens': 4000, 'reasoning_effort': effort, 'temperature': 0.7}
            octets = b''.join([b async for b in boucle.flux(corps, demandes or {'recherche_web': 'auto'}, http, 'http://qwen/v1', 'cle', registre)])
        lignes = [l[6:] for l in octets.decode().split('\n\n') if l.startswith('data: ')]
        return [json.loads(l) for l in lignes if l != '[DONE]'], lignes[-1], recus
    return asyncio.run(tout())


def texte(evenements):
    return ''.join(e['choices'][0]['delta'].get('content', '') for e in evenements if e.get('choices'))


def observatoire(evenements, cle='recherche_web'):
    return [e['observatoire'][cle] for e in evenements if cle in e.get('observatoire', {})]


class Boucle(unittest.TestCase):
    def test_reponse_directe(self):
        evenements, fin, recus = lancer([texte_qwen('Bonjour !')], FauxRegistre(),
                                        messages=[{'role': 'system', 'content': 'Mémoire : X'}, {'role': 'user', 'content': 'Salut'}])
        self.assertEqual(texte(evenements), 'Bonjour !')
        self.assertEqual(fin, '[DONE]')
        self.assertEqual(evenements[-1]['usage'], {'prompt_tokens': 500, 'completion_tokens': 7})
        self.assertEqual(evenements[-2]['choices'][0]['finish_reason'], 'stop')
        corps = recus[0]
        self.assertEqual(corps['tool_choice'], 'auto')
        self.assertEqual(corps['tools'][0]['function']['name'], 'recherche_web')
        self.assertEqual([m['role'] for m in corps['messages']], ['system', 'user'], 'une seule consigne système')
        self.assertTrue(corps['messages'][0]['content'].startswith('Nous sommes le '))
        self.assertTrue(corps['messages'][0]['content'].endswith('Mémoire : X'))
        self.assertEqual((corps['max_tokens'], corps['temperature'], corps['stream_options']), (4000, 0.7, {'include_usage': True}))

    def test_appel_d_outil_progression_et_reponse_finale(self):
        progression = [json.dumps({'type': 'planification', 'requetes': ['rust version']}),
                       json.dumps({'type': 'texte', 'delta': 'La 1.99 '}), json.dumps({'type': 'texte', 'delta': '[1][9].'})]
        registre = FauxRegistre(sortie={'mode': 'web', 'reponse': 'La 1.99 [1].\n\n**Sources**', 'sources': [{'numero': 1, 'url': 'u', 'titre': 't'}],
                                        'limites': [], 'duree_s': 20, 'appels': 2, 'pages_lues': 5, 'arret': 'réponse rédigée'},
                                progression=progression)
        evenements, fin, recus = lancer([appel_qwen(('recherche_web', {'question': 'Dernière version stable de Rust', 'profondeur': 'web'}), prompt=640)],
                                        registre)
        self.assertEqual(registre.appels, [('recherche_web', {'question': 'Dernière version stable de Rust', 'profondeur': 'web'})])
        self.assertEqual(len(recus), 1, 'réponse finale de l’outil : pas de second appel à Qwen')
        self.assertEqual(texte(evenements), 'La 1.99 [1][9].', 'texte en cours d’écriture montré tel quel')
        etapes = observatoire(evenements)
        self.assertEqual([e['type'] for e in etapes], ['appel', 'planification', 'sources', 'fin'])
        self.assertEqual(etapes[0]['arguments']['profondeur'], 'web')
        self.assertEqual(etapes[-1]['pages_lues'], 5)
        contenus = [e['observatoire']['contenu'] for e in evenements if 'contenu' in e.get('observatoire', {})]
        self.assertEqual(contenus, ['La 1.99 [1].\n\n**Sources**'], 'texte vérifié à la fin')
        self.assertEqual(evenements[-1]['usage'], {'prompt_tokens': 640, 'completion_tokens': 5})
        self.assertFalse(any('tool_calls' in json.dumps(e) for e in evenements), 'appels d’outils jamais transmis')

    def test_reglage_de_reflexion_transmis_a_l_outil(self):
        for effort, attendu in (('none', False), ('medium', True)):
            registre = FauxRegistre(sortie={'reponse': 'Rapport.'})
            lancer([appel_qwen(('recherche_web', {'question': 'q', 'profondeur': 'web'}))], registre, effort=effort)
            self.assertEqual(registre.meta, {'observatoire': {'reflexion': attendu}})

    def test_texte_ecrit_avant_l_appel_garde(self):
        registre = FauxRegistre(sortie={'reponse': 'Rapport.'})
        evenements, _, _ = lancer([appel_qwen(('recherche_web', {'question': 'q', 'profondeur': 'web'}), avant='Je vérifie.')], registre)
        self.assertEqual([e['observatoire']['contenu'] for e in evenements if 'contenu' in e.get('observatoire', {})], ['Je vérifie.\n\nRapport.'])

    def test_profondeur_imposee(self):
        registre = FauxRegistre(sortie={'reponse': 'Rapport.'})
        _, _, recus = lancer([appel_qwen(('recherche_web', {'question': 'q', 'profondeur': 'tres_approfondie'}))], registre,
                             demandes={'recherche_web': 'tres_approfondie'})
        corps = recus[0]
        self.assertEqual(corps['tool_choice'], {'type': 'function', 'function': {'name': 'recherche_web'}})
        self.assertEqual(corps['tools'][0]['function']['parameters']['properties']['profondeur']['enum'], ['tres_approfondie'])
        self.assertIn('demandé d’utiliser l’outil recherche_web', corps['messages'][0]['content'])
        self.assertEqual(DEFINITION['function']['parameters']['properties']['profondeur']['enum'], ['web', 'approfondie', 'tres_approfondie'],
                         'définition d’origine intacte')

    def test_echec_de_l_outil_qwen_repond_sans(self):
        registre = FauxRegistre(erreur='l’outil recherche_web est injoignable')
        evenements, _, recus = lancer([appel_qwen(('recherche_web', {'question': 'q', 'profondeur': 'web'})), texte_qwen('Sans recherche : …')], registre)
        self.assertEqual(texte(evenements), 'Sans recherche : …')
        self.assertEqual(observatoire(evenements)[-1], {'type': 'echec', 'message': 'l’outil recherche_web est injoignable'})
        second = recus[1]
        self.assertNotIn('tools', second, 'outil en échec plus proposé')
        self.assertEqual(second['messages'][-1]['role'], 'tool')
        self.assertIn('injoignable', second['messages'][-1]['content'])
        self.assertIn('ne devine jamais une date', second['messages'][-1]['content'], 'consigne de repli : pas de faits récents inventés')
        self.assertEqual(second['messages'][-2]['tool_calls'][0]['function']['name'], 'recherche_web')

    def test_outil_indisponible(self):
        evenements, _, recus = lancer([texte_qwen('Réponse.')], FauxRegistre(disponibles=False))
        self.assertEqual(observatoire(evenements)[0]['type'], 'indisponible')
        self.assertNotIn('tools', recus[0])
        self.assertEqual(recus[0]['messages'][0]['role'], 'user', 'pas de consigne d’outils sans outil')

    def test_un_seul_appel_par_outil(self):
        registre = FauxRegistre(sortie={'reponse': 'Rapport.'})
        lancer([appel_qwen(('recherche_web', {'question': 'a', 'profondeur': 'web'}), ('recherche_web', {'question': 'b', 'profondeur': 'web'}))], registre)
        self.assertEqual([a[1]['question'] for a in registre.appels], ['a'])

    def test_erreur_de_qwen(self):
        evenements, fin, _ = lancer([503], FauxRegistre())
        self.assertEqual(evenements[-1], {'error': {'message': 'Qwen a répondu HTTP 503.'}})


class Relais(unittest.TestCase):
    def client(self, reponse, recus):
        def repondre(request):
            recus.append((dict(request.headers), json.loads(request.content)))
            return reponse
        tc = TestClient(application.app)
        tc.__enter__()
        self.addCleanup(tc.__exit__, None, None, None)
        application.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(repondre))
        return tc

    def test_relais_a_l_identique(self):
        recus = []
        brut = texte_qwen('Bonjour, été !')
        with mock.patch.object(application, 'JETON', 'jeton'), mock.patch.object(application, 'QWEN_URL', 'http://qwen/v1'), \
                mock.patch.object(application, 'QWEN_CLE', 'cle-qwen'):
            tc = self.client(httpx.Response(200, content=brut, headers={'Content-Type': 'text/event-stream'}), recus)
            r = tc.post('/v1/chat/completions', headers={'Authorization': 'Bearer jeton'},
                        json={'model': 'q', 'stream': True, 'messages': [], 'observatoire': {'outils': {}}})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.content, brut)
            self.assertEqual(recus[0][0]['authorization'], 'Bearer cle-qwen')
            self.assertNotIn('observatoire', recus[0][1])
            refus = tc.post('/v1/chat/completions', headers={'Authorization': 'Bearer faux'}, json={})
            self.assertEqual(refus.status_code, 401)

    def test_erreur_relayee_et_reprise_sans_outils(self):
        recus = []
        with mock.patch.object(application, 'JETON', 'j'), mock.patch.object(application, 'QWEN_URL', 'http://qwen/v1'), \
                mock.patch.object(application, 'QWEN_CLE', 'c'):
            tc = self.client(httpx.Response(503, json={'error': 'x'}), recus)
            r = tc.post('/v1/chat/completions', headers={'Authorization': 'Bearer j'},
                        json={'stream': True, 'continue_final_message': True, 'messages': [],
                              'observatoire': {'outils': {'recherche_web': 'auto'}}})
            self.assertEqual(r.status_code, 503, 'une reprise passe toujours par le relais, sans outils')


class Deconnexion(unittest.TestCase):
    def test_coupure_annule_la_production(self):
        """Le backend coupe la connexion : la source (requête à Qwen, ou boucle d'outils) est annulée."""
        async def tout():
            etat = {'annulee': False}
            messages = asyncio.Queue()
            await messages.put({'type': 'http.request', 'body': b'', 'more_body': False})

            class Requete:
                async def receive(self):
                    return await messages.get()

            async def source():
                try:
                    yield b'a'
                    await asyncio.sleep(30)
                    yield b'jamais'
                except asyncio.CancelledError:
                    etat['annulee'] = True
                    raise
            flux = application.jusqu_a_deconnexion(Requete(), source())
            premier = await flux.__anext__()
            await messages.put({'type': 'http.disconnect'})
            await asyncio.sleep(0.1)
            await flux.aclose()
            return premier, etat['annulee']
        premier, annulee = asyncio.run(tout())
        self.assertEqual(premier, b'a')
        self.assertTrue(annulee)

    def test_battement_pendant_un_long_silence(self):
        async def tout():
            class Requete:
                async def receive(self):
                    await asyncio.sleep(30)

            async def source():
                yield b'data: 1\n\n'
                await asyncio.sleep(0.35)
                yield b'data: 2\n\n'
            return [b async for b in application.jusqu_a_deconnexion(Requete(), source(), battement=0.1)]
        blocs = asyncio.run(tout())
        self.assertEqual((blocs[0], blocs[-1]), (b'data: 1\n\n', b'data: 2\n\n'))
        self.assertGreaterEqual(blocs.count(b': keep-alive\n\n'), 2)

    def test_flux_complet_sans_coupure(self):
        async def tout():
            class Requete:
                async def receive(self):
                    await asyncio.sleep(30)

            async def source():
                for b in (b'1', b'2', b'3'):
                    yield b
            return [b async for b in application.jusqu_a_deconnexion(Requete(), source())]
        self.assertEqual(asyncio.run(tout()), [b'1', b'2', b'3'])


class McpReel(unittest.TestCase):
    """Un vrai serveur MCP (HTTP, sans session) lancé dans le test : découverte, jeton, progression, résultat."""
    def test_decouverte_et_appel(self):
        import uvicorn
        from mcp.server.fastmcp import Context, FastMCP

        serveur = FastMCP('essai', stateless_http=True, log_level='WARNING')

        @serveur.tool(name='recherche_web', description='Cherche.')
        async def recherche_web(question: str, profondeur: str, ctx: Context) -> dict:
            await ctx.report_progress(1, None, json.dumps({'type': 'planification', 'requetes': [question]}))
            return {'reponse': f'R : {question} ({profondeur})'}

        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]

        async def tout():
            srv = uvicorn.Server(uvicorn.Config(serveur.streamable_http_app(), host='127.0.0.1', port=port, log_level='warning'))
            tache = asyncio.create_task(srv.serve())
            while not srv.started:
                await asyncio.sleep(0.05)
            try:
                registre = Registre([Serveur('essai', f'http://127.0.0.1:{port}/mcp')])
                outils = await registre.disponibles()
                recus = []

                async def progression(m):
                    recus.append(json.loads(m))
                sortie = await registre.appeler('recherche_web', {'question': 'Q', 'profondeur': 'web'}, progression)
                injoignable = Registre([Serveur('absent', 'http://127.0.0.1:9/mcp')])
                return outils, sortie, recus, await injoignable.disponibles()
            finally:
                srv.should_exit = True
                await tache
        outils, sortie, recus, rien = asyncio.run(tout())
        self.assertEqual(outils['recherche_web']['function']['description'], 'Cherche.')
        self.assertEqual(sortie, {'reponse': 'R : Q (web)'})
        self.assertEqual(recus, [{'type': 'planification', 'requetes': ['Q']}])
        self.assertEqual(rien, {}, 'serveur injoignable : aucun outil, sans erreur')

    def test_appel_abandonne_le_serveur_est_prevenu(self):
        import uvicorn
        from mcp.server.fastmcp import Context, FastMCP
        from starlette.responses import JSONResponse

        serveur, annulations = FastMCP('essai', stateless_http=True, log_level='WARNING'), []

        @serveur.tool(name='lent', description='Long.')
        async def lent(ctx: Context) -> dict:
            await ctx.report_progress(1, None, json.dumps({'type': 'debut'}))
            await asyncio.sleep(30)
            return {'reponse': 'trop tard'}

        @serveur.custom_route('/annuler', methods=['POST'])
        async def annuler(request):
            annulations.append(request.headers.get('authorization'))
            return JSONResponse({'annulee': True})

        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]

        async def tout():
            srv = uvicorn.Server(uvicorn.Config(serveur.streamable_http_app(), host='127.0.0.1', port=port, log_level='warning'))
            tache_serveur = asyncio.create_task(srv.serve())
            while not srv.started:
                await asyncio.sleep(0.05)
            try:
                registre = Registre([Serveur('essai', f'http://127.0.0.1:{port}/mcp', jeton='j', annuler=f'http://127.0.0.1:{port}/annuler')])
                await registre.disponibles()
                debut = asyncio.Event()

                async def progression(_):
                    debut.set()
                appel = asyncio.create_task(registre.appeler('lent', {}, progression))
                await asyncio.wait_for(debut.wait(), 10)
                appel.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await appel
                for _ in range(50):
                    if annulations:
                        break
                    await asyncio.sleep(0.05)
            finally:
                srv.should_exit = True
                await tache_serveur
        asyncio.run(tout())
        self.assertEqual(annulations, ['Bearer j'])


if __name__ == '__main__':
    unittest.main()
