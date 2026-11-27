"""Lecture simple (sans navigateur) et route /lire-page : faux sites et faux Crawl4AI (httpx.MockTransport), aucun réseau."""
import asyncio
import json
import unittest

import httpx
from fastapi.testclient import TestClient

import multi
import telechargement
from app import app

ARTICLE = "<html><head><title>Lunettes</title></head><body><main><h1>Lunettes</h1><p>" + "Le 100 % Santé rembourse les lunettes. " * 40 + "</p></main></body></html>"


def site(routes: dict):
    """Faux Internet (derrière le proxy de sortie) : adresse -> réponse."""
    demandes = []

    def repondre(r: httpx.Request) -> httpx.Response:
        demandes.append(r)
        reponse = routes.get(str(r.url))
        return reponse(r) if callable(reponse) else reponse if reponse is not None else httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(repondre)), demandes


def html(texte: str, statut: int = 200, genre: str = "text/html; charset=utf-8", **entetes) -> httpx.Response:
    return httpx.Response(statut, content=texte.encode(), headers={"content-type": genre, **entetes})


def telecharger(routes: dict, url: str):
    client, demandes = site(routes)
    return asyncio.run(telechargement.telecharger(client, url)), demandes


class Telechargement(unittest.TestCase):
    def test_page_html_et_redirections_controlees(self):
        (texte, finale), demandes = telecharger({
            "https://exemple.fr/a": httpx.Response(301, headers={"location": "/b"}),
            "https://exemple.fr/b": html(ARTICLE)}, "https://exemple.fr/a")
        self.assertEqual((finale, texte), ("https://exemple.fr/b", ARTICLE))
        self.assertEqual(demandes[0].headers["user-agent"], telechargement.AGENT, "robot qui se présente")
        with self.assertRaises(telechargement.Echec) as e:
            telecharger({"https://exemple.fr/a": httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})}, "https://exemple.fr/a")
        self.assertIn("redirection", e.exception.raison)
        with self.assertRaises(telechargement.Echec):
            telecharger({"https://exemple.fr/a": httpx.Response(302, headers={"location": "https://intranet.maison.internal/"})}, "https://exemple.fr/a")
        boucle = {"https://exemple.fr/a": httpx.Response(302, headers={"location": "https://exemple.fr/a"})}
        with self.assertRaises(telechargement.Echec) as e:
            telecharger(boucle, "https://exemple.fr/a")
        self.assertEqual(e.exception.raison, "trop de redirections")

    def test_refus_qui_menent_au_navigateur(self):
        for reponse, raison in [(html("Accès refusé", 403), "statut HTTP 403"),
                                (httpx.Response(200, content=b"%PDF-1.7", headers={"content-type": "application/zip"}), "pas une page HTML"),
                                (httpx.Response(200, content=b"<html>pas un PDF", headers={"content-type": "application/pdf"}), "PDF illisible"),
                                (html("x", **{"content-length": str(telechargement.OCTETS_MAX + 1)}), "page trop lourde")]:
            with self.assertRaises(telechargement.Echec) as e:
                telecharger({"https://exemple.fr/": reponse}, "https://exemple.fr/")
            self.assertEqual(e.exception.raison, raison)
        with mock_octets_max(1000), self.assertRaises(telechargement.Echec) as e:
            telecharger({"https://exemple.fr/": html("a" * 5000, genre="text/html")}, "https://exemple.fr/")
        self.assertEqual(e.exception.raison, "page trop lourde", "taille comptée pendant la réception, sans en-tête")

    def test_pdf_rendu_tel_quel(self):
        (contenu, finale), _ = telecharger({"https://exemple.fr/bareme.pdf": httpx.Response(200, content=b"%PDF-1.7 plafonds",
                                           headers={"content-type": "application/pdf"})}, "https://exemple.fr/bareme.pdf")
        self.assertIsInstance(contenu, telechargement.Pdf)
        self.assertEqual((bytes(contenu), finale), (b"%PDF-1.7 plafonds", "https://exemple.fr/bareme.pdf"))

    def test_jeu_de_caracteres(self):
        latin = '<html><head><meta charset="iso-8859-1"></head><body>Santé</body></html>'.encode("latin-1")
        (texte, _), _ = telecharger({"https://exemple.fr/": httpx.Response(200, content=latin, headers={"content-type": "text/html"})},
                                    "https://exemple.fr/")
        self.assertIn("Santé", texte)

    def test_besoin_du_navigateur(self):
        self.assertEqual(telechargement.besoin_navigateur("Chargement…"), "presque aucun texte sans JavaScript")
        self.assertIsNotNone(telechargement.besoin_navigateur("Just a moment... " + "x " * 600))
        self.assertIsNotNone(telechargement.besoin_navigateur("Veuillez activer JavaScript pour continuer. " + "x " * 600))
        self.assertIsNone(telechargement.besoin_navigateur("Un vrai article. " * 100))
        self.assertIsNone(telechargement.besoin_navigateur("Activez JavaScript pour les vidéos. " + "Un vrai article. " * 400),
                          "longue page : la mention ne compte pas")


