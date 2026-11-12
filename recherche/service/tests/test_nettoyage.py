"""Module nettoyage : statistiques, trous, liens, repli sur le brut."""
import unittest

import nettoyage


class Nettoyage(unittest.TestCase):
    def test_trous(self):
        self.assertEqual(nettoyage.trous("« Ameli » redirige ici. Ne pas confondre avec . Pour plus, voir . L’ est le modèle du ."), 3)
        self.assertEqual(nettoyage.trous("Ne pas confondre avec AMELY. Voir l'assurance maladie. Le 100 % Santé."), 0)

    def test_statistiques(self):
        brut = "a" * 1000
        r = nettoyage.assembler(brut, "b" * 300, "c" * 600, "d" * 400, None, 200_000)
        v = r["versions"]
        self.assertEqual(list(v), ["sans_liens", "structure", "pruning", "brut"])
        self.assertEqual((v["sans_liens"]["caracteres"], v["sans_liens"]["jetons_estimes"], v["sans_liens"]["reduction"]), (400, 100, 60.0))
        self.assertEqual(v["brut"]["reduction"], 0.0)
        self.assertEqual(v["sans_liens"]["libelle"], "Nettoyé, sans liens")
        self.assertEqual(r["recommandee"], "brut", "400 caractères : sous le minimum de 500")
        self.assertIsNotNone(r["repli"])

    def test_recommandee_et_repli(self):
        brut = "mot " * 1000
        self.assertEqual(nettoyage.assembler(brut, "", "x " * 500, "y " * 500, None, 200_000)["recommandee"], "sans_liens")
        r = nettoyage.assembler(brut, "", "x " * 500, "y " * 300, None, 200_000)   # 600 caractères mais moins de 20 % du brut
        self.assertEqual((r["recommandee"], bool(r["repli"])), ("brut", True))
        self.assertEqual(nettoyage.assembler(brut, "", None, None, None, 200_000)["recommandee"], "brut")

    def test_troncature(self):
        v = nettoyage.assembler("a" * 50, "", "a" * 50, "a" * 50, None, 10)["versions"]["sans_liens"]
        self.assertEqual((len(v["texte"]), v["caracteres"], v["tronque"]), (10, 50, True))

    def test_avertissements(self):
        v = nettoyage.assembler("texte " * 200, "Ne pas confondre avec . Voir .", "texte " * 200, "texte " * 200, "", 200_000)["versions"]
        self.assertIn("2 lien(s)", v["pruning"]["avertissement"])
        self.assertIn("BM25 n'a presque rien gardé", v["bm25"]["avertissement"])
        self.assertNotIn("avertissement", v["sans_liens"])

    def test_brut_sans_reduction(self):
        self.assertEqual(nettoyage.assembler("  texte  \n", "", None, None, None, 100)["versions"]["brut"]["reduction"], 0.0)

    def test_liens_relatifs(self):
        r = {"links": {"internal": [{"href": "/author/Einstein", "text": "Einstein"}, {"href": "#haut", "text": "Haut"}, {"href": "mailto:a@b.fr", "text": "m"}]}}
        self.assertEqual(nettoyage.liens(r, "https://quotes.toscrape.com/js/"), [{"texte": "Einstein", "url": "https://quotes.toscrape.com/author/Einstein", "externe": False}])

    def test_configurations_fixes(self):
        self.assertIn("[class*=orejime]", nettoyage.BANDEAUX)
        self.assertNotIn("content_filter", nettoyage.configuration_sans_liens("")["markdown_generator"]["params"])
        self.assertEqual(nettoyage.configuration_sans_liens("lunettes")["markdown_generator"]["params"]["content_filter"]["params"]["user_query"], "lunettes")


class LiensAbsolus(unittest.TestCase):
    def test_liens_relatifs_rendus_absolus(self):
        html = ('<a href="/wiki/Pulp_Fiction">P</a> <a href=\'#ref-1\'>1</a> <a href=autre.html>a</a> '
                '<img src="//upload.wikimedia.org/x.png" srcset="/x2.png 2x, /x3.png 3x"> <a href="https://imdb.com/t">i</a> '
                '<a HREF="mailto:a@b.fr">m</a>')
        self.assertEqual(nettoyage.liens_absolus(html, "https://fr.wikipedia.org/wiki/Quentin_Tarantino"),
                         '<a href="https://fr.wikipedia.org/wiki/Pulp_Fiction">P</a> '
                         '<a href=\'https://fr.wikipedia.org/wiki/Quentin_Tarantino#ref-1\'>1</a> '
                         '<a href="https://fr.wikipedia.org/wiki/autre.html">a</a> <img src="https://upload.wikimedia.org/x.png"> '
                         '<a href="https://imdb.com/t">i</a> <a HREF="mailto:a@b.fr">m</a>')


class AppelsDeNote(unittest.TestCase):
    def test_appels_retires_code_garde(self):
        texte = ("Jump to content\nFrom Wikipedia, the free encyclopedia\nshowFilmography\n"
                 "Reservoir Dogs (1992).[12] Film : 16 (10 feature,[a] 6 short). Un fait[réf. nécessaire] et[note 3] fin.[citation needed]\n"
                 "| Pulp Fiction[3] | 1994 |\nVoir [1] et la liste [a].\n```python\nx = tableau[0]  # [12]\n```\net `a[2]` reste.")
        self.assertEqual(nettoyage.sans_appels_de_note(texte),
                         "\n\n\nReservoir Dogs (1992). Film : 16 (10 feature, 6 short). Un fait et fin.\n"
                         "| Pulp Fiction | 1994 |\nVoir [1] et la liste [a].\n```python\nx = tableau[0]  # [12]\n```\net `a[2]` reste.")


if __name__ == "__main__":
    unittest.main()
