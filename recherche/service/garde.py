"""Garde-fous appliqués avant toute sortie vers Internet : requêtes sans donnée personnelle, adresses publiques seulement.

Ce contrôle applicatif est la première barrière. Les vraies barrières réseau sont ailleurs : Crawl4AI résout et épingle
chaque adresse, et le proxy « sortie » refuse toute destination interne. Le filtre de données personnelles des requêtes
est une option (`filtre`, activé par défaut) : c'est un garde-fou contre un copier-coller, pas une obligation.
"""
import ipaddress
import re
from urllib.parse import urlsplit

REQUETE_MAX = 500
URL_MAX = 2048

# Domaines internes : jamais lus, quel que soit ce que donne le DNS.
SUFFIXES_INTERNES = (".local", ".internal", ".lan", ".localhost", ".home.arpa", ".arpa")
NOMS_INTERNES = {"localhost", "metadata", "metadata.google.internal"}

_NIR = re.compile(r"(?<![\dA-Za-z])([1-478])\s?(\d{2})\s?(0[1-9]|1[0-2]|[2-9]\d)\s?(\d{2}|2[AB])\s?(\d{3})\s?(\d{3})(?:\s?[|/]?\s?(\d{2}))?(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_TELEPHONE = re.compile(r"(?<!\d)(?:\+33\s?|0033\s?|0)[1-9](?:[\s.-]?\d{2}){4}(?!\d)")
_IBAN = re.compile(r"\bFR\d{2}(?:\s?[A-Z0-9]{4}){5}\s?[A-Z0-9]{3}\b", re.IGNORECASE)


class Refus(Exception):
    """Demande refusée avant tout appel : le message est montré tel quel."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def donnees_personnelles(texte: str) -> list[str]:
    """Catégories de données personnelles repérées dans une requête (vide : rien repéré)."""
    trouve = []
    if _NIR.search(texte):
        trouve.append("numéro de sécurité sociale")
    if _EMAIL.search(texte):
        trouve.append("adresse e-mail")
    if _TELEPHONE.search(texte):
        trouve.append("numéro de téléphone")
    if _IBAN.search(texte):
        trouve.append("IBAN")
    return trouve


def requete(texte: object, filtre: bool = True) -> str:
    if not isinstance(texte, str) or not texte.strip():
        raise Refus("requete_vide", "Saisissez une recherche.")
    texte = " ".join(texte.split())
    if len(texte) > REQUETE_MAX:
        raise Refus("requete_trop_longue", f"Recherche trop longue : {REQUETE_MAX} caractères au plus.")
    trouve = donnees_personnelles(texte) if filtre else []
    if trouve:
        raise Refus("donnees_personnelles", "Recherche refusée : elle semble contenir " + " et ".join(trouve)
                    + ". Retirez-la : la recherche part vers des moteurs extérieurs.")
    return texte


def url_publique(url: object) -> str:
    """URL http(s) d'un site public, sans identifiants, port standard, nom de domaine (pas d'adresse IP)."""
    if not isinstance(url, str) or not url.strip():
        raise Refus("url_vide", "Adresse de page manquante.")
    url = url.strip()
    if len(url) > URL_MAX or any(c in url for c in "\r\n\t "):
        raise Refus("url_invalide", "Adresse de page invalide.")
    try:
        parties = urlsplit(url)
        port = parties.port
    except ValueError:
        raise Refus("url_invalide", "Adresse de page invalide.")
    if parties.scheme not in ("http", "https"):
        raise Refus("url_refusee", "Seules les adresses http et https sont lues.")
    if parties.username or parties.password or "@" in parties.netloc:
        raise Refus("url_refusee", "Adresse refusée : identifiants dans l'adresse.")
    if port not in (None, 80, 443):
        raise Refus("url_refusee", "Adresse refusée : seuls les ports 80 et 443 sont permis.")
    hote = (parties.hostname or "").rstrip(".").lower()
    if not hote:
        raise Refus("url_invalide", "Adresse de page invalide.")
    try:
        ipaddress.ip_address(hote)
        raise Refus("url_refusee", "Adresse refusée : une adresse IP ne peut pas être lue, seulement un nom de site.")
    except ValueError:
        pass
    if hote in NOMS_INTERNES or hote.endswith(SUFFIXES_INTERNES) or "." not in hote or re.fullmatch(r"[\d.]+|0x[\da-f.x]+", hote):
        raise Refus("url_refusee", "Adresse refusée : site interne ou adresse locale.")
    return url
