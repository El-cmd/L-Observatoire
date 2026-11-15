"""Outil MCP recherche_web : événements réduits, résultat, appel complet par un client MCP (en mémoire, sans réseau)."""
import asyncio
import json
import unittest
from unittest import mock

from mcp.shared.memory import create_connected_server_and_client_session

import serveur


class Compacter(unittest.TestCase):
    def test_evenements_reduits(self):
        self.assertEqual(serveur.compacter({'type': 'texte', 'delta': 'Bon'}), {'type': 'texte', 'delta': 'Bon'})
        self.assertIsNone(serveur.compacter({'type': 'reflexion'}))
        self.assertIsNone(serveur.compacter({'type': 'debut', 'mode': 'web'}))
        c = serveur.compacter({'type': 'chercheur', 'id': 'Q1', 'question': 'Q', 'tour': 1, 'requetes': ['a'], 'passages': 4,
                               'faits': [{'texte': 'f'}] * 3, 'jetons': {'entree': 9},
                               'pages': [{'url': 'https://a.fr', 'titre': 'A' * 300, 'etat': 'lue', 'source': 2, 'favorisee': True, 'erreur': None}] * 20})
        self.assertEqual(c['faits'], 3)
        self.assertEqual(len(c['pages']), serveur.PAGES_AFFICHEES)
        self.assertEqual(len(c['pages'][0]['titre']), 200)
        self.assertNotIn('jetons', c)
        sup = serveur.compacter({'type': 'supervision', 'tour': 1, 'decision': 'rechercher', 'raison': 'r',
                                 'couverture': [{'id': 'Q1', 'statut': 'partielle', 'question': 'Q', 'manque': 'm'}],
                                 'relances': [{'id': 'Q1', 'requetes': ['x'], 'question': 'Q'}]})
        self.assertEqual((sup['couverture'], sup['relances']), ([{'id': 'Q1', 'statut': 'partielle'}], ['Q1']))
        self.assertEqual(serveur.compacter({'type': 'compression', 'id': 'Q2', 'notes': [1, 2]}), {'type': 'compression', 'id': 'Q2', 'notes': 2})
        self.assertEqual(serveur.compacter({'type': 'section', 'id': 'Q1', 'texte': '### Partie', 'jetons': {}}),
                         {'type': 'section', 'id': 'Q1', 'texte': '### Partie'})

    def test_resultat(self):
        res = {'reponse': 'R [1].', 'limites': ['l'], 'sources': [{'numero': 1, 'url': 'u', 'titre': 't', 'favorisee': True}],
               'statistiques': {'duree_s': 3.2, 'appels_qwen': 2, 'pages_lues': 5, 'raison_arret': 'réponse rédigée'}}
        self.assertEqual(serveur.resultat_outil(res, 'web'), {
            'mode': 'web', 'reponse': 'R [1].', 'limites': ['l'], 'sources': [{'numero': 1, 'url': 'u', 'titre': 't'}],
            'duree_s': 3.2, 'appels': 2, 'pages_lues': 5, 'arret': 'réponse rédigée'})
        avec = serveur.resultat_outil({**res, 'sources': [{'numero': 1, 'url': 'u', 'titre': 't', 'icone': 'data:image/png;base64,AA'}]}, 'web')
        self.assertEqual(avec['sources'][0]['icone'], 'data:image/png;base64,AA')
        vide = serveur.resultat_outil({'reponse': '', 'statistiques': {'raison_arret': 'erreur : Qwen injoignable'}}, 'web')
        self.assertEqual(vide['erreur'], 'erreur : Qwen injoignable')


