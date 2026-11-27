"""Les deux graphes de bout en bout, avec un faux Qwen et un faux service de recherche (aucun réseau)."""
import asyncio
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

import httpx

import graphe


def flux_sse(texte: str, fin: str = 'stop', reflexion: str = '') -> bytes:
    """Réponse en flux comme vLLM/LiteLLM : morceaux de 7 caractères, raison de fin, usage, [DONE]."""
    morceaux = [{'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': ''}}]}]
    if reflexion:
        morceaux.append({'choices': [{'index': 0, 'delta': {'reasoning_content': reflexion}}]})
    morceaux += [{'choices': [{'index': 0, 'delta': {'content': texte[i:i + 7]}}]} for i in range(0, len(texte), 7)]
    morceaux += [{'choices': [{'index': 0, 'delta': {}, 'finish_reason': fin}]},
                 {'choices': [{'index': 0, 'delta': {}}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}]
    return (''.join(f'data: {json.dumps(m)}\n\n' for m in morceaux) + 'data: [DONE]\n\n').encode()


def faux_qwen(reponses: dict, appels: list):
    """Réponse JSON selon l'étape (nom du schéma) ; les demandes reçues sont gardées dans « appels ». La réponse finale
    (sans schéma) est rendue en flux SSE si elle est demandée ainsi."""
    def repondre(request: httpx.Request) -> httpx.Response:
        corps = json.loads(request.content)
        # Sans schéma : texte libre (réponse finale, section ou synthèse du rapport, reconnues à leur consigne).
        if 'response_format' in corps:
            etape = corps['response_format']['json_schema']['name']
        else:
            systeme = corps['messages'][0]['content']
            etape = ('section' if systeme.startswith('Tu écris une section') else
                     'synthese' if systeme.startswith('Tu écris la synthèse') else 'redaction')
        appels.append(corps)
        contenu = reponses[etape](corps) if callable(reponses[etape]) else reponses[etape]
        texte = contenu if isinstance(contenu, str) and 'response_format' not in corps else json.dumps(contenu)
        if corps.get('stream'):
            return httpx.Response(200, content=flux_sse(texte), headers={'Content-Type': 'text/event-stream'})
        return httpx.Response(200, json={'choices': [{'message': {'content': texte}, 'finish_reason': 'stop'}],
                                         'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})
    return httpx.MockTransport(repondre)


def sans_texte(evenements: list) -> list[str]:
    """Types d'événements, sans les morceaux de la réponse en flux."""
    return [e['type'] for e in evenements if e['type'] != 'texte']


def faux_service(recherches: list):
    def repondre(request: httpx.Request) -> httpx.Response:
        corps = json.loads(request.content)
        recherches.append(corps)
        return httpx.Response(200, json={
            'pages': [{'url': 'https://docs.docker.com/memoire', 'titre': 'Docker', 'etat': 'lue', 'numero': 1, 'groupe': 'favorisee', 'gardes': 2,
                       'icone': 'data:image/png;base64,iVBORw0KGgo='},
                      {'url': 'https://blog.exemple.fr/x', 'titre': 'Blog', 'etat': 'lue', 'numero': 2, 'groupe': 'autre', 'gardes': 0},
                      {'url': 'https://lent.exemple.fr/', 'titre': 'Lent', 'etat': 'delai', 'erreur': 'trop long', 'groupe': 'autre'}],
            'contexte': {'texte': 'Sources :\n[1] Docker — https://docs.docker.com/memoire\n<<<PASSAGE [1]>>>\nUtilisez --memory.\n<<<FIN DU PASSAGE>>>',
                         'jetons': 40},
            'passages': [{'numero': 1, 'position': 0, 'jetons': 30, 'section': 'Limites', 'texte': 'Utilisez --memory=512m.'},
                         {'numero': 1, 'position': 1, 'jetons': 30, 'section': '', 'texte': 'En rootless, il faut cgroup v2.'}],
            'avertissements': []})
    return httpx.MockTransport(repondre)


def lancer(mode: str, reponses: dict, filtre: bool = True, clarifier: bool = False):
    async def tout():
        appels, recherches, evenements = [], [], []
        async with httpx.AsyncClient(transport=faux_qwen(reponses, appels)) as qwen, \
                httpx.AsyncClient(transport=faux_service(recherches), base_url='http://service') as web:
            ctx = graphe.RechercheContext(qwen_url='http://qwen/v1', qwen_cle='cle', modele='qwen', http=qwen, web=web, reflexion=False,
                                          filtre=filtre, clarifier=clarifier,
                                          compteurs=graphe.Compteurs(debut=asyncio.get_running_loop().time()))

            async def emettre(e):
                evenements.append(e)

            resultat = await graphe.executer(mode, ctx, 'Comment limiter la mémoire d’un conteneur Docker rootless ?', emettre)
        return resultat, evenements, appels, recherches
    return asyncio.run(tout())


PLAN = {'recherche_necessaire': True, 'raison': 'technique', 'requetes': ['docker rootless memory limit', 'docker rootless memory limit']}


class Planification(unittest.TestCase):
    def test_theme_et_sites(self):
        self.assertEqual(graphe.theme_valide('administratif'), 'administratif')
        self.assertEqual(graphe.theme_valide('inconnu'), 'autre')
        self.assertEqual(graphe.theme_valide(None), 'autre')
        self.assertEqual(graphe.sites_valides(['https://www.FIFA.com/fr/x', 'git-scm.com', 'troisieme.org']), ['fifa.com', 'git-scm.com'])
        self.assertEqual(graphe.sites_valides(['pas un site', 7, 'a b.com']), [])
        self.assertEqual(graphe.sites_valides('fifa.com'), [])
        self.assertIn('sites_officiels', graphe.SCHEMA_PLAN['properties'])
        self.assertEqual(graphe.SCHEMA_PLAN['properties']['theme']['enum'][-1], 'autre')


class Outils(unittest.TestCase):
    def test_citations_verifiees(self):
        self.assertEqual(graphe.verifier_citations('A [1], B [3], C [12].', {1, 12}), ('A [1], B [source inconnue], C [12].', 1))
        self.assertEqual(graphe.verifier_citations('Voir [1, 2, 5] et [3; 1].', {1, 5}),
                         ('Voir [1][source inconnue][5] et [source inconnue][1].', 2))
        self.assertEqual(graphe.verifier_citations('liste [a, b] et tableau[0]', {1}), ('liste [a, b] et tableau[0]', 0))
        self.assertEqual(graphe.verifier_citations('Code `x[3]` et\n```py\nprint(a[2])\n```\nfin [4].', set()),
                         ('Code `x[3]` et\n```py\nprint(a[2])\n```\nfin [source inconnue].', 1))

    def test_requetes(self):
        self.assertEqual(graphe.requetes_valides([' a  b ', 'A B', '', 'x' * 151, 'c', 'd', 'e']), ['a b', 'c', 'd'])
        self.assertEqual(graphe.requetes_valides('pas une liste'), [])

    def test_lots(self):
        passages = [{'jetons': 1000}, {'jetons': 1000}, {'jetons': 1000}, {'jetons': 2600}, {'jetons': 10}, {'jetons': 10}]
        self.assertEqual([len(l) for l in graphe.lots_de(passages)], [2, 1, 1])


class Web(unittest.TestCase):
    def test_une_recherche_puis_une_reponse_citee(self):
        resultat, evenements, appels, recherches = lancer('web', {
            'planification': PLAN, 'redaction': 'Utilisez `--memory` [1], voir aussi [2] et [9].'})
        self.assertEqual(sans_texte(evenements), ['planification', 'recherche', 'redaction_debut', 'redaction'])
        # La réponse arrive mot à mot : les morceaux mis bout à bout donnent le texte de Qwen, avant vérification.
        self.assertEqual(''.join(e['delta'] for e in evenements if e['type'] == 'texte'),
                         'Utilisez `--memory` [1], voir aussi [2] et [9].')
        self.assertTrue(appels[1]['stream'])
        self.assertEqual(resultat['statistiques']['jetons_par_etape']['redaction']['entree'], 100)
        self.assertEqual(len(appels), 2)
        self.assertEqual(recherches[0]['requetes'], ['docker rootless memory limit'])
        self.assertTrue(recherches[0]['filtre'])
        # Le contexte cité du service part tel quel ; seules les sources ayant des passages gardés sont citables.
        self.assertIn('Utilisez --memory.', appels[1]['messages'][1]['content'])
        self.assertNotIn('response_format', appels[1], 'réponse finale en texte libre')
        self.assertEqual(resultat['reponse'], 'Utilisez `--memory` [1], voir aussi [source inconnue] et [source inconnue].'
                         '\n\n**Sources**\n\n- [1] [Docker](<https://docs.docker.com/memoire>)')
        self.assertEqual(resultat['citations_invalides'], 2)
        self.assertEqual([s['numero'] for s in resultat['sources']], [1, 2])
        self.assertTrue(resultat['sources'][0]['favorisee'])
        self.assertEqual(resultat['sources'][0]['icone'], 'data:image/png;base64,iVBORw0KGgo=', 'icône du site gardée avec la source')
        self.assertIsNone(resultat['sources'][1]['icone'])
        self.assertIn('Page non lue ou incomplète : https://lent.exemple.fr/ (trop long)', resultat['limites'])
        self.assertEqual(resultat['statistiques']['appels_qwen'], 2)

    def test_pages_suivantes_si_rien_d_utile(self):
        async def tout():
            recherches, appels = [], []

            def service(request):
                corps = json.loads(request.content)
                recherches.append(corps)
                premier = len(recherches) == 1
                url = 'https://vide.fr/' if premier else 'https://utile.fr/'
                return httpx.Response(200, json={'pages': [{'url': url, 'titre': 'T', 'etat': 'lue', 'numero': 1, 'gardes': 0 if premier else 1}],
                                                 'contexte': {'texte': '' if premier else 'Sources :\n[1] T — https://utile.fr/', 'jetons': 10}})
            async with httpx.AsyncClient(transport=faux_qwen({'planification': PLAN, 'redaction': 'Oui [1].'}, appels)) as qwen, \
                    httpx.AsyncClient(transport=httpx.MockTransport(service), base_url='http://service') as web:
                ctx = graphe.RechercheContext(qwen_url='http://qwen/v1', qwen_cle='c', modele='q', http=qwen, web=web, reflexion=False,
                                              filtre=True, compteurs=graphe.Compteurs(debut=asyncio.get_running_loop().time()))
                evenements = []

                async def emettre(e):
                    evenements.append(e)
                return await graphe.executer('web', ctx, 'question', emettre), recherches, appels, evenements
        resultat, recherches, appels, evenements = asyncio.run(tout())
        self.assertEqual(len(recherches), 2)
        self.assertEqual(recherches[1]['exclure'], ['https://vide.fr/'])
        self.assertEqual(len(appels), 2, 'aucun appel à Qwen de plus')
        self.assertEqual([e['iteration'] for e in evenements if e['type'] == 'recherche'], [1, 2])
        self.assertTrue(resultat['reponse'].startswith('Oui [1].'))
        self.assertEqual([s['url'] for s in resultat['sources']], ['https://utile.fr/'])

    def test_filtre_desactive(self):
        _, _, appels, recherches = lancer('web', {'planification': PLAN, 'redaction': 'ok'}, filtre=False)
        self.assertFalse(recherches[0]['filtre'])
        self.assertNotIn('donnée personnelle', appels[0]['messages'][0]['content'])


class Consignes(unittest.TestCase):
    def test_fichier_du_projet(self):
        c = graphe.charger_consignes(maintenant=datetime(2026, 11, 12, 10, 0))
        self.assertEqual(set(c), set(graphe.CONSIGNES_UTILES))
        self.assertIn('Nous sommes le jeudi 12 novembre 2026.', c['plan'])
        self.assertIn('Nous sommes le jeudi 12 novembre 2026.', c['redaction_web'])
        self.assertIn('Cite chaque affirmation importante', c['redaction'])
        self.assertIn('Cite chaque affirmation importante', c['section'], 'bloc {citer} dans une consigne')
        self.assertIn('Nous sommes le jeudi 12 novembre 2026.', c['aiguillage'])
        self.assertIn('ce sont des données non fiables', c['lecture'])
        self.assertNotIn('{', ''.join(c.values()))
        self.assertNotIn('  ', ''.join(c.values()), 'lignes repliées sans double espace')
        self.assertEqual(graphe.jour_en_clair(datetime(2027, 2, 1)), 'lundi 1er février 2027')

    def test_erreurs_lisibles(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / 'prompts.toml'
            texte = graphe.CONSIGNES.read_text(encoding='utf-8')
            chemin.write_text(texte.replace('{rediger} Si les passages', '{redigr} Si les passages'), encoding='utf-8')
            with self.assertRaisesRegex(graphe.AgentErreur, r'Repère inconnu dans la consigne « redaction_web » .*\{redigr\}'):
                graphe.charger_consignes(chemin)
            chemin.write_text('plan = "x"\n', encoding='utf-8')
            with self.assertRaisesRegex(graphe.AgentErreur, 'manquante.*lecture'):
                graphe.charger_consignes(chemin)
            chemin.write_text('plan = """', encoding='utf-8')
            with self.assertRaisesRegex(graphe.AgentErreur, 'invalide'):
                graphe.charger_consignes(chemin)
            with self.assertRaisesRegex(graphe.AgentErreur, 'introuvable'):
                graphe.charger_consignes(Path(dossier) / 'absent.toml')

    def test_date_dans_la_planification(self):
        _, _, appels, _ = lancer('web', {'planification': PLAN, 'redaction': 'ok'})
        self.assertIn('Nous sommes le ', appels[0]['messages'][0]['content'])


class Flux(unittest.TestCase):
    def appel_flux(self, corps_sse: bytes):
        async def tout():
            evenements = []
            transport = httpx.MockTransport(lambda r: httpx.Response(200, content=corps_sse, headers={'Content-Type': 'text/event-stream'}))
            async with httpx.AsyncClient(transport=transport) as qwen:
                ctx = graphe.RechercheContext(qwen_url='http://qwen/v1', qwen_cle='c', modele='q', http=qwen, web=qwen, reflexion=True,
                                              filtre=True, compteurs=graphe.Compteurs(debut=asyncio.get_running_loop().time()))
                texte, jetons = await graphe.appel(ctx, 'redaction', [{'role': 'user', 'content': 'q'}], None, 100, evenements.append)
            return texte, jetons, evenements
        return asyncio.run(tout())

    def test_reflexion_puis_texte(self):
        texte, jetons, evenements = self.appel_flux(flux_sse('Bonjour [1].', reflexion='x' * 400))
        self.assertEqual(texte, 'Bonjour [1].')
        self.assertEqual(evenements[0], {'type': 'reflexion'})
        self.assertEqual(sum(e['type'] == 'reflexion' for e in evenements), 1)
        self.assertEqual((jetons['entree'], jetons['sortie'], jetons['reflexion']), (100, 20, 100))
        self.assertNotIn('coupee', jetons)

    def test_reponse_coupee_gardee(self):
        texte, jetons, _ = self.appel_flux(flux_sse('Début de réponse', fin='length'))
        self.assertEqual(texte, 'Début de réponse')
        self.assertEqual(jetons['coupee'], 100 + graphe.REFLEXION_SUPPLEMENT)

    def test_flux_vide(self):
        with self.assertRaisesRegex(graphe.AgentErreur, 'vide'):
            self.appel_flux(flux_sse(''))


class Sources(unittest.TestCase):
    def test_seules_les_sources_citees(self):
        sources = {'u1': {'numero': 1, 'url': 'https://a.fr/x (1)', 'titre': 'Titre [avec] crochets'},
                   'u2': {'numero': 2, 'url': 'https://b.fr', 'titre': 'B'}, 'u3': {'numero': 3, 'url': 'https://c.fr', 'titre': ''}}
        self.assertEqual(graphe.avec_sources('Voir [3][1] et `x[2]`.', sources),
                         'Voir [3][1] et `x[2]`.\n\n**Sources**\n\n- [1] [Titre avec crochets](<https://a.fr/x (1)>)\n- [3] [https://c.fr](<https://c.fr>)')
        self.assertEqual(graphe.avec_sources('Rien de cité.', sources), 'Rien de cité.')


class Relance(unittest.TestCase):
    def test_recherche_vide_relancee_une_fois(self):
        async def tout():
            appels = []

            def repondre(request):
                appels.append(1)
                return httpx.Response(200, json={'pages': [] if len(appels) == 1 else [{'url': 'https://a.fr', 'etat': 'lue', 'numero': 1}]})
            async with httpx.AsyncClient(transport=httpx.MockTransport(repondre), base_url='http://service') as web:
                ctx = graphe.RechercheContext(qwen_url='', qwen_cle='', modele='', http=web, web=web, reflexion=False, filtre=True,
                                              compteurs=graphe.Compteurs(debut=0))
                return await graphe.recherche_multi(ctx, 'q', ['q'], [], 1000, False), appels
        resultat, appels = asyncio.run(tout())
        self.assertEqual(len(appels), 2)
        self.assertEqual(resultat['avertissements'], ['Aucun résultat au premier essai : recherche relancée une fois.'])


class Approfondie(unittest.TestCase):
    def test_lecteurs_faits_verification_et_redaction(self):
        lecture = {'faits': [{'texte': 'L’option --memory limite la mémoire.', 'references': ['S1.0']},
                             {'texte': 'Fait inventé.', 'references': ['S9.9']}],
                   'contradictions': [], 'sans_reponse': ['cas de Podman']}
        resultat, evenements, appels, recherches = lancer('approfondie', {
            'planification': PLAN, 'lecture': lecture,
            'verification': {'decision': 'repondre', 'raison': 'suffisant', 'sources_coherentes': True,
                             'informations_manquantes': [], 'nouvelles_requetes': []},
            'redaction': 'Utilisez --memory [1] (source inconnue [2]).'})
        self.assertEqual(sans_texte(evenements), ['planification', 'recherche', 'lecture', 'verification', 'arret', 'redaction_debut',
                                                  'redaction'])
        self.assertFalse(appels[1].get('stream'), 'les étapes intermédiaires ne sont pas en flux')
        lu = next(e for e in evenements if e['type'] == 'lecture')
        self.assertEqual((len(lu['faits']), lu['rejetes']), (1, 1))
        self.assertEqual(resultat['faits'][0]['sources'], [1])
        self.assertEqual(resultat['reponse'], 'Utilisez --memory [1] (source inconnue [source inconnue]).'
                         '\n\n**Sources**\n\n- [1] [Docker](<https://docs.docker.com/memoire>)')
        self.assertEqual(resultat['statistiques']['appels_qwen'], 4)
        self.assertTrue(recherches[0]['passages'])
        # Le lecteur ne voit que son lot, délimiteurs compris.
        self.assertIn('<<<PASSAGE S1.0 — section : Limites>>>', appels[1]['messages'][1]['content'])

    def test_nouvelle_recherche_puis_limite_de_tours(self):
        tour = {'n': 0}

        def lecture(_):
            tour['n'] += 1
            return {'faits': [{'texte': f'Fait {tour["n"]}', 'references': ['S1.0']}], 'contradictions': [], 'sans_reponse': []}
        resultat, evenements, _, recherches = lancer('approfondie', {
            'planification': PLAN, 'lecture': lecture,
            'verification': {'decision': 'rechercher', 'raison': 'manque', 'sources_coherentes': True,
                             'informations_manquantes': ['cgroup'], 'nouvelles_requetes': ['cgroup v2 rootless delegation']},
            'redaction': 'Réponse [1].'})
        self.assertEqual(len(recherches), 2)
        self.assertEqual(recherches[1]['requetes'], ['cgroup v2 rootless delegation'])
        self.assertIn('https://docs.docker.com/memoire', recherches[1]['exclure'])
        self.assertEqual(resultat['statistiques']['raison_arret'], 'nombre maximal de recherches atteint (2)')

    def test_premier_tour_vide_reformule(self):
        tour = {'n': 0}

        def lecture(_):
            tour['n'] += 1
            faits = [] if tour['n'] == 1 else [{'texte': 'Un index inversé relie chaque mot aux documents.', 'references': ['S1.0']}]
            return {'faits': faits, 'contradictions': [], 'sans_reponse': []}
        resultat, evenements, _, recherches = lancer('approfondie', {
            'planification': PLAN, 'lecture': lecture,
            'verification': {'decision': 'rechercher', 'raison': 'rien trouvé', 'sources_coherentes': True,
                             'informations_manquantes': [], 'nouvelles_requetes': ['inverted index tutorial']},
            'redaction': 'Réponse [1].'})
        self.assertEqual(len(recherches), 2, 'un second tour après un premier tour sans fait')
        self.assertEqual(len(resultat['faits']), 1)

    def test_erreur_de_qwen(self):
        resultat, evenements, _, _ = lancer('approfondie', {'planification': lambda _: 'pas un objet'})
        self.assertEqual(evenements[-1], {'type': 'erreur', 'message': 'Réponse de Qwen illisible (JSON attendu).'})
        self.assertTrue(resultat['statistiques']['raison_arret'].startswith('erreur'))



CAHIER = {'objectif': 'Comparer Docker et Podman pour limiter la mémoire en rootless.',
          'sous_questions': [{'question': 'Limiter la mémoire avec Docker rootless', 'requetes': ['docker rootless memory limit']},
                             {'question': 'Limiter la mémoire avec Podman rootless', 'requetes': ['podman rootless memory limit']},
                             {'question': '', 'requetes': ['sous-question vide ignorée']}],
          'criteres': ['options exactes', 'prérequis cgroup v2']}


def lecture_par_sous_question(corps):
    question = corps['messages'][1]['content']
    outil = 'Podman' if question.startswith('Question : Limiter la mémoire avec Podman') else 'Docker'
    return {'faits': [{'texte': f'{outil} : utilisez --memory.', 'references': ['S1.0']}, {'texte': 'Inventé.', 'references': ['S7.1']}],
            'contradictions': [], 'sans_reponse': [f'{outil} : cas de cgroup v1']}


def supervision(*decisions):
    """Réponses successives du superviseur."""
    suite = iter(decisions)
    return lambda corps: next(suite)


def compression(corps):
    """Une note valide par sous-question, et une note qui cite une source absente des faits (rejetée)."""
    return {'notes': [{'texte': 'Option --memory pour limiter la mémoire.', 'sources': [1]}, {'texte': 'Inventée.', 'sources': [9]}],
            'contradictions': [], 'sans_reponse': ['cgroup v1']}


def section(corps):
    sous_question = corps['messages'][1]['content'].split('Sous-question de cette section : ')[1].split('\n')[0]
    return f'## {sous_question}\nUtilisez --memory [1], voir aussi [7].'


ETAPES_FINALES = {'compression': compression, 'section': section, 'synthese': 'En bref : --memory [1].'}


class TresApprofondie(unittest.TestCase):
    def test_cahier_chercheurs_paralleles_relance_et_rapport(self):
        relancer = {'couverture': [{'id': 'Q1', 'statut': 'couverte', 'manque': ''}, {'id': 'Q2', 'statut': 'partielle', 'manque': 'cgroup'}],
                    'decision': 'rechercher', 'raison': 'Q2 incomplète',
                    'relances': [{'id': 'Q2', 'requetes': ['podman rootless memory limit', 'podman cgroup v2 delegation']},
                                 {'id': 'Q9', 'requetes': ['id inconnu']}]}
        repondre = {'couverture': [{'id': 'Q1', 'statut': 'couverte', 'manque': ''}, {'id': 'Q2', 'statut': 'couverte', 'manque': ''}],
                    'decision': 'repondre', 'raison': 'complet', 'relances': []}
        resultat, evenements, appels, recherches = lancer('tres_approfondie', {
            'cahier': CAHIER, 'lecture': lecture_par_sous_question, 'supervision': supervision(relancer, repondre), **ETAPES_FINALES})
        types = sans_texte(evenements)
        self.assertEqual(types[:10], ['cahier', 'chercheur_debut', 'chercheur_debut', 'chercheur', 'chercheur', 'supervision',
                                      'chercheur_debut', 'chercheur', 'supervision', 'arret'])
        # Compressions puis sections en parallèle (ordre d'arrivée libre), puis la synthèse.
        self.assertEqual(sorted(types[10:14]), ['compression', 'compression', 'section', 'section'])
        self.assertEqual(types[10:12], ['compression', 'compression'])
        self.assertEqual(types[14:], ['redaction_debut', 'redaction'])
        cahier = evenements[0]
        self.assertEqual([q['id'] for q in cahier['sous_questions']], ['Q1', 'Q2'], 'sous-question vide ignorée')
        # Tour 1 : une recherche par sous-question, la sous-question servant au classement des passages.
        self.assertEqual(sorted(r['requete'] for r in recherches[:2]),
                         ['Limiter la mémoire avec Docker rootless', 'Limiter la mémoire avec Podman rootless'])
        # Tour 2 : seulement Q2, avec la requête nouvelle (celle déjà faite est retirée), pages déjà essayées exclues.
        self.assertEqual(len(recherches), 3)
        self.assertEqual(recherches[2]['requetes'], ['podman cgroup v2 delegation'])
        self.assertIn('https://docs.docker.com/memoire', recherches[2]['exclure'])
        sup = [e for e in evenements if e['type'] == 'supervision'][0]
        self.assertEqual([r['id'] for r in sup['relances']], ['Q2'])
        # Faits rangés par sous-question, fait sans référence valide rejeté ; numéro de source commun aux chercheurs.
        self.assertEqual(sorted((f['sous_question'], f['texte']) for f in resultat['faits']),
                         [('Q1', 'Docker : utilisez --memory.'), ('Q2', 'Podman : utilisez --memory.')])
        self.assertEqual([s['numero'] for s in resultat['sources']], [1, 2])
        # Compression : faits avec leurs sources ; une note qui cite une source hors des faits est rejetée.
        comp = next(e for e in evenements if e['type'] == 'compression')
        self.assertEqual((len(comp['notes']), comp['rejetees'], comp['repli']), (1, 1, False))
        compresseurs = [c for c in appels if c.get('response_format', {}).get('json_schema', {}).get('name') == 'compression']
        self.assertIn('Numéros de source permis : 1', compresseurs[0]['messages'][1]['content'])
        # Sections : écrites à partir des notes, chacune connaît le titre des autres ; titre ramené à ###, citation [7] remplacée.
        sections = [c for c in appels if c['messages'][0]['content'].startswith('Tu écris une section')]
        self.assertEqual(len(sections), 2)
        self.assertIn('Autres sections du rapport (à ne pas traiter ici) :\n- Limiter la mémoire avec Podman rootless',
                      next(c for c in sections if 'section : Limiter la mémoire avec Docker' in c['messages'][1]['content'])['messages'][1]['content'])
        self.assertIn('- Option --memory pour limiter la mémoire. [1]', sections[0]['messages'][1]['content'])
        # Synthèse : écrite en dernier à partir des sections, en flux, placée en tête du rapport.
        synthese = appels[-1]
        self.assertTrue(synthese['stream'])
        self.assertIn('Sections du rapport :\n\n### Limiter la mémoire avec Docker rootless', synthese['messages'][1]['content'])
        self.assertIn('Critères d’une réponse complète :\n- options exactes', synthese['messages'][1]['content'])
        self.assertNotIn('[2] Blog', synthese['messages'][1]['content'], 'source sans fait non proposée')
        self.assertTrue(resultat['reponse'].startswith(
            '## Synthèse\n\nEn bref : --memory [1].\n\n### Limiter la mémoire avec Docker rootless\nUtilisez --memory [1], voir aussi [source inconnue].'
            '\n\n### Limiter la mémoire avec Podman rootless\n'))
        self.assertIn('**Sources**\n\n- [1] [Docker](<https://docs.docker.com/memoire>)', resultat['reponse'])
        self.assertIn('2 citation(s) vers une source non collectée remplacée(s) par « [source inconnue] ».', resultat['limites'])
        # 1 cahier + 2 lecteurs + supervision + 1 lecteur + supervision + 2 compressions + 2 sections + synthèse
        self.assertEqual(resultat['statistiques']['appels_qwen'], 11)
        self.assertEqual(resultat['statistiques']['raison_arret'], 'cahier jugé rempli par le superviseur')
        self.assertEqual(resultat['statistiques']['iterations'], 2)

    def test_compression_sans_note_valide(self):
        resultat, evenements, _, _ = lancer('tres_approfondie', {
            'cahier': CAHIER, 'lecture': lecture_par_sous_question,
            'supervision': {'couverture': [{'id': 'Q1', 'statut': 'couverte', 'manque': ''}, {'id': 'Q2', 'statut': 'couverte', 'manque': ''}],
                            'decision': 'repondre', 'raison': 'ok', 'relances': []},
            **ETAPES_FINALES, 'compression': {'notes': [{'texte': 'Inventée.', 'sources': [9]}], 'contradictions': [], 'sans_reponse': []}})
        comp = [e for e in evenements if e['type'] == 'compression']
        self.assertTrue(all(c['repli'] for c in comp), 'les faits bruts servent de notes')
        self.assertEqual(comp[0]['notes'][0]['sources'], [1])
        self.assertTrue(resultat['reponse'].startswith('## Synthèse'))

    def test_tours_limites_et_relance_inutile(self):
        toujours = {'couverture': [{'id': 'Q1', 'statut': 'absente', 'manque': 'tout'}, {'id': 'Q2', 'statut': 'absente', 'manque': ''}],
                    'decision': 'rechercher', 'raison': 'rien',
                    'relances': [{'id': 'Q1', 'requetes': ['nouvelle requête {n}']}]}
        compteur = {'n': 0}

        def superviseur(_):
            compteur['n'] += 1
            return json.loads(json.dumps(toujours).replace('{n}', str(compteur['n'])))
        resultat, evenements, _, recherches = lancer('tres_approfondie', {
            'cahier': CAHIER, 'lecture': lecture_par_sous_question, 'supervision': superviseur, **ETAPES_FINALES})
        self.assertEqual(len(recherches), 4, '2 au tour 1, puis 1 par relance (tours 2 et 3)')
        self.assertEqual(compteur['n'], 2, 'pas de supervision après le dernier tour')
        self.assertEqual(resultat['statistiques']['raison_arret'], 'nombre maximal de tours atteint (3)')
        self.assertTrue(any(l.startswith('Sous-question pas couverte : Limiter la mémoire avec Podman') for l in resultat['limites']))

        # Relance avec une requête déjà faite : rien de nouveau à chercher, on rédige.
        deja = {**toujours, 'relances': [{'id': 'Q1', 'requetes': ['docker rootless memory limit']}]}
        resultat, _, _, recherches = lancer('tres_approfondie', {
            'cahier': CAHIER, 'lecture': lecture_par_sous_question, 'supervision': deja, **ETAPES_FINALES})
        self.assertEqual(len(recherches), 2)
        self.assertEqual(resultat['statistiques']['raison_arret'], 'aucune relance utile proposée')

    def test_sous_question_pleine_pas_relancee(self):
        def lecture_abondante(corps):
            ids = corps['messages'][1]['content'].split('Identifiants permis : ')[1].split('\n')[0].split(', ')
            n = len(corps['messages'][1]['content'])
            return {'faits': [{'texte': f'Fait {k} de {n}', 'references': [ids[0]]} for k in range(12)], 'contradictions': [], 'sans_reponse': []}
        relancer = {'couverture': [{'id': 'Q1', 'statut': 'partielle', 'manque': ''}, {'id': 'Q2', 'statut': 'partielle', 'manque': ''}],
                    'decision': 'rechercher', 'raison': '', 'relances': [{'id': 'Q1', 'requetes': ['autre requête']}]}
        ancien = graphe.FAITS_PAR_SOUS_QUESTION
        graphe.FAITS_PAR_SOUS_QUESTION = 10
        try:
            resultat, _, _, recherches = lancer('tres_approfondie', {
                'cahier': CAHIER, 'lecture': lecture_abondante, 'supervision': relancer, **ETAPES_FINALES})
        finally:
            graphe.FAITS_PAR_SOUS_QUESTION = ancien
        self.assertEqual(len(recherches), 2, 'Q1 a déjà tous ses faits : pas de relance')
        self.assertEqual(resultat['statistiques']['raison_arret'], 'aucune relance utile proposée')

    def test_aucun_fait_aucune_redaction(self):
        vide = lambda _: {'faits': [], 'contradictions': [], 'sans_reponse': []}   # noqa: E731
        resultat, evenements, appels, _ = lancer('tres_approfondie', {
            'cahier': CAHIER, 'lecture': vide,
            'supervision': {'couverture': [{'id': 'Q1', 'statut': 'absente', 'manque': ''}, {'id': 'Q2', 'statut': 'absente', 'manque': ''}],
                            'decision': 'repondre', 'raison': 'rien', 'relances': []}, **ETAPES_FINALES})
        self.assertEqual(resultat['reponse'], graphe.AUCUNE_INFO)
        self.assertEqual(sans_texte(evenements)[-2:], ['arret', 'redaction'])
        self.assertFalse(any(c['messages'][0]['content'].startswith('Tu écris') for c in appels))

    def test_schema_du_superviseur(self):
        schema = graphe.schema_supervision(['Q1', 'Q2'])
        self.assertEqual(schema['properties']['couverture']['minItems'], 2)
        self.assertEqual(schema['properties']['relances']['items']['properties']['id']['enum'], ['Q1', 'Q2'])

    def test_limites_par_mode(self):
        self.assertEqual(graphe.limites_publiques('approfondie')['appels'], 9)
        self.assertEqual(graphe.limites_publiques('tres_approfondie')['appels'], 34)
        self.assertEqual(graphe.limites_publiques('tres_approfondie')['duree_s'], 600)
        self.assertTrue(graphe.limites_publiques('auto')['auto'])
        self.assertEqual(graphe.finale(3), 7)


class Robustesse(unittest.TestCase):
    def test_lecteur_illisible_la_recherche_continue(self):
        resultat, evenements, appels, _ = lancer('approfondie', {
            'planification': PLAN, 'lecture': lambda _: 'pas un objet',
            'verification': {'decision': 'repondre', 'raison': '', 'sources_coherentes': True, 'informations_manquantes': [],
                             'nouvelles_requetes': []}, 'redaction': 'R.'})
        self.assertNotIn('erreur', [e['type'] for e in evenements])
        self.assertEqual(resultat['reponse'], 'Aucune information fiable n’a été trouvée pour répondre à cette question dans les pages consultées.')

    def test_reflexion_reservee_aux_etapes_qui_decident(self):
        async def tout():
            corps = []

            def repondre(request):
                c = json.loads(request.content); corps.append(c)
                return httpx.Response(200, json={'choices': [{'message': {'content': '{"faits": [], "contradictions": [], "sans_reponse": []}'},
                                                              'finish_reason': 'stop'}], 'usage': {}})
            async with httpx.AsyncClient(transport=httpx.MockTransport(repondre)) as qwen:
                ctx = graphe.RechercheContext(qwen_url='http://q/v1', qwen_cle='c', modele='q', http=qwen, web=qwen, reflexion=True, filtre=True,
                                              compteurs=graphe.Compteurs(debut=asyncio.get_running_loop().time()))
                ctx.consignes = graphe.charger_consignes()
                await graphe.appel(ctx, 'lecture', [{'role': 'user', 'content': 'q'}], graphe.SCHEMA_LECTURE, 1500)
                await graphe.appel(ctx, 'verification', [{'role': 'user', 'content': 'q'}], graphe.SCHEMA_LECTURE, 800)
            return corps
        lecture, verification = asyncio.run(tout())
        self.assertEqual((lecture['chat_template_kwargs']['enable_thinking'], lecture['max_tokens']), (False, 1500))
        self.assertEqual((verification['chat_template_kwargs']['enable_thinking'], verification['max_tokens']), (True, 800 + graphe.REFLEXION_SUPPLEMENT))


class Automatique(unittest.TestCase):
    def test_reponse_directe_sans_recherche(self):
        resultat, evenements, appels, recherches = lancer('auto', {
            'aiguillage': {'mode': 'direct', 'raison': 'écrire du code'}, 'redaction': 'Voici `x[0]` et [1].'})
        self.assertEqual(sans_texte(evenements), ['aiguillage', 'redaction_debut', 'redaction'])
        self.assertEqual(evenements[0]['mode'], 'direct')
        self.assertEqual(recherches, [])
        self.assertEqual(resultat['mode'], 'direct')
        self.assertEqual(resultat['aiguillage'], {'mode': 'direct', 'raison': 'écrire du code', 'clarification': None})
        self.assertEqual(resultat['reponse'], 'Voici `x[0]` et [source inconnue].', 'aucune source en réponse directe')
        self.assertTrue(resultat['limites'][0].startswith('Réponse de Qwen sans recherche Internet'))
        self.assertEqual(resultat['statistiques']['appels_qwen'], 2)
        self.assertTrue(appels[1]['messages'][0]['content'].startswith('Tu réponds en français à la question d’un développeur, avec tes propres connaissances'))

    def test_aiguillage_vers_le_web(self):
        resultat, evenements, appels, recherches = lancer('auto', {
            'aiguillage': {'mode': 'web', 'raison': 'version récente', 'clarification': ''}, 'planification': PLAN, 'redaction': 'Oui [1].'},
            clarifier=True)
        self.assertEqual(sans_texte(evenements), ['aiguillage', 'planification', 'recherche', 'redaction_debut', 'redaction'])
        self.assertEqual(len(recherches), 1)
        self.assertEqual(resultat['mode'], 'web')
        # Une seule occasion de demander une précision : à l'aiguillage, pas de nouveau à la planification.
        self.assertIn('clarification', appels[0]['response_format']['json_schema']['schema']['properties'])
        self.assertNotIn('clarification', appels[1]['response_format']['json_schema']['schema']['properties'])
        self.assertEqual(evenements[0]['limites']['appels'], 2)

    def test_mode_inconnu_ramene_au_web(self):
        ctx_reponse = {'aiguillage': {'mode': 'n_importe_quoi', 'raison': ''}, 'planification': PLAN, 'redaction': 'ok'}
        resultat, _, _, _ = lancer('auto', ctx_reponse)
        self.assertEqual(resultat['mode'], 'web')


class Precision(unittest.TestCase):
    def test_planification_demande_une_precision(self):
        resultat, evenements, appels, recherches = lancer('web', {
            'planification': {**PLAN, 'clarification': 'RGB : les jeux Rouge/Vert/Bleu ou les couleurs ?'}}, clarifier=True)
        self.assertEqual(sans_texte(evenements), ['clarification'])
        self.assertEqual(evenements[0]['question'], 'RGB : les jeux Rouge/Vert/Bleu ou les couleurs ?')
        self.assertEqual(recherches, [])
        self.assertEqual(resultat['clarification'], 'RGB : les jeux Rouge/Vert/Bleu ou les couleurs ?')
        self.assertEqual(resultat['statistiques']['raison_arret'], 'précision demandée')
        self.assertIn('écris dans « clarification » une seule question courte', appels[0]['messages'][0]['content'])
        self.assertEqual(appels[0]['response_format']['json_schema']['schema']['required'][0], 'clarification')

    def test_precision_vide_on_cherche(self):
        resultat, _, _, recherches = lancer('approfondie', {
            'planification': {**PLAN, 'clarification': '  '}, 'lecture': {'faits': [], 'contradictions': [], 'sans_reponse': []},
            'verification': {'decision': 'repondre', 'raison': '', 'sources_coherentes': True, 'informations_manquantes': [],
                             'nouvelles_requetes': []}, 'redaction': 'ok'}, clarifier=True)
        self.assertEqual(len(recherches), 1)
        self.assertIsNone(resultat['clarification'])

    def test_sans_la_case_rien_n_est_demande(self):
        _, _, appels, _ = lancer('web', {'planification': PLAN, 'redaction': 'ok'})
        self.assertNotIn('clarification', appels[0]['response_format']['json_schema']['schema']['properties'])
        self.assertNotIn('« clarification »', appels[0]['messages'][0]['content'])

    def test_cahier_demande_une_precision(self):
        resultat, evenements, _, recherches = lancer('tres_approfondie', {
            'cahier': {**CAHIER, 'clarification': 'Quel système ?'}}, clarifier=True)
        self.assertEqual(sans_texte(evenements), ['clarification'])
        self.assertEqual(recherches, [])
        self.assertEqual(resultat['clarification'], 'Quel système ?')

    def test_aiguillage_demande_une_precision(self):
        resultat, evenements, appels, _ = lancer('auto', {
            'aiguillage': {'mode': 'web', 'raison': '', 'clarification': 'Quel sens ?'}}, clarifier=True)
        self.assertEqual(sans_texte(evenements), ['aiguillage', 'clarification'])
        self.assertEqual(len(appels), 1)
        self.assertEqual(resultat['clarification'], 'Quel sens ?')


if __name__ == '__main__':
    unittest.main()