class mock_octets_max:
    def __init__(self, valeur):
        self.valeur = valeur

    def __enter__(self):
        self.avant, telechargement.OCTETS_MAX = telechargement.OCTETS_MAX, self.valeur

    def __exit__(self, *_):
        telechargement.OCTETS_MAX = self.avant


TEXTE_ARTICLE = "# Lunettes\n\n" + "Le 100 % Santé rembourse les lunettes. " * 40


def crawl4ai_faux(appels: list, navigateur_texte: str = TEXTE_ARTICLE):
    """Faux Crawl4AI : « raw: » rend le texte du HTML reçu (titre compris) ; une adresse http(s) : lecture au navigateur."""
    def repondre(r: httpx.Request) -> httpx.Response:
        if r.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        demande = json.loads(r.content)
        url = demande["urls"][0]
        appels.append(url[:4] if url.startswith("raw:") else url)
        if url.startswith("raw:"):
            corps = url[4:]
            texte = TEXTE_ARTICLE if "100 % Santé" in corps else "Chargement…"
            return httpx.Response(200, json={"results": [{"success": True, "html": corps,
                                                          "markdown": {"raw_markdown": texte, "fit_markdown": ""},
                                                          "metadata": {"title": "Lunettes", "og:site_name": "Exemple"}}]})
        return httpx.Response(200, json={"results": [{"url": url, "success": True, "status_code": 200, "html": ARTICLE,
                                                      "markdown": {"raw_markdown": navigateur_texte}, "metadata": {"title": "Lue au navigateur"}}]})
    return repondre