class AppelMcp(unittest.TestCase):
    def setUp(self):
        # Un verrou neuf par test : un asyncio.Semaphore qui a fait attendre reste lié à la boucle de ce test-là
        # (chaque test a la sienne, asyncio.run) ; en service, il n'y a qu'une boucle.
        remplacement = mock.patch.object(serveur, 'place', asyncio.Semaphore(1))
        remplacement.start()
        self.addCleanup(remplacement.stop)

    def appeler(self, executer, arguments=None, meta=None):
        async def tout():
            recus = []

            async def progression(avance, total, message):
                recus.append(json.loads(message))

            with mock.patch.object(serveur, 'QWEN_URL', 'http://qwen/v1'), mock.patch.object(serveur, 'QWEN_CLE', 'cle'), \
                    mock.patch.object(serveur.graphe, 'executer', executer):
                async with create_connected_server_and_client_session(serveur.serveur._mcp_server) as client:
                    outils = await client.list_tools()
                    r = await client.call_tool('recherche_web', arguments or {'question': ' Dernière  version de Rust ? ',
                                                                              'profondeur': 'web'},
                                               progress_callback=progression, meta=meta)
            return outils, r, recus
        return asyncio.run(tout())

    def test_outil_decrit_et_appele(self):
        vu = {}

        async def executer(mode, ctx, question, emettre):
            vu.update(mode=mode, question=question, clarifier=ctx.clarifier, filtre=ctx.filtre, reflexion=ctx.reflexion)
            await emettre({'type': 'planification', 'requetes': ['rust latest version'], 'raison': 'x', 'jetons': {}})
            await emettre({'type': 'reflexion'})
            await emettre({'type': 'texte', 'delta': 'La 1.99 [1].'})
            return {'reponse': 'La 1.99 [1].\n\n**Sources**', 'limites': [], 'sources': [{'numero': 1, 'url': 'https://r.org', 'titre': 'Rust'}],
                    'statistiques': {'duree_s': 1.0, 'appels_qwen': 2, 'pages_lues': 5, 'raison_arret': 'réponse rédigée'}}
        outils, r, recus = self.appeler(executer)
        outil = outils.tools[0]
        self.assertEqual(outil.name, 'recherche_web')
        self.assertEqual(outil.inputSchema['properties']['profondeur']['enum'], ['web', 'approfondie', 'tres_approfondie'])
        self.assertIn('question complète et autonome', outil.inputSchema['properties']['question']['description'])
        self.assertEqual(vu, {'mode': 'web', 'question': 'Dernière version de Rust ?', 'clarifier': False, 'filtre': True, 'reflexion': False})
        self.assertEqual(recus, [{'type': 'planification', 'requetes': ['rust latest version']}, {'type': 'texte', 'delta': 'La 1.99 [1].'}])
        self.assertFalse(r.isError)
        sortie = json.loads(r.content[0].text)
        self.assertEqual((sortie['mode'], sortie['sources'][0]['url'], sortie['appels']), ('web', 'https://r.org', 2))

    def test_reflexion_transmise_par_l_orchestrateur(self):
        vu = {}

        async def executer(mode, ctx, question, emettre):
            vu['reflexion'] = ctx.reflexion
            return {'reponse': 'R.', 'statistiques': {}}
        self.appeler(executer, meta={'observatoire': {'reflexion': True}})
        self.assertTrue(vu['reflexion'])

    def test_profondeur_inconnue_refusee(self):
        async def executer(*_):
            raise AssertionError('jamais appelé')
        _, r, _ = self.appeler(executer, {'question': 'q', 'profondeur': 'extreme'})
        self.assertTrue(r.isError)

    def test_une_recherche_a_la_fois_les_autres_attendent_leur_tour(self):
        async def executer(profondeur, rctx, question, emettre):
            await emettre({'type': 'redaction_debut'})
            return {'reponse': f'R {question}', 'sources': [], 'limites': [], 'statistiques': {}}

        async def tout():
            progressions = []

            async def recue(_avance, _total, message):
                progressions.append(json.loads(message)['type'])
            await serveur.place.acquire()
            with mock.patch.object(serveur, 'QWEN_URL', 'u'), mock.patch.object(serveur, 'QWEN_CLE', 'c'), \
                    mock.patch.object(serveur.graphe, 'executer', executer):
                async with create_connected_server_and_client_session(serveur.serveur._mcp_server) as client:
                    appel = asyncio.create_task(client.call_tool('recherche_web', {'question': 'q', 'profondeur': 'web'},
                                                                 progress_callback=recue))
                    for _ in range(100):
                        if progressions:
                            break
                        await asyncio.sleep(0.01)
                    self.assertFalse(appel.done(), 'attend que la place se libère')
                    serveur.place.release()
                    r = await asyncio.wait_for(appel, 5)
            return json.loads(r.content[0].text), progressions
        resultat, progressions = asyncio.run(tout())
        self.assertEqual(resultat['reponse'], 'R q')
        self.assertEqual(progressions, ['attente', 'redaction_debut'])
        self.assertFalse(serveur.place.locked())

    def test_attente_trop_longue_refusee(self):
        async def executer(*_):
            raise AssertionError('jamais appelé')

        async def tout():
            await serveur.place.acquire()
            try:
                with mock.patch.object(serveur, 'QWEN_URL', 'u'), mock.patch.object(serveur, 'QWEN_CLE', 'c'), \
                        mock.patch.object(serveur, 'ATTENTE_MAX', 0.05), mock.patch.object(serveur.graphe, 'executer', executer):
                    async with create_connected_server_and_client_session(serveur.serveur._mcp_server) as client:
                        return await client.call_tool('recherche_web', {'question': 'q', 'profondeur': 'web'})
            finally:
                serveur.place.release()
        r = asyncio.run(tout())
        self.assertEqual(json.loads(r.content[0].text)['erreur'], serveur.OCCUPE)
        self.assertEqual(serveur.en_cours, {})


