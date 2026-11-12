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

    def test_resultat(self):
        res = {'reponse': 'R [1].', 'limites': ['l'], 'sources': [{'numero': 1, 'url': 'u', 'titre': 't', 'favorisee': True}],
               'statistiques': {'duree_s': 3.2, 'appels_qwen': 2, 'pages_lues': 5, 'raison_arret': 'réponse rédigée'}}
        self.assertEqual(serveur.resultat_outil(res, 'web'), {
            'mode': 'web', 'reponse': 'R [1].', 'limites': ['l'], 'sources': [{'numero': 1, 'url': 'u', 'titre': 't'}],
            'duree_s': 3.2, 'appels': 2, 'pages_lues': 5, 'arret': 'réponse rédigée'})
        vide = serveur.resultat_outil({'reponse': '', 'statistiques': {'raison_arret': 'erreur : Qwen injoignable'}}, 'web')
        self.assertEqual(vide['erreur'], 'erreur : Qwen injoignable')


class AppelMcp(unittest.TestCase):
    def appeler(self, executer, arguments=None):
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
                                               progress_callback=progression)
            return outils, r, recus
        return asyncio.run(tout())

    def test_outil_decrit_et_appele(self):
        vu = {}

        async def executer(mode, ctx, question, emettre):
            vu.update(mode=mode, question=question, clarifier=ctx.clarifier, filtre=ctx.filtre)
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
        self.assertEqual(vu, {'mode': 'web', 'question': 'Dernière version de Rust ?', 'clarifier': False, 'filtre': True})
        self.assertEqual(recus, [{'type': 'planification', 'requetes': ['rust latest version']}, {'type': 'texte', 'delta': 'La 1.99 [1].'}])
        self.assertFalse(r.isError)
        sortie = json.loads(r.content[0].text)
        self.assertEqual((sortie['mode'], sortie['sources'][0]['url'], sortie['appels']), ('web', 'https://r.org', 2))

    def test_profondeur_inconnue_refusee(self):
        async def executer(*_):
            raise AssertionError('jamais appelé')
        _, r, _ = self.appeler(executer, {'question': 'q', 'profondeur': 'extreme'})
        self.assertTrue(r.isError)

    def test_une_recherche_a_la_fois(self):
        async def executer(*_):
            raise AssertionError('jamais appelé')

        async def tout():
            await serveur.place.acquire()
            try:
                with mock.patch.object(serveur, 'QWEN_URL', 'u'), mock.patch.object(serveur, 'QWEN_CLE', 'c'), \
                        mock.patch.object(serveur.graphe, 'executer', executer):
                    async with create_connected_server_and_client_session(serveur.serveur._mcp_server) as client:
                        return await client.call_tool('recherche_web', {'question': 'q', 'profondeur': 'web'})
            finally:
                serveur.place.release()
        r = asyncio.run(tout())
        self.assertEqual(json.loads(r.content[0].text)['erreur'], serveur.OCCUPE)


class Annulation(unittest.TestCase):
    def test_annuler_arrete_la_recherche_en_cours(self):
        async def tout():
            async def longue():
                await asyncio.sleep(30)
            tache = asyncio.create_task(longue())
            serveur.en_cours['tache'] = tache
            try:
                r1 = await serveur.annuler(None)
                await asyncio.sleep(0)
                vide = await serveur.annuler(None)
            finally:
                serveur.en_cours.pop('tache', None)
            return json.loads(r1.body), tache.cancelled(), json.loads(vide.body)
        premier, annulee, second = asyncio.run(tout())
        self.assertEqual((premier, annulee), ({'annulee': True}, True))
        self.assertEqual(second, {'annulee': False})


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
