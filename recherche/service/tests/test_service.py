"""Tests du service avec de faux SearXNG et Crawl4AI (httpx.MockTransport) : aucun appel réseau."""
import json
import unittest

import httpx
from fastapi.testclient import TestClient

import garde
from app import app


def faux_moteurs(searxng=None, crawl4ai=None, appels=None):
    appels = appels if appels is not None else []

    def repondre(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        if requete.url.host == "searxng":
            return (searxng or (lambda r: httpx.Response(200, text="OK")))(requete)
        return (crawl4ai or (lambda r: httpx.Response(200, json={"status": "ok"})))(requete)

    return httpx.AsyncClient(transport=httpx.MockTransport(repondre)), appels


def resultats_searxng(requete):
    if requete.url.path == "/healthz":
        return httpx.Response(200, text="OK")
    return httpx.Response(200, json={"results": [
        {"title": "Lunettes  100 % santé", "url": "https://www.python.org/lunettes", "content": "Reste à charge zéro", "engines": ["bing", "qwant"]},
        {"title": "Doublon", "url": "https://www.python.org/lunettes", "content": "x", "engine": "brave"},
        {"title": "Autre page du même site", "url": "https://python.org/autre", "content": "y", "engine": "brave"},
        {"title": "Page FTP", "url": "ftp://exemple.fr/x", "content": "z", "engine": "brave"},
        {"title": "Service-public", "url": "https://www.service-public.fr/lunettes", "content": "Fiche", "engine": "duckduckgo"},
        {"title": "Intranet", "url": "https://intranet.maison.internal/x", "content": "i", "engine": "bing"},
        {"title": "Mutuelle", "url": "https://mutuelle.exemple.fr/", "content": "m", "engine": "bing"},
        {"title": "Quatrième site", "url": "https://quatre.exemple.org/", "content": "q", "engine": "bing"},
    ], "unresponsive_engines": [["startpage", "timeout"]]})


BRUT = "Menu ⏎ Accueil\n\n# Titre\n\nLe 100 % Santé permet un [reste à charge](https://exemple.fr/rac) nul. " + "Texte utile. " * 60


def page_crawl4ai(requete):
    if requete.url.path == "/health":
        return httpx.Response(200, json={"status": "ok"})
    demande = json.loads(requete.content)
    url, params = demande["urls"][0], demande["crawler_config"]["params"]
    if url.startswith("raw:"):
        options = params.get("markdown_generator", {}).get("params", {})
        if options.get("options", {}).get("ignore_links"):
            filtre = options.get("content_filter")
            fit = "Le 100 % Santé permet un reste à charge nul." if filtre and filtre["type"] == "BM25ContentFilter" else ""
            return httpx.Response(200, json={"results": [{"success": True, "markdown": {"raw_markdown": "# Titre\n\nLe 100 % Santé permet un reste à charge nul. " + "Texte utile. " * 60, "fit_markdown": fit}}]})
        return httpx.Response(200, json={"results": [{"success": True, "markdown": {"raw_markdown": "# Titre\n\nLe 100 % Santé permet un [reste à charge](https://exemple.fr/rac) nul. " + "Texte utile. " * 60},
            "links": {"internal": [{"href": "https://exemple.fr/rac", "text": " reste  à charge "}, {"href": "https://exemple.fr/rac", "text": "doublon"}, {"href": "javascript:x()", "text": "js"}, {"href": "/aide", "text": "Aide"}],
                      "external": [{"href": "https://autre.fr/", "text": "Autre"}]}}]})
    return httpx.Response(200, json={"success": True, "results": [{"url": url, "success": True, "status_code": 200, "html": "<html><body><main>page</main></body></html>",
        "markdown": {"raw_markdown": BRUT if "python" in url else "# Titre\n\nTexte de " + url, "fit_markdown": "Le 100 % Santé permet un . " + "Texte utile. " * 20},
        "metadata": {"title": "Titre de la page", "description": "Résumé"}}]})


class Service(unittest.TestCase):
    def client(self, searxng=resultats_searxng, crawl4ai=page_crawl4ai, jeton="jeton-test"):
        self.tc = TestClient(app)
        self.tc.__enter__()
        faux, self.appels = faux_moteurs(searxng, crawl4ai)
        app.state.searxng.client = faux
        app.state.searxng.url = "http://searxng:8080"
        app.state.crawl4ai.client = faux
        app.state.crawl4ai.url = "http://crawl4ai:11235"
        app.state.crawl4ai.jeton = jeton
        return self.tc

    def tearDown(self):
        tc, self.tc = getattr(self, "tc", None), None
        if tc is not None:
            tc.__exit__(None, None, None)

    def test_recherche_normalisee(self):
        r = self.client().post("/rechercher", json={"requete": "  remboursement   lunettes ", "limite": 3})
        self.assertEqual(r.status_code, 200, r.text)
        corps = r.json()
        self.assertEqual([x["url"] for x in corps["resultats"]], ["https://www.python.org/lunettes", "https://python.org/autre", "https://www.service-public.fr/lunettes"])
        self.assertEqual(corps["resultats"][0], {"position": 1, "titre": "Lunettes 100 % santé", "url": "https://www.python.org/lunettes",
                                                 "extrait": "Reste à charge zéro", "moteurs": ["bing", "qwant"]})
        self.assertEqual(corps["moteurs_muets"], ["startpage"])
        envoye = self.appels[-1].url
        self.assertEqual(envoye.params["q"], "remboursement lunettes")
        self.assertEqual(envoye.params["format"], "json")

    def test_refus_avant_tout_appel(self):
        tc = self.client()
        for requete, code in [("", "requete_vide"), ("x" * 501, "requete_trop_longue"), (["x"], "requete_vide"),
                              ("dossier 1 85 03 75 111 222 53", "donnees_personnelles"), ("jean.dupont@exemple.fr", "donnees_personnelles"),
                              ("rappeler 06 12 34 56 78", "donnees_personnelles"), ("FR76 3000 6000 0112 3456 7890 189", "donnees_personnelles")]:
            r = tc.post("/rechercher", json={"requete": requete})
            self.assertEqual(r.json()["erreur"]["code"], code, requete)
        self.assertEqual(tc.post("/rechercher", json={"requete": "x", "limite": 50}).json()["erreur"]["code"], "limite_invalide")
        self.assertEqual(tc.post("/rechercher", content=b"pas du json").json()["erreur"]["code"], "requete_invalide")
        self.assertEqual(self.appels, [], "un moteur a été appelé malgré le refus")

    def test_filtre_des_donnees_personnelles_en_option(self):
        tc = self.client()
        self.assertEqual(tc.post("/rechercher", json={"requete": "x", "filtre": "non"}).json()["erreur"]["code"], "filtre_invalide")
        self.assertEqual(tc.post("/rechercher", json={"requete": "écrire à jean.dupont@exemple.fr", "filtre": True}).json()["erreur"]["code"],
                         "donnees_personnelles")
        r = tc.post("/rechercher", json={"requete": "écrire à jean.dupont@exemple.fr", "filtre": False})
        self.assertEqual(r.status_code, 200, r.text)
        r = tc.post("/recherche-multi", json={"requete": "lunettes", "requetes": ["rappeler 06 12 34 56 78"], "filtre": False, "pages": 1})
        self.assertNotEqual(r.json().get("erreur", {}).get("code"), "donnees_personnelles")

    def test_pas_de_faux_positif(self):
        for texte in ["article L 315-2 du code de la sécurité sociale", "remboursement lunettes 100 % santé 2026",
                      "intelligence artificielle 2026", "SIRET 12345678901234", "tarif consultation 30 euros"]:
            self.assertEqual(garde.donnees_personnelles(texte), [], texte)

    def test_urls_refusees(self):
        tc = self.client()
        for url in ["file:///etc/passwd", "data:text/html,x", "http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/latest",
                    "http://55.144.209.121:10000/", "http://localhost:4000/", "http://nas.maison.lan/", "http://intranet",
                    "https://user:mdp@exemple.fr/", "https://exemple.fr:8443/", "http://2130706433/", "http://0x7f000001/",
                    "https://imprimante.local/", "javascript:alert(1)", "https://exemple.fr/\r\nX: y"]:
            r = tc.post("/lire", json={"url": url})
            self.assertIn(r.status_code, (400, 422), url)
            self.assertIn(r.json()["erreur"]["code"], ("url_refusee", "url_invalide"), url)
        self.assertEqual(self.appels, [], "Crawl4AI appelé pour une adresse refusée")

    def test_lecture(self):
        r = self.client().post("/lire", json={"url": "https://www.python.org/lunettes"})
        self.assertEqual(r.status_code, 200, r.text)
        lue = r.json()
        self.assertTrue(lue["succes"])
        self.assertEqual(lue["markdown"], BRUT)
        self.assertEqual(lue["titre"], "Titre de la page")
        self.assertRegex(lue["date_consultation"], r"^\d{4}-\d\d-\d\dT")
        crawls = [r for r in self.appels if r.url.path == "/crawl"]
        self.assertEqual(len(crawls), 3, "une lecture réseau et deux retraitements")
        self.assertEqual(json.loads(crawls[0].content)["urls"], ["https://www.python.org/lunettes"])
        self.assertTrue(all(json.loads(c.content)["urls"][0].startswith("raw:<html>") for c in crawls[1:]), "retraitement sans réseau")
        for envoye in crawls:
            self.assertEqual(envoye.headers["Authorization"], "Bearer jeton-test")
            demande = json.loads(envoye.content)
            self.assertNotIn("browser_config", demande)
            for interdit in ("js_code", "hooks", "proxy", "LLM", "deep_crawl"):
                self.assertNotIn(interdit, json.dumps(demande))
        self.assertNotIn("BM25ContentFilter", crawls[2].content.decode(), "BM25 sans recherche")
        # Versions : recommandée « sans liens », Pruning signalé (texte de lien perdu), liens dédoublonnés, http(s) seulement.
        self.assertEqual(list(lue["versions"]), ["sans_liens", "structure", "pruning", "brut"])
        self.assertEqual(lue["recommandee"], "sans_liens")
        self.assertNotIn("](", lue["versions"]["sans_liens"]["texte"])
        self.assertIn("[reste à charge](https://exemple.fr/rac)", lue["versions"]["structure"]["texte"])
        self.assertEqual(lue["versions"]["pruning"]["trous"], 1)
        self.assertIn("avertissement", lue["versions"]["pruning"])
        self.assertEqual(lue["versions"]["sans_liens"]["trous"], 0)
        self.assertGreater(lue["versions"]["sans_liens"]["reduction"], 0)
        self.assertEqual(lue["liens"], [{"texte": "reste à charge", "url": "https://exemple.fr/rac", "externe": False},
                                        {"texte": "Aide", "url": "https://www.python.org/aide", "externe": False},
                                        {"texte": "Autre", "url": "https://autre.fr/", "externe": True}])

    def test_lecture_avec_recherche_bm25(self):
        lue = self.client().post("/lire", json={"url": "https://www.python.org/lunettes", "requete": "  lunettes   100 % santé "}).json()
        crawl = json.loads([r for r in self.appels if r.url.path == "/crawl"][2].content)
        filtre = crawl["crawler_config"]["params"]["markdown_generator"]["params"]["content_filter"]
        self.assertEqual((filtre["type"], filtre["params"]["user_query"]), ("BM25ContentFilter", "lunettes 100 % santé"))
        self.assertEqual(list(lue["versions"]), ["sans_liens", "structure", "bm25", "pruning", "brut"])
        self.assertEqual(lue["versions"]["bm25"]["texte"], "Le 100 % Santé permet un reste à charge nul.")
        self.assertIn("avertissement", lue["versions"]["bm25"], "BM25 presque vide signalé")

    def test_retraitement_en_panne(self):
        def panne(r):
            if r.url.path == "/crawl" and json.loads(r.content)["urls"][0].startswith("raw:"):
                return httpx.Response(413, text='{"detail": "Request body too large"}')
            return page_crawl4ai(r)
        lue = self.client(crawl4ai=panne).post("/lire", json={"url": "https://www.python.org/lunettes"}).json()
        self.assertTrue(lue["succes"])
        self.assertEqual(list(lue["versions"]), ["pruning", "brut"])
        self.assertEqual(lue["recommandee"], "brut")
        self.assertIn("Versions nettoyées indisponibles", lue["nettoyage_erreur"])

    def test_lecture_bornee(self):
        long = lambda r: httpx.Response(200, json={"results": [{"success": True, "markdown": "a" * 300_000}]})
        lue = self.client(crawl4ai=long).post("/lire", json={"url": "https://exemple.fr/"}).json()
        self.assertEqual(len(lue["markdown"]), 200_000)
        self.assertTrue(lue["tronque"])

    def test_erreurs_crawl4ai(self):
        for reponse, statut, code in [(httpx.Response(400, text='{"detail":"URL blocked"}'), 422, "url_refusee"),
                                      (httpx.Response(401, text="no"), 502, "jeton_refuse"),
                                      (httpx.Response(504, text="timeout"), 504, "delai_depasse"),
                                      (httpx.Response(500, text="boom"), 502, "erreur_crawl4ai"),
                                      (httpx.Response(200, text="pas du json"), 502, "reponse_invalide")]:
            tc = self.client(crawl4ai=lambda r, x=reponse: x)
            r = tc.post("/lire", json={"url": "https://exemple.fr/"})
            self.assertEqual((r.status_code, r.json()["erreur"]["code"]), (statut, code))
            self.tearDown()

    def test_page_en_echec(self):
        echec = lambda r: httpx.Response(200, json={"results": [{"success": False, "error_message": "net::ERR_NAME_NOT_RESOLVED", "markdown": ""}]})
        lue = self.client(crawl4ai=echec).post("/lire", json={"url": "https://inexistant.exemple.fr/"}).json()
        self.assertFalse(lue["succes"])
        self.assertIn("ERR_NAME_NOT_RESOLVED", lue["erreur"])

    def test_recherche_complete(self):
        r = self.client().post("/recherche-complete", json={"requete": "lunettes"})
        self.assertEqual(r.status_code, 200, r.text)
        sources = r.json()["sources"]
        # 3 premiers sites lisibles, un par site, dans l'ordre : ameli.fr, service-public.fr, mutuelle (intranet écarté).
        self.assertEqual([s["url"] for s in sources], ["https://www.python.org/lunettes", "https://www.service-public.fr/lunettes", "https://mutuelle.exemple.fr/"])
        self.assertTrue(all(s["lecture"]["succes"] for s in sources))

    def test_recherche_complete_passe_les_pages_bloquees(self):
        def bloque(r):
            url = json.loads(r.content)["urls"][0] if r.url.path == "/crawl" else ""
            if "service-public" in url:
                return httpx.Response(200, json={"results": [{"success": False, "error_message": "Blocked by anti-bot protection", "markdown": ""}]})
            if "mutuelle" in url:
                return httpx.Response(200, json={"results": [{"success": True, "status_code": 503, "markdown": "Service indisponible"}]})
            return page_crawl4ai(r)
        sources = self.client(crawl4ai=bloque).post("/recherche-complete", json={"requete": "lunettes"}).json()["sources"]
        # ameli lue, service-public bloqué, mutuelle en 503, quatre.exemple.org lue : 4 essais, 2 lues, plus de candidat.
        self.assertEqual([(s["url"], s["lecture"]["succes"]) for s in sources], [("https://www.python.org/lunettes", True),
            ("https://www.service-public.fr/lunettes", False), ("https://mutuelle.exemple.fr/", False), ("https://quatre.exemple.org/", True)])
        self.assertIn("503", sources[2]["lecture"]["erreur"])

    def test_recherche_complete_crawl4ai_arrete(self):
        arrete = lambda r: (_ for _ in ()).throw(httpx.ConnectError("arrêté"))
        r = self.client(crawl4ai=arrete).post("/recherche-complete", json={"requete": "lunettes"})
        self.assertEqual(r.status_code, 200)
        sources = r.json()["sources"]
        self.assertEqual(len(sources), 2, "une seule vague de lectures quand Crawl4AI est arrêté")
        self.assertTrue(all(s["lecture"]["code"] == "crawl4ai_injoignable" for s in sources))

    def test_searxng_arrete_et_degrade(self):
        arrete = lambda r: (_ for _ in ()).throw(httpx.ConnectError("arrêté"))
        tc = self.client(searxng=arrete)
        r = tc.post("/rechercher", json={"requete": "lunettes"})
        self.assertEqual((r.status_code, r.json()["erreur"]["code"]), (503, "searxng_injoignable"))
        sante = tc.get("/sante").json()
        self.assertEqual(sante["searxng"]["etat"], "offline")
        self.assertEqual(sante["crawl4ai"]["etat"], "online")
        self.tearDown()
        muets = lambda r: httpx.Response(200, text="OK") if r.url.path == "/healthz" else httpx.Response(200, json={"results": [], "unresponsive_engines": [["bing", "CAPTCHA"]]})
        tc = self.client(searxng=muets)
        self.assertEqual(tc.post("/rechercher", json={"requete": "lunettes"}).json()["resultats"], [])
        self.assertEqual(tc.get("/sante").json()["searxng"]["etat"], "degraded")

    def test_conteneur_arrete_sans_reponse(self):
        muet = lambda r: (_ for _ in ()).throw(httpx.ConnectTimeout("pas de réponse"))
        tc = self.client(searxng=lambda r: httpx.Response(200, text="OK") if r.url.path == "/healthz" else muet(r), crawl4ai=muet)
        r = tc.post("/rechercher", json={"requete": "lunettes"})
        self.assertEqual((r.status_code, r.json()["erreur"]["code"]), (503, "searxng_injoignable"))
        self.assertEqual(tc.get("/sante").json()["searxng"]["etat"], "online", "un arrêt ne rend pas l'état dégradé")
        r = tc.post("/lire", json={"url": "https://exemple.fr/"})
        self.assertEqual((r.status_code, r.json()["erreur"]["code"]), (503, "crawl4ai_injoignable"))

    def test_sante_sans_jeton(self):
        self.assertEqual(self.client(jeton="").get("/sante").json()["crawl4ai"]["etat"], "degraded")


if __name__ == "__main__":
    unittest.main()