class Annulation(unittest.TestCase):
    def test_annuler_n_arrete_que_l_appel_designe(self):
        class Requete:
            def __init__(self, corps):
                self.corps = corps

            async def json(self):
                if self.corps is None:
                    raise ValueError('pas de JSON')
                return self.corps

        async def tout():
            async def longue():
                await asyncio.sleep(30)
            a, b = asyncio.create_task(longue()), asyncio.create_task(longue())
            serveur.en_cours.update({'a': a, 'b': b})
            try:
                sans = await serveur.annuler(Requete(None))
                inconnu = await serveur.annuler(Requete({'appel': 'z'}))
                r1 = await serveur.annuler(Requete({'appel': 'a'}))
                await asyncio.sleep(0)
                etats = (a.cancelled(), b.cancelled())
            finally:
                serveur.en_cours.clear()
                b.cancel()
            return [json.loads(x.body) for x in (sans, inconnu, r1)], etats
        reponses, etats = asyncio.run(tout())
        self.assertEqual(reponses, [{'annulee': False}, {'annulee': False}, {'annulee': True}])
        self.assertEqual(etats, (True, False), 'la recherche de l’autre appel continue')


class Jeton(unittest.TestCase):
    def test_sans_jeton_refuse(self):
        from starlette.testclient import TestClient
        with mock.patch.object(serveur, 'JETON', 'secret'):
            client = TestClient(serveur.application())
            self.assertEqual(client.post('/mcp', json={}).status_code, 401)
            self.assertEqual(client.post('/mcp', json={}, headers={'Authorization': 'Bearer faux'}).status_code, 401)
            self.assertEqual(client.post('/annuler').status_code, 401, 'annuler demande aussi le jeton')
            self.assertEqual(client.get('/sante').status_code, 200)

    def test_appele_sous_son_nom_docker(self):
        from starlette.testclient import TestClient
        initialisation = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'essai', 'version': '1'}}}
        entetes = {'Authorization': 'Bearer secret', 'Accept': 'application/json, text/event-stream'}
        with mock.patch.object(serveur, 'JETON', 'secret'):
            # Le gestionnaire de sessions MCP ne démarre qu'une fois par application : un seul client, deux en-têtes Host.
            with TestClient(serveur.application(), base_url='http://recherche:8080') as client:
                self.assertEqual(client.post('/mcp', json=initialisation, headers=entetes).status_code, 200)
                ailleurs = client.post('/mcp', json=initialisation, headers={**entetes, 'Host': 'ailleurs.example'})
                self.assertNotEqual(ailleurs.status_code, 200, 'nom d’hôte inconnu refusé')


if __name__ == '__main__':
    unittest.main()
