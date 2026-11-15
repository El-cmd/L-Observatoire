"""Icônes des sites : conversion en PNG 32 × 32, refus de ce qui n'est pas une petite image, cache par domaine."""
import asyncio
import base64
import io
import unittest

import httpx
from PIL import Image

import icones


def image(format_, taille=(48, 48), **options) -> bytes:
    sortie = io.BytesIO()
    Image.new('RGBA', taille, (200, 30, 30, 255)).save(sortie, format=format_, **options)
    return sortie.getvalue()


def taille_png(adresse: str) -> tuple[int, int]:
    with Image.open(io.BytesIO(base64.b64decode(adresse.split(',', 1)[1]))) as png:
        return png.format, png.size


class Conversion(unittest.TestCase):
    def test_png_et_ico_redessines_en_32(self):
        self.assertEqual(taille_png(icones.en_png(image('PNG'))), ('PNG', (32, 32)))
        ico = icones.en_png(image('ICO', (64, 64), sizes=[(16, 16), (32, 32), (64, 64)]))
        self.assertEqual(taille_png(ico), ('PNG', (32, 32)))
        self.assertLess(len(ico), 4000)

    def test_refus(self):
        self.assertIsNone(icones.en_png(b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'))
        self.assertIsNone(icones.en_png(b'pas une image'))
        self.assertIsNone(icones.en_png(b''))
        self.assertIsNone(icones.en_png(b'\x89PNG' + b'0' * icones.OCTETS_MAX))
        self.assertIsNone(icones.en_png(image('PNG', (1000, 1000))), 'trop de pixels')

    def test_domaines(self):
        self.assertEqual(icones.domaine('https://www.France24.com/fr/x'), 'france24.com')
        self.assertEqual(icones.domaine('https://fr.wikipedia.org/wiki/Gaza'), 'fr.wikipedia.org')
        self.assertIsNone(icones.domaine('http://127.0.0.1/x'))
        self.assertIsNone(icones.domaine('http://[::1]/x'))
        self.assertIsNone(icones.domaine('pas une adresse'))


class Cache(unittest.TestCase):
    def test_une_demande_par_domaine_puis_cache(self):
        demandes = []

        def repondre(request):
            demandes.append(str(request.url))
            if 'inconnu' in str(request.url):
                return httpx.Response(404)
            return httpx.Response(200, content=image('ICO', (32, 32)))

        async def tout():
            async with httpx.AsyncClient(transport=httpx.MockTransport(repondre)) as client:
                registre = icones.Icones(client)
                a, b = await asyncio.gather(registre.pour('https://www.python.org/a'), registre.pour('https://python.org/b'))
                c = await registre.pour('https://python.org/c')
                absente = await registre.pour('https://site-inconnu.fr/')
                sans = await icones.Icones(None).pour('https://python.org/')
            return a, b, c, absente, sans
        a, b, c, absente, sans = asyncio.run(tout())
        self.assertTrue(a.startswith('data:image/png;base64,'))
        self.assertEqual(a, b); self.assertEqual(a, c)
        self.assertEqual(demandes, ['https://icons.duckduckgo.com/ip3/python.org.ico', 'https://icons.duckduckgo.com/ip3/site-inconnu.fr.ico'])
        self.assertIsNone(absente)
        self.assertIsNone(sans, 'sans proxy de sortie : pas d’icône')


if __name__ == '__main__':
    unittest.main()
