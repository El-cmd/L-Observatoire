"""Qualité des passages : lignes parasites, vraies phrases, pages incomplètes, fautes, quasi-doublons, mode comparé."""
import unittest

import multi
import qualite

ARTICLE = " ".join(f"Le judoka Teddy Riner a annoncé lundi sa candidature à l'élection présidentielle, phrase {i} de l'article." for i in range(40))


class Nettoyage(unittest.TestCase):
    def test_lignes_parasites(self):
        texte = ("Voir plus - Afficher toutes les notifications\nFermer le menu\n* Facebook\n* Partager sur X (nouvelle fenêtre)\n"
                 "Ajoutez TF1info à vos sources\n# Teddy Riner candidat\nLe judoka a annoncé sa candidature à l'élection présidentielle lundi soir.\n"
                 "Les notifications de l'application ont été envoyées à des millions de Français pour annoncer la nouvelle du jour.")
        net, retirees = qualite.nettoyer(texte)
        self.assertEqual(retirees, 5)
        self.assertIn("# Teddy Riner candidat", net)
        self.assertIn("notifications de l'application", net, "ligne longue gardée même si elle contient un mot surveillé")

    def test_part_phrases(self):
        self.assertLess(qualite.part_phrases("Accueil\nPolitique\nSport\nJudo\nVoir tout\nNos offres"), qualite.PART_PHRASES_MIN)
        self.assertGreater(qualite.part_phrases(ARTICLE), 0.9)
        self.assertLess(qualite.part_phrases("Accessibilité Vidéo Podcasts Jeux Journal Exclusif Élections Présidentielle 2027 Offrir Suivre Le Parisien"), 0.1)


class Incompletes(unittest.TestCase):
    def test_marques(self):
        coupe = "Teddy Riner annonce sa candidature. " * 5 + "\nIl vous reste 78.45% de cet article à lire. La suite est réservée aux abonnés."
        self.assertIn("suite réservée aux abonnés", qualite.incomplete(coupe, coupe))
        bloque = "Just a moment...\nChecking if the site connection is secure"
        self.assertIn("blocage", qualite.incomplete(bloque, bloque))
        self.assertIn("trop court", qualite.incomplete("Accueil\nMenu", "Accueil\nMenu"))

    def test_page_libre_avec_mentions(self):
        page = ARTICLE + "\nArticle réservé à nos abonnés : à lire aussi\nL'accès refusé aux soins est un autre sujet."
        self.assertIsNone(qualite.incomplete(page, page), "marques ambiguës ignorées sur une page longue")


class Fautes(unittest.TestCase):
    def test_correction_par_vocabulaire(self):
        self.assertEqual(qualite.corrections(["teddy", "rinner", "president"], [ARTICLE, ARTICLE], multi.MOTS_VIDES), {"rinner": "riner"})

    def test_sans_correction_abusive(self):
        self.assertEqual(qualite.corrections(["riner", "dupont", "le"], [ARTICLE], multi.MOTS_VIDES), {}, "mot présent, mot inconnu sans voisin, mot vide")


def page(numero, url, texte, groupe="autre"):
    return {"numero": numero, "url": url, "titre": "T", "groupe": groupe, "texte": texte, "date_consultation": "2026-11-10T09:00:00+00:00"}


class Selection(unittest.TestCase):
    def test_teddy_rinner(self):
        lues = [page(1, "https://a.fr/", "# Candidature\n\n" + ARTICLE)]
        avant = multi.selectionner("teddy rinner president", lues, 8000, optimise=False)
        apres = multi.selectionner("teddy rinner president", [page(1, "https://a.fr/", "# Candidature\n\n" + ARTICLE)], 8000)
        self.assertEqual(apres["corrections"], [{"de": "rinner", "vers": "riner"}])
        self.assertEqual(avant["corrections"], [])
        self.assertGreater(max(c["couverture"] for c in apres["classement"]), max(c["couverture"] for c in avant["classement"]))

    def test_quasi_doublons_entre_sites(self):
        commun = "# Annonce\n\n" + ARTICLE
        lues = [page(1, "https://a.fr/", commun, "favorisee"), page(2, "https://b.fr/", commun.replace("phrase 3 ", "phrase trois ")),
                page(3, "https://a.fr/autre", commun)]
        r = multi.selectionner("teddy riner candidature", lues, 8000)
        gardes = [c for c in r["classement"] if c["statut"] == "garde"]
        self.assertTrue(gardes)
        self.assertTrue(all(c["numero"] == 1 and c["aussi_dans"] == [2] for c in gardes), [(c["numero"], c["aussi_dans"]) for c in gardes])
        self.assertTrue(all("même information aussi dans [2]" in c["raison"] for c in gardes))
        raisons = [c["raison"] for c in r["classement"] if c["statut"] == "ecarte"]
        self.assertTrue(any("citée en appui" in x for x in raisons))
        self.assertTrue(any("même site" in x for x in raisons))
        texte = r["contexte"]["texte"]
        self.assertIn("(même information aussi dans [2])", texte)
        self.assertIn("[2] T — https://b.fr/", texte, "source d'appui listée")
        self.assertNotIn("[3] T", texte)
        self.assertLessEqual(r["contexte"]["jetons"], 8000)

    def test_passage_pauvre_penalise(self):
        menu = "# Rubriques\n\n" + "\n".join(f"Teddy Riner rubrique {i}" for i in range(30))
        r = multi.selectionner("teddy riner", [page(1, "https://a.fr/", "# Article\n\n" + ARTICLE + "\n\n" + menu)], 8000)
        pauvres = [c for c in r["classement"] if c["penalite"] < 1]
        self.assertTrue(pauvres)
        self.assertTrue(all("peu de vraies phrases" in c["raison"] or c["statut"] == "ecarte" for c in pauvres))

    def test_mode_sans_optimisation_inchange(self):
        texte = "Fermer le menu\nAfficher toutes les notifications\n# A\n\n" + ARTICLE
        r = multi.selectionner("teddy riner", [page(1, "https://a.fr/", texte)], 8000, optimise=False)
        self.assertFalse(r["optimisations"])
        self.assertIn("Fermer le menu", r["contexte"]["texte"])
        self.assertTrue(all(c["penalite"] == 1.0 for c in r["classement"]))


if __name__ == "__main__":
    unittest.main()
