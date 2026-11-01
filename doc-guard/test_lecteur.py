"""Checks of the reading rules: python -m unittest test_lecteur (in the doc-guard image)."""
import unittest

import lecteur


class Rules(unittest.TestCase):
    def test_pages_read_on_their_image(self):
        good = 'Le dossier a été traité par le service, la référence est indiquée ci-dessous.'
        self.assertIsNone(lecteur.image_reason(good, False))
        self.assertEqual(lecteur.image_reason('3', False), 'sans texte')
        self.assertEqual(lecteur.image_reason(good, True), 'texte invisible de scanner')
        self.assertEqual(lecteur.image_reason(good.encode().decode('latin-1'), False), 'texte illisible')
        self.assertEqual(lecteur.image_reason('(cid:12)(cid:15)(cid:3) ' * 5 + good, False), 'texte illisible')

    def test_columns_become_segments(self):
        words = [(10, 10, 40, 20, 'Mois'), (100, 10, 160, 20, 'Recettes'), (165, 10, 175, 20, '(€)'), (10, 30, 50, 40, 'Janvier')]
        self.assertEqual(lecteur.segment(words), [[10, 10, 'Mois'], [100, 10, 'Recettes (€)'], [10, 30, 'Janvier']])

    def test_word_output_is_retouched(self):
        self.assertEqual(lecteur.retouch('|  |  |\n| --- | --- |\n| Mois | Total |\n| Mars | 3 |'), '| Mois | Total |\n| --- | --- |\n| Mars | 3 |')
        self.assertEqual(lecteur.retouch('Voir ![Logo de la caisse](data:image/png;base64,AAAA) et ![](x.png)'), 'Voir [image : Logo de la caisse] et [image]')

    def test_formats(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.txt') as file:
            file.write(b'def f():\n    return "```"\n'); file.flush()
            self.assertEqual(lecteur.kind(file.name, '.py'), 'text')
            self.assertEqual(lecteur.analyse_text(file.name, '.py')['markdown'], '````python\ndef f():\n    return "```"\n````')
            for extension, message in (('.xlsx', 'Excel'), ('.odt', '.docx'), ('.exe', 'Format non pris en charge')):
                with self.assertRaises(lecteur.Refused) as refused:
                    lecteur.kind(file.name, extension)
                self.assertIn(message, str(refused.exception))


if __name__ == '__main__':
    unittest.main()