class LectureSimple(unittest.TestCase):
    def client(self, routes: dict):
        self.tc = TestClient(app)
        self.tc.__enter__()
        self.addCleanup(self.tc.__exit__, None, None, None)
        self.crawls = []
        interne = httpx.AsyncClient(transport=httpx.MockTransport(crawl4ai_faux(self.crawls)))
        c4 = app.state.crawl4ai
        c4.client, c4.url, c4.jeton = interne, "http://crawl4ai:11235", "jeton-test"
        c4.sortie, self.demandes = site(routes)
        app.state.icones.client = None
        self.addCleanup(setattr, c4, "sortie", None)
        return self.tc

    def test_page_lue_sans_navigateur(self):
        lue = self.client({"https://exemple.fr/a": httpx.Response(301, headers={"location": "https://exemple.fr/b"}),
                           "https://exemple.fr/b": html(ARTICLE)}).post("/lire", json={"url": "https://exemple.fr/a"}).json()
        self.assertTrue(lue["succes"], lue)
        self.assertEqual((lue["lecture"], lue["url_finale"], lue["statut_http"], lue["titre"]), ("simple", "https://exemple.fr/b", 200, "Lunettes"))
        self.assertNotIn("repli_navigateur", lue)
        self.assertEqual(self.crawls, ["raw:"] * 3, "aucune ouverture au navigateur : lecture puis deux retraitements")
        self.assertIn("sans_liens", lue["versions"])

    def test_repli_sur_le_navigateur(self):
        for routes, raison in [({"https://exemple.fr/": html("Refusé", 403)}, "statut HTTP 403"),
                               ({"https://exemple.fr/": html("<html><body><div id=root></div></body></html>")}, "presque aucun texte sans JavaScript")]:
            lue = self.client(routes).post("/lire", json={"url": "https://exemple.fr/"}).json()
            self.assertTrue(lue["succes"], lue)
            self.assertEqual((lue["lecture"], lue["repli_navigateur"], lue["titre"]), ("navigateur", raison, "Lue au navigateur"))
            self.assertIn("https://exemple.fr/", self.crawls, "page ouverte au navigateur")

    def test_pdf_lu_par_doc_guard(self):
        pdf = httpx.Response(200, content=b"%PDF-1.7 ...", headers={"content-type": "application/pdf"})
        url = "https://www.exemple.gouv.fr/files/2026%20Plafonds_C2S.pdf"
        envoyes = []

        def doc_guard(r: httpx.Request) -> httpx.Response:
            if r.url.host == "doc-guard":
                envoyes.append((r.url.path, r.content))
                return httpx.Response(200, json={"kind": "pdf", "pages": [{"text": "Plafonds 2026\n1 personne 10 421 €"}, {"text": "Forfaits logement"}]})
            return crawl4ai_faux(self.crawls)(r)

        tc = self.client({url: pdf})
        c4 = app.state.crawl4ai
        c4.client, c4.doc_guard = httpx.AsyncClient(transport=httpx.MockTransport(doc_guard)), "http://doc-guard:8080"
        self.addCleanup(setattr, c4, "doc_guard", "")
        lue = tc.post("/lire", json={"url": url}).json()
        self.assertTrue(lue["succes"], lue)
        self.assertEqual((lue["lecture"], lue["titre"]), ("pdf", "2026 Plafonds C2S"))
        self.assertIn("10 421 €", lue["versions"]["sans_liens"]["texte"])
        self.assertEqual(envoyes, [("/analyse", b"%PDF-1.7 ...")])
        self.assertEqual(self.crawls, [], "ni navigateur ni Crawl4AI pour un PDF")
        # Sans doc-guard : le PDF n'est pas lu (le navigateur ne lit pas mieux un PDF).
        c4.doc_guard = ""
        self.assertFalse(tc.post("/lire", json={"url": url}).json().get("lecture") == "pdf")

    def test_sans_proxy_de_sortie_toujours_le_navigateur(self):
        tc = self.client({})
        app.state.crawl4ai.sortie = None
        lue = tc.post("/lire", json={"url": "https://exemple.fr/"}).json()
        self.assertEqual(lue["lecture"], "navigateur")
        self.assertNotIn("repli_navigateur", lue)
        self.assertEqual(self.demandes, [])

    def test_lire_page_entiere(self):
        r = self.client({"https://exemple.fr/": html(ARTICLE)}).post("/lire-page", json={"url": "https://exemple.fr/", "question": "lunettes"})
        page = r.json()
        self.assertEqual(r.status_code, 200, page)
        self.assertTrue(page["succes"])
        self.assertTrue(page["entier"])
        self.assertNotIn("extrait", page)
        self.assertIn("100 % Santé rembourse", page["texte"])
        self.assertEqual((page["titre"], page["site"], page["lecture"]), ("Lunettes", "Exemple", "simple"))
        self.assertGreater(page["jetons"], 0)

    def test_lire_page_refusee_ou_illisible(self):
        tc = self.client({})
        r = tc.post("/lire-page", json={"url": "http://localhost:8080/"})
        self.assertEqual((r.status_code, r.json()["erreur"]["code"]), (422, "url_refusee"))
        r = tc.post("/lire-page", json={"url": "https://exemple.fr/", "budget": 50})
        self.assertEqual(r.json()["erreur"]["code"], "budget_invalide")
        vide = lambda r: httpx.Response(200, json={"results": [{"success": False, "error_message": "net::ERR_NAME_NOT_RESOLVED", "markdown": ""}]})
        app.state.crawl4ai.client = httpx.AsyncClient(transport=httpx.MockTransport(vide))
        page = tc.post("/lire-page", json={"url": "https://inexistant.exemple.fr/"}).json()
        self.assertFalse(page["succes"])
        self.assertIn("ERR_NAME_NOT_RESOLVED", page["erreur"])


class ExtraitPage(unittest.TestCase):
    def test_page_longue(self):
        sections = [f"## Partie {i}\n\n" + ("Texte de remplissage sur un autre sujet. " * 60) for i in range(12)]
        sections[7] = "## Garantie\n\n" + "La garantie légale de conformité dure deux ans. " * 20
        texte = "\n\n".join(sections)
        avec = multi.extrait_page(texte, "https://exemple.fr/", "Titre", "durée de la garantie légale", 2000)
        self.assertFalse(avec["entier"])
        self.assertIn("garantie légale", avec["texte"])
        self.assertTrue(avec["texte"].startswith("## Partie 0"), "le début de la page est gardé")
        self.assertIn("proches de la question", avec["extrait"])
        self.assertLessEqual(avec["jetons"], 2000 + 20)
        self.assertEqual(avec["texte"].count("## Garantie"), 1, "titre de section pas doublé")
        sans = multi.extrait_page(texte, "https://exemple.fr/", "Titre", "", 1000)
        self.assertIn("début de la page", sans["extrait"])
        self.assertTrue(sans["texte"].startswith("## Partie 0"))
        court = multi.extrait_page("Court.", "https://exemple.fr/", "Titre", "", 1000)
        self.assertEqual((court["texte"], court["entier"]), ("Court.", True))


if __name__ == "__main__":
    unittest.main()
