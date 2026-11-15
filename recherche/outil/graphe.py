"""Recherche web du labo, en deux modes, pilotés par Qwen (repris du graphe de CeliA, réglages personnels).

Mode « web » : une recherche, puis une réponse citée (2 appels à Qwen). Si aucun passage utile n'est trouvé, les pages
suivantes des mêmes résultats sont lues (pages déjà lues exclues), une fois, sans appel de plus à Qwen :

    START → planifier → recherche_simple (×2 au plus) → rediger_passages → END

Mode « approfondie » : le graphe agentique, avec lecteurs parallèles et nouvelles recherches au besoin :

    START → planifier → rechercher ─(un Send par lot)→ lecteur ×n → fusionner → decider ─→ verifier ─→ rechercher …
                            │                                                    │            │
                            └──────────── (limite, aucun passage) ───────────────┴─→ rediger ←┘ → END

- planifier : Qwen propose 1 à 3 requêtes courtes (en anglais pour un sujet technique).
- rechercher : /recherche-multi du service (SearXNG, Crawl4AI, nettoyage, BM25), pages déjà lues exclues ; numéros de
  source globaux, passages S<source>.<position> découpés en lots de LOT_JETONS.
- lecteur : un appel indépendant à Qwen par lot (en parallèle, Send de LangGraph) ; il ne voit que son lot.
- fusionner : mémoire de travail (faits et références, contradictions, manques) ; un fait sans référence du lot est
  rejeté ; les passages complets quittent alors l'état du graphe.
- decider / verifier : limites, puis Qwen décide de répondre ou de chercher encore (nouvelles requêtes).
- rediger : réponse à partir des faits seuls ; toute citation vers une source sans fait est remplacée.

Mode « tres_approfondie » (idées d'open_deep_research : cahier de recherche, un chercheur par sous-question,
superviseur, notes compressées, rapport écrit par sections) :

    START → ecrire_cahier ─(un Send par sous-question)→ chercheur ×n → consolider → superviser ─→ chercheur … (relances)
                                                                                       └─→ conclure
    conclure ─(un Send par sous-question)→ compresseur ×n → ranger_notes ─(Send)→ redacteur_section ×n → synthetiser → END

- ecrire_cahier : objectif, 1 à 4 sous-questions (chacune avec ses requêtes) et critères d'une réponse complète.
- chercheur : pour une sous-question, une recherche (5 pages) puis ses lecteurs en parallèle (2 lots au plus) ; faits
  avec références vérifiées, rangés sous la sous-question. Numéros de source communs à tous les chercheurs.
- superviser : couverture de chaque sous-question (couverte, partielle, absente) ; répondre, ou relancer seulement les
  sous-questions qui manquent, avec de nouvelles requêtes (3 tours au plus).
- compresseur : les faits d'une sous-question deviennent au plus 10 notes (doublons fusionnés, contradictions
  explicites), qui ne peuvent citer que les sources de ces faits.
- redacteur_section : une section par sous-question, en parallèle, à partir de ses notes (titres des autres sections
  connus, pour ne pas les répéter).
- synthetiser : la synthèse, écrite en dernier à partir des sections, placée en tête ; elle seule est envoyée mot à mot.

Mode « auto » : Qwen choisit d'abord (aiguiller) entre « direct » (réponse sans recherche, graphe d'un seul nœud),
« web », « approfondie » et « tres_approfondie ». Avec « clarifier », l'aiguillage, la planification ou le cahier peuvent
demander une précision au lieu de chercher : la recherche s'arrête (événement « clarification »), et la page la relance
avec la précision ajoutée à la question.

Les étapes intermédiaires sont du JSON contraint par un schéma (décodage guidé de vLLM) ; la réponse finale est du
Markdown libre, envoyé mot à mot au fil de l'écriture (événements « texte »). Les consignes système sont dans
consignes/prompts.toml, relu à chaque recherche, avec la date du jour. Les pages sont des données non fiables :
délimitées, délimiteurs neutralisés, consignes ignorées. Rien n'est conservé (pas de checkpointer).
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tomllib
from typing import Annotated, Any, Callable, TypedDict
from zoneinfo import ZoneInfo

import httpx
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send

ITERATIONS_MAX = 2
PAGES_PAR_ITERATION = 5
LOT_JETONS = 2500
LOTS_PAR_ITERATION = 3
APPELS_MAX = 12
DUREE_MAX = 240
JETONS_MAX = 150_000
FAITS_MAX = 40
REQUETE_MAX = 150
QUESTION_MAX = 1000
BUDGET_WEB = 8000                     # mode web : jetons de passages envoyés à Qwen pour la réponse
REFLEXION_SUPPLEMENT = 4000           # jetons de sortie en plus quand la réflexion est activée
PARALLELE = 3                         # appels à Qwen en même temps pour une recherche
# Mode très approfondi
SOUS_QUESTIONS_MAX = 4
TOURS_MAX = 3                         # tour 1 : toutes les sous-questions ; tours 2 et 3 : relances du superviseur
LOTS_PAR_CHERCHEUR = 2
FAITS_PAR_SOUS_QUESTION = 30          # condensés ensuite en NOTES_MAX notes par la compression
RECHERCHES_PARALLELES = 2             # /recherche-multi en même temps (le service lit 2 pages à la fois en tout)
EXCLURE_MAX = 50                      # limite du service
NOTES_MAX = 10                        # notes par sous-question après compression
SECTION_JETONS = 3000
SYNTHESE_JETONS = 1500
MODES_AUTO = ('direct', 'web', 'approfondie', 'tres_approfondie')
AUCUNE_INFO = 'Aucune information fiable n’a été trouvée pour répondre à cette question dans les pages consultées.'
APPEL_DELAI = 150
RECHERCHE_DELAI = 150                 # /recherche-multi : 5 pages lues par Crawl4AI

CONSIGNES = Path(os.environ.get('CONSIGNES', Path(__file__).parent / 'consignes' / 'prompts.toml'))
CONSIGNES_UTILES = ('aiguillage', 'clarification', 'direct', 'plan', 'plan_filtre', 'lecture', 'verification', 'redaction',
                    'redaction_web', 'cahier', 'superviseur', 'compression', 'section', 'synthese', 'eval_generation',
                    'eval_qualite', 'eval_citations')
BLOCS = ('date', 'donnees', 'citer', 'rediger')   # dans cet ordre : un bloc peut utiliser ceux qui le précèdent
JOURS = ('lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche')
MOIS = ('janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre')


class AgentErreur(Exception):
    """Arrêt de la recherche, message montré tel quel."""


# --- Contexte et état --------------------------------------------------------------------------------------------

@dataclass
class Compteurs:
    """Appels, jetons et durée par étape : partagés par les lecteurs parallèles (une seule boucle asyncio)."""
    debut: float
    appels: int = 0
    jetons: dict = field(default_factory=dict)

    def total(self) -> int:
        return sum(j['entree'] + j['sortie'] for j in self.jetons.values())


@dataclass(frozen=True)
class Limites:
    """Limites globales d'une recherche (selon le mode)."""
    appels: int = APPELS_MAX
    duree: int = DUREE_MAX
    jetons: int = JETONS_MAX


# Très approfondie : 1 cahier + 3 tours (2 lecteurs par chercheur, 1 supervision) + compression, sections et synthèse.
LIMITES = {'direct': Limites(appels=3), 'web': Limites(), 'approfondie': Limites(),
           'tres_approfondie': Limites(appels=34, duree=600, jetons=400_000)}


@dataclass
class RechercheContext:
    """Propre à une recherche, hors de l'état du graphe."""
    qwen_url: str
    qwen_cle: str
    modele: str
    http: httpx.AsyncClient            # vers Qwen
    web: httpx.AsyncClient             # vers le service de recherche
    reflexion: bool
    filtre: bool                       # refus des données personnelles dans les requêtes
    compteurs: Compteurs
    places: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(PARALLELE))
    consignes: dict = field(default_factory=dict)   # rempli par executer (charger_consignes)
    limites: Limites = field(default_factory=Limites)
    # Mode très approfondi : pages lues par tous les chercheurs (url -> source), pour des numéros communs. Rempli sans
    # attente entre lecture et écriture : sûr avec les chercheurs parallèles (une seule boucle asyncio).
    sources_lues: dict = field(default_factory=dict)
    recherches: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(RECHERCHES_PARALLELES))
    clarifier: bool = False            # Qwen peut demander une précision avant de chercher
    passages: dict = field(default_factory=dict)   # identifiant S<n>.<p> -> texte : passages lus (pour l'évaluation)


def cumule(avant: list, ajout: list | None) -> list:
    """Lectures des lecteurs parallèles mises bout à bout ; None vide la liste (après fusion)."""
    return [] if ajout is None else avant + ajout


class Etat(TypedDict, total=False):
    question: str
    a_faire: list[str]                 # requêtes de la prochaine recherche
    iteration: int
    requetes: list[str]                # requêtes déjà faites
    sources: dict                      # url -> {numero, url, titre, iteration}
    urls: list[str]                    # pages essayées (exclues des recherches suivantes)
    faits: list[dict]
    contradictions: list[dict]
    manques: list[str]
    corrections: list[dict]
    pages_partielles: list[dict]
    lots: list[list[dict]]             # passages complets : de la recherche à la fusion seulement
    lectures: Annotated[list[dict], cumule]
    nouveaux: int
    arret: str
    contexte: str                      # mode web : contexte cité rendu par le service
    citables: list[int]                # mode web : sources présentes dans le contexte
    redaction: dict
    # Mode très approfondi
    cahier: dict                       # objectif, criteres
    par_sq: dict                       # id (Q1…) -> {id, question, requetes, faits, manques, contradictions}
    resultats: Annotated[list[dict], cumule]   # rendus des chercheurs parallèles, jusqu'à la consolidation
    a_relancer: list[dict]             # [{id, requetes}] : chercheurs du prochain tour
    tour: int
    lots_par_chercheur: int
    couverture: list[dict]             # dernier avis du superviseur
    notes: Annotated[list[dict], cumule]       # rendus des compresseurs parallèles
    notes_par_sq: dict                 # id -> {notes, contradictions, sans_reponse}
    sections: Annotated[list[dict], cumule]    # sections du rapport, écrites en parallèle
    clarification: str                 # précision demandée par Qwen avant de chercher (la recherche s'arrête)


# --- Outils ------------------------------------------------------------------------------------------------------

def sur(texte: str) -> str:
    """Délimiteurs neutralisés dans un texte venu d'Internet (une page ne peut pas fermer un passage)."""
    return texte.replace('<<<PASSAGE', '« passage »').replace('FIN>>>', '« fin »')


def cle(texte: str) -> str:
    return re.sub(r'\W+', ' ', texte.strip().lower())


def jour_en_clair(moment: datetime) -> str:
    """« jeudi 12 novembre 2026 », « 1er novembre 2026 »."""
    return f'{JOURS[moment.weekday()]} {"1er" if moment.day == 1 else moment.day} {MOIS[moment.month - 1]} {moment.year}'


def charger_consignes(chemin: Path = CONSIGNES, maintenant: datetime | None = None) -> dict[str, str]:
    """Consignes système de consignes/prompts.toml, repères remplacés ({date}, {donnees}, {citer}, {rediger}, {jour}).
    Relu à chaque recherche : une modification s'applique à la suivante, sans redémarrer."""
    try:
        brut = tomllib.loads(chemin.read_text(encoding='utf-8'))
    except OSError:
        raise AgentErreur(f'Fichier des consignes introuvable : {chemin}.') from None
    except tomllib.TOMLDecodeError as e:
        raise AgentErreur(f'Fichier des consignes invalide ({chemin.name}) : {e}.') from None
    manquantes = [k for k in CONSIGNES_UTILES + BLOCS if not isinstance(brut.get(k), str) or not brut[k].strip()]
    if manquantes:
        raise AgentErreur(f'Consigne(s) manquante(s) dans {chemin.name} : {", ".join(manquantes)}.')
    jour = jour_en_clair(maintenant or datetime.now(ZoneInfo('Europe/Paris')))
    blocs: dict[str, str] = {}
    for k in BLOCS:
        texte = brut[k].strip().replace('{jour}', jour)
        for nom, bloc in blocs.items():
            texte = texte.replace('{' + nom + '}', bloc)
        blocs[k] = texte
    consignes = {}
    for k in CONSIGNES_UTILES:
        texte = brut[k].strip()
        for nom, bloc in blocs.items():
            texte = texte.replace('{' + nom + '}', bloc)
        if inconnus := re.findall(r'\{[a-z_]+\}', texte):
            raise AgentErreur(f'Repère inconnu dans la consigne « {k} » ({chemin.name}) : {", ".join(dict.fromkeys(inconnus))}.')
        consignes[k] = texte
    return consignes


def requetes_valides(requetes: Any) -> list[str]:
    """Requêtes courtes, sans doublon, 3 au plus."""
    sortie: list[str] = []
    for q in requetes if isinstance(requetes, list) else []:
        q = re.sub(r'\s+', ' ', str(q)).strip()
        if q and len(q) <= REQUETE_MAX and q.lower() not in (s.lower() for s in sortie):
            sortie.append(q)
    return sortie[:3]


def limite_atteinte(ctx: RechercheContext, reserve: int, marge: int = 40) -> str | None:
    """Raison d'arrêter si une limite globale est atteinte, en gardant « reserve » appels (et « marge » secondes) pour
    finir."""
    c, lim = ctx.compteurs, ctx.limites
    if c.appels + reserve >= lim.appels:
        return f'nombre maximal d’appels à Qwen atteint ({lim.appels})'
    if asyncio.get_running_loop().time() - c.debut > lim.duree - (marge if reserve else 0):
        return f'durée maximale atteinte ({lim.duree} s)'
    if c.total() >= lim.jetons - (15_000 if reserve else 0):
        return f'budget global de jetons épuisé ({lim.jetons})'
    return None


async def _en_flux(ctx: RechercheContext, body: dict, timeout: float, ecrire: Callable[[dict], Any]) -> tuple[int, dict, dict]:
    """Appel en flux (SSE) : chaque morceau de texte part aussitôt dans un événement « texte » ; un événement
    « reflexion » signale que Qwen réfléchit avant d'écrire. Rend (statut, message reconstitué, usage)."""
    body = {**body, 'stream': True, 'stream_options': {'include_usage': True}}
    texte, reflexion, fin, usage, signale = [], [], None, {}, False
    async with ctx.http.stream('POST', ctx.qwen_url + '/chat/completions', json=body,
                               headers={'Authorization': 'Bearer ' + ctx.qwen_cle}, timeout=timeout) as r:
        if r.status_code != 200:
            await r.aread()
            return r.status_code, {}, {}
        async for ligne in r.aiter_lines():
            if not ligne.startswith('data:'):
                continue
            donnee = ligne[5:].strip()
            if donnee == '[DONE]':
                break
            try:
                morceau = json.loads(donnee)
            except ValueError:
                continue
            usage = morceau.get('usage') or usage
            for choix in morceau.get('choices') or []:
                delta = choix.get('delta') or {}
                if pensee := delta.get('reasoning_content') or delta.get('reasoning'):
                    reflexion.append(pensee)
                    if not signale:
                        signale = True
                        ecrire({'type': 'reflexion'})
                if delta.get('content'):
                    texte.append(delta['content'])
                    ecrire({'type': 'texte', 'delta': delta['content']})
                fin = choix.get('finish_reason') or fin
    return 200, {'content': ''.join(texte), 'reasoning_content': ''.join(reflexion), 'finish_reason': fin}, usage


async def appel(ctx: RechercheContext, etape: str, messages: list[dict], schema: dict | None, max_tokens: int,
                ecrire: Callable[[dict], Any] | None = None, temperature: float = 0.2) -> tuple[Any, dict]:
    """Un appel à Qwen, compté par étape. Avec un schéma : JSON contraint, rendu décodé ; sans : texte libre (la réponse
    finale, que Qwen écrit bien plus pauvrement à l'intérieur d'un JSON), envoyé mot à mot à `ecrire` si elle est donnée
    (une réponse coupée par la limite de jetons est alors gardée, avec « coupee » dans les jetons). Rend aussi les
    jetons de cet appel."""
    if (limite := limite_atteinte(ctx, 0)) is not None:
        raise AgentErreur(f'Limite atteinte : {limite}.')
    loop = asyncio.get_running_loop()
    ctx.compteurs.appels += 1
    body = {'model': ctx.modele, 'messages': messages, 'temperature': temperature, 'stream': False,
            'max_tokens': max_tokens + (REFLEXION_SUPPLEMENT if ctx.reflexion else 0),
            'chat_template_kwargs': {'enable_thinking': ctx.reflexion}}
    if schema is not None:
        body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': etape, 'schema': schema, 'strict': True}}
    en_flux = schema is None and ecrire is not None
    async with ctx.places:
        debut = loop.time()
        left = max(1.0, ctx.compteurs.debut + ctx.limites.duree + 30 - loop.time())
        try:
            if en_flux:
                statut, message, usage = await _en_flux(ctx, body, min(APPEL_DELAI, left), ecrire)
                choix = {'finish_reason': message.get('finish_reason')}
            else:
                r = await ctx.http.post(ctx.qwen_url + '/chat/completions', json=body, headers={'Authorization': 'Bearer ' + ctx.qwen_cle},
                                        timeout=min(APPEL_DELAI, left))
                statut = r.status_code
        except httpx.TimeoutException:
            raise AgentErreur('Qwen n’a pas répondu à temps.') from None
        except httpx.HTTPError:
            raise AgentErreur('Qwen est injoignable : l’adresse trycloudflare a peut-être changé (make init, puis make restart).') from None
    if statut != 200:
        raise AgentErreur(f'Qwen a refusé la demande (HTTP {statut}).')
    if not en_flux:
        donnees = r.json()
        choix = (donnees.get('choices') or [{}])[0]
        message = choix.get('message') or {}
        usage = donnees.get('usage') or {}
    duree = round((loop.time() - debut) * 1000)
    coupee = choix.get('finish_reason') == 'length'
    if coupee and not en_flux:
        raise AgentErreur(f'Réponse de Qwen coupée (limite de {body["max_tokens"]} jetons).')
    if schema is None:
        contenu = (message.get('content') or '').strip()
        if not contenu:
            raise AgentErreur('Qwen a rendu une réponse vide.')
    else:
        try:
            contenu = json.loads(message.get('content') or '')
        except ValueError:
            contenu = None
        if not isinstance(contenu, dict):
            raise AgentErreur('Réponse de Qwen illisible (JSON attendu).')
    reflexion = len(message.get('reasoning_content') or message.get('reasoning') or '') // 4   # estimation, ~4 caractères par jeton
    dernier = {'entree': usage.get('prompt_tokens', 0), 'sortie': usage.get('completion_tokens', 0), 'reflexion': reflexion, 'duree_ms': duree}
    if coupee:
        dernier['coupee'] = body['max_tokens']
    j = ctx.compteurs.jetons.setdefault(etape, {'entree': 0, 'sortie': 0, 'reflexion': 0, 'appels': 0, 'duree_ms': 0})
    for k in ('entree', 'sortie', 'reflexion', 'duree_ms'):
        j[k] += dernier[k]
    j['appels'] += 1
    return contenu, dernier


async def recherche_multi(ctx: RechercheContext, question: str, requetes: list[str], exclure: list[str], budget: int,
                          passages: bool) -> dict:
    """/recherche-multi du service de recherche ; un nouvel essai si aucune page n'est revenue (moteurs qui coupent la
    connexion ou limitent le rythme, fréquent juste après le démarrage de SearXNG)."""
    resultat = await _recherche_multi(ctx, question, requetes, exclure, budget, passages)
    if not resultat.get('pages'):
        await asyncio.sleep(2)
        resultat = await _recherche_multi(ctx, question, requetes, exclure, budget, passages)
        resultat.setdefault('avertissements', []).insert(0, 'Aucun résultat au premier essai : recherche relancée une fois.')
    return resultat


async def _recherche_multi(ctx: RechercheContext, question: str, requetes: list[str], exclure: list[str], budget: int,
                           passages: bool) -> dict:
    try:
        r = await ctx.web.post('/recherche-multi', json={
            'requete': question[:500], 'requetes': requetes, 'exclure': exclure, 'budget': budget, 'pages': PAGES_PAR_ITERATION,
            'passages': passages, 'filtre': ctx.filtre}, timeout=RECHERCHE_DELAI)
    except httpx.TimeoutException:
        raise AgentErreur('La recherche web n’a pas abouti à temps.') from None
    except httpx.HTTPError:
        raise AgentErreur('Service de recherche web injoignable.') from None
    try:
        corps = r.json()
    except ValueError:
        corps = None
    if r.status_code != 200 or not isinstance(corps, dict):
        erreur = corps.get('erreur') if isinstance(corps, dict) else None
        message = erreur.get('message') if isinstance(erreur, dict) else None
        raise AgentErreur('Recherche web en échec' + (f' : {message}' if isinstance(message, str) else f' (statut {r.status_code}).'))
    return corps


def lots_de(liste: list[dict]) -> list[list[dict]]:
    """Lots de LOT_JETONS au plus, dans l'ordre, LOTS_PAR_ITERATION au plus."""
    lots, courant, taille = [], [], 0
    for p in liste:
        if courant and taille + p['jetons'] > LOT_JETONS:
            lots.append(courant)
            courant, taille = [], 0
        courant.append(p)
        taille += p['jetons']
    if courant:
        lots.append(courant)
    return lots[:LOTS_PAR_ITERATION]


def icone(page: dict) -> str | None:
    """Icône du site rendue par le service (PNG en adresse data:), pour la liste des sources ; None sinon."""
    valeur = page.get('icone')
    return valeur if isinstance(valeur, str) and valeur.startswith('data:image/png;base64,') and len(valeur) < 16_000 else None


def nom_du_site(page: dict) -> str:
    """Nom que le site se donne (« GitHub Docs »), pour les puces de citation ; vide s'il n'en déclare pas."""
    return ' '.join(str(page.get('site') or '').split())[:60]


def enregistrer_pages(resultat: dict, sources: dict, urls: list, partielles: list, iteration: int) -> list[dict]:
    """Pages d'une recherche : numéros de source globaux (stables d'une recherche à l'autre), pages essayées et pages
    partielles notées (`sources`, `urls`, `partielles` complétés sur place). Rend les passages, identifiés
    S<source>.<position>."""
    numeros: dict[int, int] = {}
    for page in resultat.get('pages') or []:
        url = str(page.get('url') or '')
        if not url:
            continue
        if url not in urls:
            urls.append(url)
        if page.get('etat') == 'lue':
            sources.setdefault(url, {'numero': len(sources) + 1, 'url': url, 'titre': str(page.get('titre') or url),
                                     'iteration': iteration, 'favorisee': page.get('groupe') == 'favorisee', 'icone': icone(page), 'site': nom_du_site(page)})
            if page.get('numero') is not None:
                numeros[int(page['numero'])] = sources[url]['numero']
        elif page.get('etat') in ('incomplete', 'erreur', 'delai'):
            partielles.append({'url': url, 'raison': str(page.get('erreur') or page.get('etat'))})
    liste = []
    for p in resultat.get('passages') or []:
        n = numeros.get(int(p.get('numero') or 0))
        if n is not None:
            liste.append({'id': f'S{n}.{int(p.get("position") or 0)}', 'source': n, 'section': str(p.get('section') or ''),
                          'jetons': int(p.get('jetons') or 0), 'texte': str(p.get('texte') or '')})
    return liste


async def lire_lot(ctx: 'RechercheContext', question: str, lot: list[dict], precision: str = '') -> tuple[dict, dict, list[str]]:
    """Un lecteur : un appel à Qwen sur un lot de passages délimités. Rend (réponse, jetons, identifiants permis)."""
    ids = [p['id'] for p in lot]
    texte = '\n\n'.join(f'<<<PASSAGE {p["id"]}' + (f' — section : {sur(p["section"])}' if p['section'] else '')
                         + f'>>>\n{sur(p["texte"])}\nFIN>>>' for p in lot)
    reponse, jetons = await appel(ctx, 'lecture', [
        {'role': 'system', 'content': ctx.consignes['lecture']},
        {'role': 'user', 'content': f'Question : {question}{precision}\n\nIdentifiants permis : {", ".join(ids)}\n\n{texte}'},
    ], SCHEMA_LECTURE, 1500)
    return reponse, jetons, ids


def faits_valides(reponse: dict, ids: list[str], connus: set, place: int, **extra) -> tuple[list[dict], int]:
    """Faits d'une lecture appuyés par au moins une référence du lot lu (sinon rejetés), sans doublon (`connus`, mis à
    jour), `place` au plus. Rend (faits retenus, nombre de rejetés)."""
    nouveaux, rejetes = [], 0
    for f in reponse.get('faits') or []:
        refs = [str(x) for x in f.get('references') or [] if str(x) in ids]
        texte = str(f.get('texte') or '').strip()
        if not texte or not refs:   # référence inconnue : fait rejeté
            rejetes += 1
            continue
        if cle(texte) in connus or len(nouveaux) >= place:
            continue
        nouveaux.append({'texte': texte[:400], 'references': refs,
                         'sources': list(dict.fromkeys(int(x.split('.')[0][1:]) for x in refs)), **extra})
        connus.add(cle(texte))
    return nouveaux, rejetes


def resume_memoire(etat: Etat, par_source: bool = False) -> str:
    lignes = [f'- {f["texte"]} ' + (''.join(f'[{n}]' for n in f['sources']) if par_source else f'({", ".join(f["references"])})')
              for f in etat.get('faits', [])]
    texte = 'Faits rassemblés :\n' + ('\n'.join(lignes) or '(aucun)')
    if etat.get('contradictions'):
        texte += '\n\nContradictions relevées :\n' + '\n'.join(f'- {c["texte"]}' for c in etat['contradictions'])
    if etat.get('manques'):
        texte += '\n\nPoints sans réponse :\n' + '\n'.join(f'- {m}' for m in etat['manques'][:8])
    if etat.get('corrections'):
        texte += '\n\nOrthographe relevée dans les pages : ' + ', '.join(f'{c.get("de")} → {c.get("vers")}' for c in etat['corrections'])
    return texte


# Pas après une lettre ou un chiffre (tableau[0]) ; jamais dans le code (voir verifier_citations).
CITATION = re.compile(r'(?<!\w)\[(\d+(?:\s*[,;]\s*\d+)*)\]')
CODE = re.compile(r'(```.*?```|`[^`\n]*`)', re.S)


def verifier_citations(texte: str, permises: set[int]) -> tuple[str, int]:
    """Citations gardées seulement vers des sources réellement lues et utilisées ; les autres sont remplacées. Une
    citation groupée « [1, 2, 5] » devient « [1][2][5] » (chaque numéro vérifié)."""
    invalides = 0

    def remplace(m: re.Match) -> str:
        nonlocal invalides
        sortie = []
        for n in re.split(r'\s*[,;]\s*', m.group(1)):
            if int(n) in permises:
                sortie.append(f'[{int(n)}]')
            else:
                invalides += 1
                sortie.append('[source inconnue]')
        return ''.join(sortie)

    morceaux = CODE.split(texte)   # rangs impairs : blocs et extraits de code, laissés tels quels
    return ''.join(m if i % 2 else CITATION.sub(remplace, m) for i, m in enumerate(morceaux)), invalides


def avec_sources(reponse: str, sources: dict) -> str:
    """Réponse suivie de la liste des sources réellement citées (titre et lien), écrite ici et non par le modèle."""
    citees = {int(n) for m in CODE.split(reponse)[::2] for n in re.findall(r'(?<!\w)\[(\d+)\]', m)}
    lignes = [f'- [{s["numero"]}] [{re.sub(r"[\[\]]", "", s["titre"]).strip() or s["url"]}](<{s["url"]}>)'
              for s in sorted(sources.values(), key=lambda s: s['numero']) if s['numero'] in citees]
    return reponse + ('\n\n**Sources**\n\n' + '\n'.join(lignes) if lignes else '')


# --- Schémas et consignes ----------------------------------------------------------------------------------------

def _objet(proprietes: dict) -> dict:
    return {'type': 'object', 'additionalProperties': False, 'required': list(proprietes), 'properties': proprietes}


_REFS = {'type': 'array', 'minItems': 1, 'maxItems': 4, 'items': {'type': 'string', 'maxLength': 20}}
SCHEMA_PLAN = _objet({'recherche_necessaire': {'type': 'boolean'}, 'raison': {'type': 'string', 'maxLength': 300},
                      'requetes': {'type': 'array', 'minItems': 1, 'maxItems': 3, 'items': {'type': 'string', 'maxLength': REQUETE_MAX}}})
SCHEMA_LECTURE = _objet({
    'faits': {'type': 'array', 'maxItems': 12, 'items': _objet({'texte': {'type': 'string', 'maxLength': 400}, 'references': _REFS})},
    'contradictions': {'type': 'array', 'maxItems': 5, 'items': _objet({'texte': {'type': 'string', 'maxLength': 400}, 'references': _REFS})},
    'sans_reponse': {'type': 'array', 'maxItems': 5, 'items': {'type': 'string', 'maxLength': 300}}})
SCHEMA_VERIFICATION = _objet({
    'decision': {'type': 'string', 'enum': ['repondre', 'rechercher']}, 'raison': {'type': 'string', 'maxLength': 400},
    'sources_coherentes': {'type': 'boolean'},
    'informations_manquantes': {'type': 'array', 'maxItems': 5, 'items': {'type': 'string', 'maxLength': 200}},
    'nouvelles_requetes': {'type': 'array', 'maxItems': 3, 'items': {'type': 'string', 'maxLength': REQUETE_MAX}}})
_REQUETES = {'type': 'array', 'minItems': 1, 'maxItems': 3, 'items': {'type': 'string', 'maxLength': REQUETE_MAX}}
SCHEMA_CAHIER = _objet({
    'objectif': {'type': 'string', 'maxLength': 400},
    'sous_questions': {'type': 'array', 'minItems': 1, 'maxItems': SOUS_QUESTIONS_MAX,
                       'items': _objet({'question': {'type': 'string', 'maxLength': 250}, 'requetes': _REQUETES})},
    'criteres': {'type': 'array', 'maxItems': 5, 'items': {'type': 'string', 'maxLength': 200}}})


def schema_supervision(ids: list[str]) -> dict:
    """Le superviseur ne peut parler que des sous-questions du cahier (Q1…), chacune jugée une fois."""
    return _objet({
        'couverture': {'type': 'array', 'minItems': len(ids), 'maxItems': len(ids), 'items': _objet({
            'id': {'type': 'string', 'enum': ids}, 'statut': {'type': 'string', 'enum': ['couverte', 'partielle', 'absente']},
            'manque': {'type': 'string', 'maxLength': 200}})},
        'decision': {'type': 'string', 'enum': ['repondre', 'rechercher']},
        'raison': {'type': 'string', 'maxLength': 400},
        'relances': {'type': 'array', 'maxItems': 3, 'items': _objet({'id': {'type': 'string', 'enum': ids}, 'requetes': _REQUETES})}})

# Les consignes système sont dans consignes/prompts.toml (voir charger_consignes).


_NOTE = _objet({'texte': {'type': 'string', 'maxLength': 600},
                'sources': {'type': 'array', 'minItems': 1, 'maxItems': 4, 'items': {'type': 'integer'}}})
SCHEMA_COMPRESSION = _objet({'notes': {'type': 'array', 'maxItems': NOTES_MAX, 'items': _NOTE},
                             'contradictions': {'type': 'array', 'maxItems': 4, 'items': _NOTE},
                             'sans_reponse': {'type': 'array', 'maxItems': 4, 'items': {'type': 'string', 'maxLength': 300}}})
SCHEMA_AIGUILLAGE = _objet({'mode': {'type': 'string', 'enum': list(MODES_AUTO)}, 'raison': {'type': 'string', 'maxLength': 300}})


def avec_clarification(schema: dict) -> dict:
    """Le schéma, avec en premier un champ « clarification » (vide si la question est claire)."""
    return {**schema, 'required': ['clarification'] + schema['required'],
            'properties': {'clarification': {'type': 'string', 'maxLength': 300}, **schema['properties']}}


def consigne(ctx: 'RechercheContext', nom: str, filtre: bool = False) -> str:
    """Consigne, avec le filtre des données personnelles et la demande de précision quand ils s'appliquent."""
    return ' '.join([ctx.consignes[nom]] + ([ctx.consignes['plan_filtre']] if filtre and ctx.filtre else [])
                    + ([ctx.consignes['clarification']] if ctx.clarifier else []))


def precision_demandee(ctx: 'RechercheContext', reponse: dict) -> str | None:
    if not ctx.clarifier:
        return None
    return re.sub(r'\s+', ' ', str(reponse.get('clarification') or '')).strip()[:300] or None


# --- Nœuds communs -----------------------------------------------------------------------------------------------

async def planifier(etat: Etat, runtime: Runtime[RechercheContext]) -> dict:
    ctx, question = runtime.context, etat['question']
    schema = avec_clarification(SCHEMA_PLAN) if ctx.clarifier else SCHEMA_PLAN
    plan, jetons = await appel(ctx, 'planification', [{'role': 'system', 'content': consigne(ctx, 'plan', filtre=True)},
                                                      {'role': 'user', 'content': 'Question : ' + question}], schema, 800)
    if precision := precision_demandee(ctx, plan):
        runtime.stream_writer({'type': 'clarification', 'question': precision, 'jetons': jetons})
        return {'clarification': precision}
    requetes = requetes_valides(plan.get('requetes'))
    runtime.stream_writer({'type': 'planification', 'recherche_necessaire': bool(plan.get('recherche_necessaire', True)),
                           'raison': str(plan.get('raison', '')), 'requetes': requetes, 'jetons': jetons})
    return {'a_faire': requetes or [question[:REQUETE_MAX]], 'iteration': 0}


def apres_planification(suivant: str) -> Callable[[Etat], str]:
    """Après la planification (ou le cahier) : fin si Qwen demande une précision, sinon l'étape suivante."""
    return lambda etat: END if etat.get('clarification') else suivant


def pages_pour_affichage(resultat: dict, sources: dict) -> list[dict]:
    return [{'url': p.get('url', ''), 'titre': p.get('titre', ''), 'etat': p.get('etat', ''), 'erreur': p.get('erreur'),
             'favorisee': p.get('groupe') == 'favorisee',
             'source': sources[p['url']]['numero'] if p.get('etat') == 'lue' and p.get('url') in sources else None}
            for p in resultat.get('pages') or []]


# --- Mode web ----------------------------------------------------------------------------------------------------

async def recherche_simple(etat: Etat, runtime: Runtime[RechercheContext]) -> dict:
    """Une recherche ; le contexte cité du service (passages classés par BM25, sous budget) part tel quel à Qwen. Au second
    essai, les pages déjà essayées sont exclues : le service lit les résultats suivants des mêmes requêtes."""
    ctx, requetes = runtime.context, etat['a_faire']
    iteration, urls = etat.get('iteration', 0) + 1, list(etat.get('urls', []))
    resultat = await recherche_multi(ctx, etat['question'], requetes, urls, BUDGET_WEB, False)
    urls += [str(p['url']) for p in resultat.get('pages') or [] if p.get('url') and p['url'] not in urls]
    if iteration > 1:
        resultat.setdefault('avertissements', []).insert(0, 'Aucun passage utile dans les premières pages : pages suivantes lues.')
    sources = {}
    for page in resultat.get('pages') or []:
        if page.get('etat') == 'lue' and page.get('numero') is not None:
            sources[page['url']] = {'numero': int(page['numero']), 'url': page['url'], 'titre': str(page.get('titre') or page['url']),
                                    'iteration': iteration, 'favorisee': page.get('groupe') == 'favorisee', 'icone': icone(page), 'site': nom_du_site(page)}
    pages = resultat.get('pages') or []
    citables = sorted({int(p['numero']) for p in pages if p.get('numero') is not None and p.get('gardes')})
    contexte = (resultat.get('contexte') or {})
    runtime.stream_writer({'type': 'recherche', 'iteration': iteration, 'requetes': requetes, 'pages': pages_pour_affichage(resultat, sources),
                           'passages': sum(int(p.get('gardes') or 0) for p in pages), 'jetons_contexte': contexte.get('jetons'),
                           'corrections': resultat.get('corrections') or [], 'avertissements': resultat.get('avertissements') or [],
                           'moteurs_muets': resultat.get('moteurs_muets') or []})
    partielles = list(etat.get('pages_partielles', [])) + [{'url': p['url'], 'raison': str(p.get('erreur') or p.get('etat'))}
                                                          for p in resultat.get('pages') or [] if p.get('etat') in ('incomplete', 'erreur', 'delai')]
    # Les numéros de source repartent de 1 à chaque recherche : seules comptent les pages du dernier essai.
    return {'iteration': iteration, 'requetes': requetes, 'urls': urls, 'sources': sources, 'pages_partielles': partielles,
            'contexte': str(contexte.get('texte') or ''), 'citables': citables}


def apres_recherche_simple(etat: Etat) -> str:
    return 'recherche_simple' if not etat.get('citables') and etat['iteration'] < 2 else 'rediger_passages'


async def rediger_passages(etat: Etat, runtime: Runtime[RechercheContext]) -> dict:
    ctx = runtime.context
    limites = [f'Page non lue ou incomplète : {p["url"]} ({p["raison"]})' for p in etat.get('pages_partielles', [])[:5]]
    if not etat.get('contexte'):
        runtime.stream_writer({'type': 'redaction', 'jetons': None})
        return {'redaction': {'reponse': 'Aucun passage pertinent n’a été trouvé dans les pages consultées.', 'limites': limites,
                              'citations_invalides': 0}}
    runtime.stream_writer({'type': 'redaction_debut'})
    texte, jetons = await appel(ctx, 'redaction', [
        {'role': 'system', 'content': ctx.consignes['redaction_web']},
        {'role': 'user', 'content': f'Question : {etat["question"]}\n\n{etat["contexte"]}'}], None, 4000, runtime.stream_writer)
    reponse, invalides = verifier_citations(texte, set(etat.get('citables') or []))
    reponse = avec_sources(reponse, etat.get('sources') or {})
    if invalides:
        limites.append(f'{invalides} citation(s) vers une source absente du contexte remplacée(s) par « [source inconnue] ».')
    if jetons.get('coupee'):
        limites.append(f'Réponse coupée : limite de {jetons["coupee"]} jetons atteinte.')
    runtime.stream_writer({'type': 'redaction', 'jetons': jetons})
    return {'redaction': {'reponse': reponse, 'limites': limites, 'citations_invalides': invalides}}


# --- Mode approfondi ---------------------------------------------------------------------------------------------

async def rechercher(etat: Etat, runtime: Runtime[RechercheContext]) -> dict:
    ctx = runtime.context
    if (limite := limite_atteinte(ctx, 2)) is not None:
        return {'arret': limite}
    iteration, requetes = etat['iteration'] + 1, etat['a_faire']
    deja = list(dict.fromkeys(etat.get('requetes', []) + requetes))
    urls, sources = list(etat.get('urls', [])), dict(etat.get('sources', {}))
    partielles, corrections = list(etat.get('pages_partielles', [])), list(etat.get('corrections', []))
    resultat = await recherche_multi(ctx, etat['question'], requetes, urls, LOT_JETONS * LOTS_PAR_ITERATION, True)
    liste = enregistrer_pages(resultat, sources, urls, partielles, iteration)
    ctx.passages.update({p['id']: p['texte'] for p in liste})
    corrections += [c for c in resultat.get('corrections') or [] if isinstance(c, dict)]
    runtime.stream_writer({'type': 'recherche', 'iteration': iteration, 'requetes': requetes, 'pages': pages_pour_affichage(resultat, sources),
                           'passages': len(liste), 'corrections': resultat.get('corrections') or [],
                           'avertissements': resultat.get('avertissements') or [], 'moteurs_muets': resultat.get('moteurs_muets') or []})
    # Lecteurs : autant de lots que d'appels disponibles, en gardant de quoi vérifier et rédiger.
    possibles = max(0, ctx.limites.appels - ctx.compteurs.appels - 2)
    return {'iteration': iteration, 'requetes': deja, 'urls': urls, 'sources': sources, 'pages_partielles': partielles,
            'corrections': corrections, 'lots': lots_de(liste)[:possibles], 'a_faire': []}


def vers_lecteurs(etat: Etat):
    """Un Send par lot : les lecteurs travaillent en parallèle, chacun sur son lot seulement."""
    if etat.get('arret'):
        return 'rediger'
    if not etat.get('lots'):
        return 'fusionner'
    return [Send('lecteur', {'question': etat['question'], 'iteration': etat['iteration'], 'numero': k, 'lot': lot})
            for k, lot in enumerate(etat['lots'], 1)]


async def lecteur(entree: dict, runtime: Runtime[RechercheContext]) -> dict:
    reponse, jetons, ids = await lire_lot(runtime.context, entree['question'], entree['lot'])
    return {'lectures': [{'iteration': entree['iteration'], 'lot': entree['numero'], 'ids': ids, 'reponse': reponse, 'jetons': jetons}]}


async def fusionner(etat: Etat, runtime: Runtime[RechercheContext]) -> dict:
    """Mémoire de travail : faits aux références vérifiées (dans le lot lu), sans doublon, FAITS_MAX au plus."""
    faits, contradictions = list(etat.get('faits', [])), list(etat.get('contradictions', []))
    manques = list(etat.get('manques', []))
    connus = {cle(f['texte']) for f in faits}
    avant = len(faits)
    for lecture in sorted(etat.get('lectures', []), key=lambda l: l['lot']):
        r, ids = lecture['reponse'], lecture['ids']
        nouveaux, rejetes = faits_valides(r, ids, connus, FAITS_MAX - len(faits), iteration=lecture['iteration'])
        for fait in nouveaux:
            fait['id'] = f'F{len(faits) + 1}'
            faits.append(fait)
        for c in r.get('contradictions') or []:
            if str(c.get('texte') or '').strip():
                contradictions.append({'texte': str(c['texte'])[:400],
                                       'references': [str(x) for x in c.get('references') or [] if str(x) in ids]})
        for m in r.get('sans_reponse') or []:
            if str(m).strip() and str(m)[:300] not in manques:
                manques.append(str(m)[:300])
        runtime.stream_writer({'type': 'lecture', 'iteration': lecture['iteration'], 'lot': lecture['lot'], 'passages': ids,
                               'faits': nouveaux, 'rejetes': rejetes, 'contradictions': r.get('contradictions') or [],
                               'sans_reponse': r.get('sans_reponse') or [], 'jetons': lecture['jetons']})
    return {'faits': faits, 'contradictions': contradictions, 'manques': manques, 'nouveaux': len(faits) - avant,
            'lots': [], 'lectures': None}


async def decider(etat: Etat, runtime: Runtime[RechercheContext]) -> dict:
    if etat['iteration'] >= ITERATIONS_MAX:
        return {'arret': f'nombre maximal de recherches atteint ({ITERATIONS_MAX})'}
    # Rien de nouveau : on s'arrête, sauf si l'on n'a encore aucun fait (le vérificateur reformule alors la recherche).
    if etat.get('nouveaux', 0) == 0 and etat.get('faits'):
        return {'arret': 'aucune information nouvelle trouvée'}
    if (limite := limite_atteinte(runtime.context, 2)) is not None:
        return {'arret': limite}
    return {}


async def verifier(etat: Etat, runtime: Runtime[RechercheContext]) -> dict:
    ctx = runtime.context
    r, jetons = await appel(ctx, 'verification', [
        {'role': 'system', 'content': ctx.consignes['verification']},
        {'role': 'user', 'content': f'Question : {etat["question"]}\nRecherche {etat["iteration"]} sur {ITERATIONS_MAX}\n'
                                    f'Requêtes déjà faites : {" ; ".join(etat.get("requetes", []))}\n\n{resume_memoire(etat)}'},
    ], SCHEMA_VERIFICATION, 800)
    decision = 'rechercher' if r.get('decision') == 'rechercher' else 'repondre'
    nouvelles = requetes_valides(r.get('nouvelles_requetes'))
    runtime.stream_writer({'type': 'verification', 'iteration': etat['iteration'], 'decision': decision,
                           'raison': str(r.get('raison') or '')[:400],
                           'informations_manquantes': [str(x) for x in (r.get('informations_manquantes') or [])][:5],
                           'nouvelles_requetes': nouvelles, 'sources_coherentes': bool(r.get('sources_coherentes', True)),
                           'jetons': jetons})
    if decision == 'repondre':
        return {'arret': 'informations jugées suffisantes par le vérificateur'}
    faites = {q.lower() for q in etat.get('requetes', [])}
    a_faire = [q for q in nouvelles if q.lower() not in faites]
    if not a_faire:
        return {'arret': 'aucune nouvelle requête utile proposée'}
    return {'a_faire': a_faire}


async def rediger(etat: Etat, runtime: Runtime[RechercheContext]) -> dict:
    ctx = runtime.context
    runtime.stream_writer({'type': 'arret', 'raison': etat.get('arret', '')})
    limites = [f'Page non lue ou incomplète : {p["url"]} ({p["raison"]})' for p in etat.get('pages_partielles', [])[:5]]
    if not etat.get('faits'):
        runtime.stream_writer({'type': 'redaction', 'jetons': None})
        return {'redaction': {'reponse': 'Aucune information fiable n’a été trouvée pour répondre à cette question dans les pages consultées.',
                              'limites': limites, 'citations_invalides': 0}}
    sources = '\n'.join(f'[{s["numero"]}] {sur(s["titre"])} — {s["url"]}' for s in etat['sources'].values())
    runtime.stream_writer({'type': 'redaction_debut'})
    texte, jetons = await appel(ctx, 'redaction', [
        {'role': 'system', 'content': ctx.consignes['redaction']},
        {'role': 'user', 'content': f'Question : {etat["question"]}\n\nSources :\n{sources}\n\n{resume_memoire(etat, True)}'},
    ], None, 4000, runtime.stream_writer)
    # Citations vérifiées : seulement des sources réellement lues et appuyant au moins un fait.
    reponse, invalides = verifier_citations(texte, {n for f in etat['faits'] for n in f['sources']})
    reponse = avec_sources(reponse, etat['sources'])
    if invalides:
        limites.append(f'{invalides} citation(s) vers une source non collectée remplacée(s) par « [source inconnue] ».')
    if jetons.get('coupee'):
        limites.append(f'Réponse coupée : limite de {jetons["coupee"]} jetons atteinte.')
    runtime.stream_writer({'type': 'redaction', 'jetons': jetons})
    return {'redaction': {'reponse': reponse, 'limites': limites, 'citations_invalides': invalides}}


# --- Mode très approfondi ---------------------------------------------------------------------------------------

def finale(sous_questions: int) -> int:
    """Appels de la rédaction : une compression et une section par sous-question, puis la synthèse."""
    return 2 * sous_questions + 1


def lots_disponibles(ctx: RechercheContext, chercheurs: int, reserve: int) -> int:
    """Lecteurs par chercheur pour ce tour, en gardant « reserve » appels (supervision et rédaction)."""
    reste = ctx.limites.appels - ctx.compteurs.appels - reserve
    return max(0, min(LOTS_PAR_CHERCHEUR, reste // max(1, chercheurs)))


def cahier_en_clair(etat: Etat) -> str:
    c = etat.get('cahier') or {}
    return (f'Objectif : {c.get("objectif") or etat["question"]}'
            + ('\nCritères d’une réponse complète :\n' + '\n'.join(f'- {x}' for x in c['criteres']) if c.get('criteres') else ''))


def memoire_par_sous_question(etat: Etat, par_source: bool = False, requetes: bool = False) -> str:
    blocs = []
    for d in etat['par_sq'].values():
        lignes = [f'- {f["texte"]} ' + ''.join(f'[{n}]' for n in f['sources']) if par_source else f'- {f["texte"]}' for f in d['faits']]
        bloc = f'### {d["id"]} — {d["question"]}'
        if requetes:
            bloc += '\nRequêtes déjà faites : ' + (' ; '.join(d['requetes']) or '(aucune)')
        bloc += '\nFaits :\n' + ('\n'.join(lignes) or '(aucun)')
        if d['manques']:
            bloc += '\nSans réponse dans les pages lues : ' + ' ; '.join(d['manques'][:5])
        if d['contradictions']:
            bloc += '\nContradictions : ' + ' ; '.join(c['texte'] for c in d['contradictions'][:3])
        blocs.append(bloc)
    return '\n\n'.join(blocs)


async def ecrire_cahier(etat: Etat, runtime: Runtime[RechercheContext]) -> dict:
    ctx, question = runtime.context, etat['question']
    schema = avec_clarification(SCHEMA_CAHIER) if ctx.clarifier else SCHEMA_CAHIER
    r, jetons = await appel(ctx, 'cahier', [{'role': 'system', 'content': consigne(ctx, 'cahier', filtre=True)},
                                            {'role': 'user', 'content': 'Question : ' + question}], schema, 1200)
    if precision := precision_demandee(ctx, r):
        runtime.stream_writer({'type': 'clarification', 'question': precision, 'jetons': jetons})
        return {'clarification': precision}
    sous_questions = []
    for sq in (r.get('sous_questions') or [])[:SOUS_QUESTIONS_MAX]:
        texte = re.sub(r'\s+', ' ', str(sq.get('question') or '')).strip()[:250] if isinstance(sq, dict) else ''
        requetes = requetes_valides(sq.get('requetes')) if isinstance(sq, dict) else []
        if texte and requetes:
            sous_questions.append({'id': f'Q{len(sous_questions) + 1}', 'question': texte, 'requetes': requetes})
    if not sous_questions:
        sous_questions = [{'id': 'Q1', 'question': question[:250], 'requetes': [question[:REQUETE_MAX]]}]
    cahier = {'objectif': str(r.get('objectif') or '').strip()[:400],
              'criteres': [str(c).strip()[:200] for c in r.get('criteres') or [] if str(c).strip()][:5]}
    runtime.stream_writer({'type': 'cahier', **cahier, 'sous_questions': sous_questions, 'jetons': jetons})
    return {'cahier': cahier, 'tour': 1, 'lots_par_chercheur': lots_disponibles(ctx, len(sous_questions), 1 + finale(len(sous_questions))),
            'par_sq': {sq['id']: {'id': sq['id'], 'question': sq['question'], 'requetes': [], 'faits': [], 'manques': [],
                                  'contradictions': []} for sq in sous_questions},
            'a_relancer': [{'id': sq['id'], 'requetes': sq['requetes']} for sq in sous_questions]}


def vers_chercheurs(etat: Etat):
    """Un Send par sous-question à chercher : les chercheurs travaillent en parallèle, chacun sur la sienne."""
    if etat.get('clarification'):
        return END
    if etat.get('arret') or not etat.get('a_relancer') or not etat.get('lots_par_chercheur'):
        return 'conclure'
    exclure = list(etat.get('urls', []))[-EXCLURE_MAX:]
    envois = []
    for r in etat['a_relancer']:
        d = etat['par_sq'][r['id']]
        envois.append(Send('chercheur', {
            'sous_question': {'id': d['id'], 'question': d['question']}, 'objectif': (etat.get('cahier') or {}).get('objectif', ''),
            'requetes': r['requetes'], 'tour': etat['tour'], 'lots': etat['lots_par_chercheur'], 'exclure': exclure,
            'connus': [cle(f['texte']) for f in d['faits']], 'place': FAITS_PAR_SOUS_QUESTION - len(d['faits'])}))
    return envois


async def chercheur(entree: dict, runtime: Runtime[RechercheContext]) -> dict:
    """Une sous-question : une recherche, puis ses lecteurs en parallèle ; ne voit ni les autres sous-questions ni leurs
    faits."""
    ctx, sq, tour, requetes = runtime.context, entree['sous_question'], entree['tour'], entree['requetes']
    runtime.stream_writer({'type': 'chercheur_debut', 'id': sq['id'], 'question': sq['question'], 'tour': tour, 'requetes': requetes})
    async with ctx.recherches:
        resultat = await recherche_multi(ctx, sq['question'], requetes, entree['exclure'], LOT_JETONS * max(1, entree['lots']), True)
    urls, partielles = [], []
    liste = enregistrer_pages(resultat, ctx.sources_lues, urls, partielles, tour)
    ctx.passages.update({p['id']: p['texte'] for p in liste})
    lots = lots_de(liste)[:entree['lots']]
    precision = f'\n(Sous-question d’une recherche plus large : {entree["objectif"]})' if entree.get('objectif') else ''
    lectures = await asyncio.gather(*(lire_lot(ctx, sq['question'], lot, precision) for lot in lots))
    connus = set(entree['connus'])
    faits, rejetes, contradictions, manques = [], 0, [], []
    jetons = {'entree': 0, 'sortie': 0, 'reflexion': 0, 'duree_ms': 0}
    for reponse, j, ids in lectures:
        nouveaux, n = faits_valides(reponse, ids, connus, entree['place'] - len(faits), iteration=tour, sous_question=sq['id'])
        faits += nouveaux
        rejetes += n
        contradictions += [{'texte': str(c['texte'])[:400], 'references': [str(x) for x in c.get('references') or [] if str(x) in ids]}
                           for c in reponse.get('contradictions') or [] if str(c.get('texte') or '').strip()]
        manques += [str(m)[:300] for m in reponse.get('sans_reponse') or [] if str(m).strip()]
        for k in jetons:
            jetons[k] = max(jetons[k], j.get(k, 0)) if k == 'duree_ms' else jetons[k] + j.get(k, 0)
    runtime.stream_writer({'type': 'chercheur', 'id': sq['id'], 'question': sq['question'], 'tour': tour, 'requetes': requetes,
                           'pages': pages_pour_affichage(resultat, ctx.sources_lues), 'passages': len(liste),
                           'lecteurs': len(lots), 'faits': faits, 'rejetes': rejetes, 'sans_reponse': list(dict.fromkeys(manques)),
                           'avertissements': resultat.get('avertissements') or [], 'moteurs_muets': resultat.get('moteurs_muets') or [],
                           'jetons': jetons if lots else None})
    return {'resultats': [{'id': sq['id'], 'requetes': requetes, 'faits': faits, 'contradictions': contradictions,
                           'manques': list(dict.fromkeys(manques)), 'urls': urls, 'partielles': partielles}]}


async def consolider(etat: Etat, runtime: Runtime[RechercheContext]) -> dict:
    """Rendus des chercheurs rangés sous leur sous-question ; vue d'ensemble (faits, sources) pour le résultat."""
    par_sq = {k: {**d, 'requetes': list(d['requetes']), 'faits': list(d['faits']), 'contradictions': list(d['contradictions'])}
              for k, d in etat['par_sq'].items()}
    urls, partielles = list(etat.get('urls', [])), list(etat.get('pages_partielles', []))
    nouveaux = 0
    for r in sorted(etat.get('resultats', []), key=lambda r: r['id']):
        d = par_sq[r['id']]
        d['requetes'] = list(dict.fromkeys(d['requetes'] + r['requetes']))
        for f in r['faits'][:FAITS_PAR_SOUS_QUESTION - len(d['faits'])]:
            d['faits'].append({**f, 'id': f'{r["id"]}.F{len(d["faits"]) + 1}'})
            nouveaux += 1
        d['contradictions'] += r['contradictions']
        d['manques'] = r['manques'][:6]   # ce qui manque après le dernier passage du chercheur
        urls += [u for u in r['urls'] if u not in urls]
        partielles += r['partielles']
    return {'par_sq': par_sq, 'urls': urls, 'pages_partielles': partielles, 'sources': dict(runtime.context.sources_lues),
            'faits': [f for d in par_sq.values() for f in d['faits']],
            'contradictions': [c for d in par_sq.values() for c in d['contradictions']],
            'manques': [m for d in par_sq.values() for m in d['manques']], 'nouveaux': nouveaux, 'resultats': None, 'a_relancer': []}


async def superviser(etat: Etat, runtime: Runtime[RechercheContext]) -> dict:
    ctx, tour = runtime.context, etat['tour']
    if tour >= TOURS_MAX:
        return {'arret': f'nombre maximal de tours atteint ({TOURS_MAX})'}
    ids = list(etat['par_sq'])
    reserve = 1 + finale(len(ids))     # cette supervision, puis la rédaction
    if (limite := limite_atteinte(ctx, reserve, marge=90)) is not None:
        return {'arret': limite}
    r, jetons = await appel(ctx, 'supervision', [
        {'role': 'system', 'content': ctx.consignes['superviseur']},
        {'role': 'user', 'content': f'Question : {etat["question"]}\n{cahier_en_clair(etat)}\nTour {tour} sur {TOURS_MAX}\n\n'
                                    + memoire_par_sous_question(etat, requetes=True)},
    ], schema_supervision(ids), 1200)
    couverture = []
    for c in r.get('couverture') or []:
        if isinstance(c, dict) and c.get('id') in etat['par_sq'] and c['id'] not in (x['id'] for x in couverture):
            couverture.append({'id': c['id'], 'question': etat['par_sq'][c['id']]['question'],
                               'statut': c.get('statut') if c.get('statut') in ('couverte', 'partielle', 'absente') else 'partielle',
                               'manque': str(c.get('manque') or '')[:200]})
    decision = 'rechercher' if r.get('decision') == 'rechercher' else 'repondre'
    relances = []
    for x in r.get('relances') or []:
        if not isinstance(x, dict) or x.get('id') not in etat['par_sq'] or x['id'] in (y['id'] for y in relances):
            continue
        if len(etat['par_sq'][x['id']]['faits']) >= FAITS_PAR_SOUS_QUESTION:   # plus de place : relance inutile
            continue
        faites = {q.lower() for q in etat['par_sq'][x['id']]['requetes']}
        requetes = [q for q in requetes_valides(x.get('requetes')) if q.lower() not in faites]
        if requetes:
            relances.append({'id': x['id'], 'requetes': requetes})
    relances = relances[:3] if decision == 'rechercher' else []
    runtime.stream_writer({'type': 'supervision', 'tour': tour, 'couverture': couverture, 'decision': decision,
                           'raison': str(r.get('raison') or '')[:400],
                           'relances': [{**x, 'question': etat['par_sq'][x['id']]['question']} for x in relances], 'jetons': jetons})
    if decision == 'repondre':
        return {'couverture': couverture, 'arret': 'cahier jugé rempli par le superviseur'}
    if not relances:
        return {'couverture': couverture, 'arret': 'aucune relance utile proposée'}
    lots = lots_disponibles(ctx, len(relances), reserve)
    if not lots:
        return {'couverture': couverture, 'arret': f'nombre maximal d’appels à Qwen atteint ({ctx.limites.appels})'}
    return {'couverture': couverture, 'a_relancer': relances, 'tour': tour + 1, 'lots_par_chercheur': lots}


def limites_rapport(etat: Etat) -> list[str]:
    limites = [f'Page non lue ou incomplète : {p["url"]} ({p["raison"]})' for p in etat.get('pages_partielles', [])[:5]]
    return limites + [f'Sous-question {"peu" if c["statut"] == "partielle" else "pas"} couverte : {c["question"]}'
                      + (f' ({c["manque"]})' if c['manque'] else '') for c in etat.get('couverture', []) if c['statut'] != 'couverte']


async def conclure(etat: Etat, runtime: Runtime[RechercheContext]) -> dict:
    """Fin des recherches. Sans aucun fait : réponse d'absence, sans appel à Qwen."""
    runtime.stream_writer({'type': 'arret', 'raison': etat.get('arret', '')})
    if etat.get('faits'):
        return {}
    runtime.stream_writer({'type': 'redaction', 'jetons': None})
    return {'redaction': {'reponse': AUCUNE_INFO, 'limites': limites_rapport(etat), 'citations_invalides': 0}}


def vers_compression(etat: Etat):
    """Un compresseur par sous-question qui a des faits, en parallèle."""
    if etat.get('redaction'):
        return END
    return [Send('compresseur', {'sous_question': {'id': d['id'], 'question': d['question']}, 'faits': d['faits'],
                                 'contradictions': d['contradictions'], 'manques': d['manques']})
            for d in etat['par_sq'].values() if d['faits']]


def _notes_valides(liste: Any, permises: set[int]) -> tuple[list[dict], int]:
    notes, rejetees = [], 0
    for n in liste if isinstance(liste, list) else []:
        texte = str(n.get('texte') or '').strip() if isinstance(n, dict) else ''
        sources = list(dict.fromkeys(x for x in (n.get('sources') or []) if isinstance(x, int) and x in permises)) if texte else []
        if not sources:
            rejetees += 1
            continue
        notes.append({'texte': texte[:600], 'sources': sources})
    return notes, rejetees


async def compresseur(entree: dict, runtime: Runtime[RechercheContext]) -> dict:
    """Les faits bruts d'une sous-question deviennent des notes : doublons fusionnés, contradictions mises à plat ; une
    note ne peut citer que des sources de ses faits (sinon rejetée)."""
    ctx, sq, faits = runtime.context, entree['sous_question'], entree['faits']
    permises = {n for f in faits for n in f['sources']}
    contenu = (f'Sous-question : {sq["question"]}\nNuméros de source permis : {", ".join(map(str, sorted(permises)))}\n\nFaits :\n'
               + '\n'.join(f'- {f["texte"]} ' + ''.join(f'[{n}]' for n in f['sources']) for f in faits))
    if entree['contradictions']:
        contenu += '\n\nContradictions relevées par les lecteurs :\n' + '\n'.join(f'- {c["texte"]}' for c in entree['contradictions'][:5])
    if entree['manques']:
        contenu += '\n\nSans réponse dans les pages lues :\n' + '\n'.join(f'- {m}' for m in entree['manques'][:5])
    r, jetons = await appel(ctx, 'compression', [{'role': 'system', 'content': ctx.consignes['compression']},
                                                 {'role': 'user', 'content': contenu}], SCHEMA_COMPRESSION, 2500)
    notes, rejetees = _notes_valides(r.get('notes'), permises)
    contradictions, _ = _notes_valides(r.get('contradictions'), permises)
    repli = not notes   # aucune note valide : les faits eux-mêmes servent de notes
    if repli:
        notes = [{'texte': f['texte'], 'sources': f['sources']} for f in faits[:NOTES_MAX * 2]]
    sans_reponse = [str(m).strip()[:300] for m in r.get('sans_reponse') or [] if str(m).strip()][:4]
    runtime.stream_writer({'type': 'compression', 'id': sq['id'], 'question': sq['question'], 'faits': len(faits), 'notes': notes,
                           'contradictions': contradictions, 'sans_reponse': sans_reponse, 'rejetees': rejetees, 'repli': repli,
                           'jetons': jetons})
    return {'notes': [{'id': sq['id'], 'notes': notes, 'contradictions': contradictions, 'sans_reponse': sans_reponse}]}


async def ranger_notes(etat: Etat, runtime: Runtime[RechercheContext]) -> dict:
    return {'notes_par_sq': {n['id']: n for n in etat.get('notes', [])}, 'notes': None}


def vers_sections(etat: Etat):
    """Une section par sous-question qui a des notes, écrites en parallèle ; chacune connaît les titres des autres."""
    ordre = [d for d in etat['par_sq'].values() if d['id'] in etat.get('notes_par_sq', {})]
    if not ordre:
        return 'synthetiser'
    return [Send('redacteur_section', {'question': etat['question'], 'objectif': (etat.get('cahier') or {}).get('objectif', ''),
                                       'sous_question': {'id': d['id'], 'question': d['question']}, **etat['notes_par_sq'][d['id']],
                                       'autres': [x['question'] for x in ordre if x['id'] != d['id']]}) for d in ordre]


async def redacteur_section(entree: dict, runtime: Runtime[RechercheContext]) -> dict:
    ctx, sq = runtime.context, entree['sous_question']
    permises = {n for note in entree['notes'] for n in note['sources']}
    contenu = (f'Question du rapport : {entree["question"]}\n' + (f'Objectif : {entree["objectif"]}\n' if entree['objectif'] else '')
               + f'Sous-question de cette section : {sq["question"]}\n'
               + ('Autres sections du rapport (à ne pas traiter ici) :\n' + '\n'.join(f'- {a}' for a in entree['autres']) + '\n' if entree['autres'] else '')
               + f'Numéros de source permis : {", ".join(map(str, sorted(permises)))}\n\nNotes :\n'
               + '\n'.join(f'- {n["texte"]} ' + ''.join(f'[{x}]' for x in n['sources']) for n in entree['notes']))
    if entree['contradictions']:
        contenu += '\n\nContradictions :\n' + '\n'.join(f'- {c["texte"]} ' + ''.join(f'[{x}]' for x in c['sources']) for c in entree['contradictions'])
    if entree['sans_reponse']:
        contenu += '\n\nSans réponse dans les pages lues :\n' + '\n'.join(f'- {m}' for m in entree['sans_reponse'])
    # En flux vers nulle part : une section coupée par la limite de jetons est gardée (et signalée).
    texte, jetons = await appel(ctx, 'section', [{'role': 'system', 'content': ctx.consignes['section']},
                                                 {'role': 'user', 'content': contenu}], None, SECTION_JETONS, lambda _: None)
    texte, invalides = verifier_citations(texte.strip(), permises)
    lignes = texte.split('\n', 1)
    if lignes[0].startswith('#'):
        texte = '### ' + lignes[0].lstrip('#').strip() + ('\n' + lignes[1] if len(lignes) > 1 else '')
    else:
        texte = f'### {sq["question"]}\n\n{texte}'
    runtime.stream_writer({'type': 'section', 'id': sq['id'], 'texte': texte, 'invalides': invalides,
                           'coupee': bool(jetons.get('coupee')), 'jetons': jetons})
    return {'sections': [{'id': sq['id'], 'texte': texte, 'invalides': invalides, 'coupee': bool(jetons.get('coupee'))}]}


async def synthetiser(etat: Etat, runtime: Runtime[RechercheContext]) -> dict:
    """Synthèse écrite en dernier (elle lit les sections), placée en tête ; envoyée mot à mot."""
    ctx = runtime.context
    limites = limites_rapport(etat)
    par_id = {s['id']: s for s in etat.get('sections', [])}
    sections = [par_id[k] for k in etat['par_sq'] if k in par_id]
    if not sections:
        runtime.stream_writer({'type': 'redaction', 'jetons': None})
        return {'redaction': {'reponse': AUCUNE_INFO, 'limites': limites, 'citations_invalides': 0}}
    corps = '\n\n'.join(s['texte'] for s in sections)
    utiles = {n for f in etat['faits'] for n in f['sources']}
    sources = '\n'.join(f'[{s["numero"]}] {sur(s["titre"])} — {s["url"]}'
                        for s in sorted(etat['sources'].values(), key=lambda s: s['numero']) if s['numero'] in utiles)
    runtime.stream_writer({'type': 'redaction_debut'})
    texte, jetons = await appel(ctx, 'synthese', [
        {'role': 'system', 'content': ctx.consignes['synthese']},
        {'role': 'user', 'content': f'Question : {etat["question"]}\n{cahier_en_clair(etat)}\n\nSources :\n{sources}\n\n'
                                    f'Sections du rapport :\n\n{corps}'},
    ], None, SYNTHESE_JETONS, runtime.stream_writer)
    texte, invalides = verifier_citations(texte.strip(), utiles)
    invalides += sum(s['invalides'] for s in sections)
    reponse = avec_sources(f'## Synthèse\n\n{texte}\n\n{corps}', etat['sources'])
    if invalides:
        limites.append(f'{invalides} citation(s) vers une source non collectée remplacée(s) par « [source inconnue] ».')
    coupees = [s['id'] for s in sections if s['coupee']] + (['synthèse'] if jetons.get('coupee') else [])
    if coupees:
        limites.append(f'Texte coupé par la limite de jetons : {", ".join(coupees)}.')
    runtime.stream_writer({'type': 'redaction', 'jetons': jetons})
    return {'redaction': {'reponse': reponse, 'limites': limites, 'citations_invalides': invalides}}


# --- Mode direct (choisi par l'aiguillage) -------------------------------------------------------------------------

async def repondre_direct(etat: Etat, runtime: Runtime[RechercheContext]) -> dict:
    ctx = runtime.context
    runtime.stream_writer({'type': 'redaction_debut'})
    texte, jetons = await appel(ctx, 'redaction', [{'role': 'system', 'content': ctx.consignes['direct']},
                                                   {'role': 'user', 'content': 'Question : ' + etat['question']}],
                                None, 4000, runtime.stream_writer)
    reponse, invalides = verifier_citations(texte, set())
    limites = ['Réponse de Qwen sans recherche Internet : rien n’a été vérifié dans des sources.']
    if jetons.get('coupee'):
        limites.append(f'Réponse coupée : limite de {jetons["coupee"]} jetons atteinte.')
    runtime.stream_writer({'type': 'redaction', 'jetons': jetons})
    return {'redaction': {'reponse': reponse, 'limites': limites, 'citations_invalides': invalides}}


async def aiguiller(ctx: RechercheContext, question: str) -> dict:
    """Mode automatique : Qwen choisit le mode (ou demande une précision)."""
    schema = avec_clarification(SCHEMA_AIGUILLAGE) if ctx.clarifier else SCHEMA_AIGUILLAGE
    r, jetons = await appel(ctx, 'aiguillage', [{'role': 'system', 'content': consigne(ctx, 'aiguillage')},
                                                {'role': 'user', 'content': 'Question : ' + question}], schema, 400)
    return {'mode': r.get('mode') if r.get('mode') in MODES_AUTO else 'web', 'raison': str(r.get('raison') or '').strip()[:300],
            'clarification': precision_demandee(ctx, r), 'jetons': jetons}


# --- Graphes -----------------------------------------------------------------------------------------------------

def apres(etat: Etat) -> str:
    return 'rediger' if etat.get('arret') else 'suite'


def graphe_approfondi():
    g = StateGraph(Etat, context_schema=RechercheContext)
    for nom, noeud in (('planifier', planifier), ('rechercher', rechercher), ('lecteur', lecteur), ('fusionner', fusionner),
                       ('decider', decider), ('verifier', verifier), ('rediger', rediger)):
        g.add_node(nom, noeud)
    g.add_edge(START, 'planifier')
    g.add_conditional_edges('planifier', apres_planification('rechercher'), ['rechercher', END])
    g.add_conditional_edges('rechercher', vers_lecteurs, ['lecteur', 'fusionner', 'rediger'])
    g.add_edge('lecteur', 'fusionner')
    g.add_edge('fusionner', 'decider')
    g.add_conditional_edges('decider', apres, {'rediger': 'rediger', 'suite': 'verifier'})
    g.add_conditional_edges('verifier', apres, {'rediger': 'rediger', 'suite': 'rechercher'})
    g.add_edge('rediger', END)
    return g.compile()


def graphe_web():
    g = StateGraph(Etat, context_schema=RechercheContext)
    for nom, noeud in (('planifier', planifier), ('recherche_simple', recherche_simple), ('rediger_passages', rediger_passages)):
        g.add_node(nom, noeud)
    g.add_edge(START, 'planifier')
    g.add_conditional_edges('planifier', apres_planification('recherche_simple'), ['recherche_simple', END])
    g.add_conditional_edges('recherche_simple', apres_recherche_simple, ['recherche_simple', 'rediger_passages'])
    g.add_edge('rediger_passages', END)
    return g.compile()


def graphe_tres_approfondi():
    g = StateGraph(Etat, context_schema=RechercheContext)
    for nom, noeud in (('ecrire_cahier', ecrire_cahier), ('chercheur', chercheur), ('consolider', consolider),
                       ('superviser', superviser), ('conclure', conclure), ('compresseur', compresseur),
                       ('ranger_notes', ranger_notes), ('redacteur_section', redacteur_section), ('synthetiser', synthetiser)):
        g.add_node(nom, noeud)
    g.add_edge(START, 'ecrire_cahier')
    g.add_conditional_edges('ecrire_cahier', vers_chercheurs, ['chercheur', 'conclure', END])
    g.add_edge('chercheur', 'consolider')
    g.add_edge('consolider', 'superviser')
    g.add_conditional_edges('superviser', vers_chercheurs, ['chercheur', 'conclure', END])
    g.add_conditional_edges('conclure', vers_compression, ['compresseur', END])
    g.add_edge('compresseur', 'ranger_notes')
    g.add_conditional_edges('ranger_notes', vers_sections, ['redacteur_section', 'synthetiser'])
    g.add_edge('redacteur_section', 'synthetiser')
    g.add_edge('synthetiser', END)
    return g.compile()


def graphe_direct():
    g = StateGraph(Etat, context_schema=RechercheContext)
    g.add_node('repondre_direct', repondre_direct)
    g.add_edge(START, 'repondre_direct')
    g.add_edge('repondre_direct', END)
    return g.compile()


GRAPHES = {'direct': graphe_direct(), 'web': graphe_web(), 'approfondie': graphe_approfondi(),
           'tres_approfondie': graphe_tres_approfondi()}


def limites_publiques(mode: str) -> dict:
    if mode == 'auto':   # selon le mode choisi : au plus celles du mode très approfondi, plus l'aiguillage
        return {'auto': True, 'appels': LIMITES['tres_approfondie'].appels + 1, 'duree_s': LIMITES['tres_approfondie'].duree}
    lim = LIMITES[mode]
    if mode == 'direct':
        return {'recherches': 0, 'appels': 1, 'duree_s': lim.duree}
    if mode == 'web':
        return {'recherches': 2, 'pages_par_recherche': PAGES_PAR_ITERATION, 'jetons_contexte': BUDGET_WEB, 'appels': 2, 'duree_s': lim.duree}
    if mode == 'tres_approfondie':
        return {'tours': TOURS_MAX, 'sous_questions': SOUS_QUESTIONS_MAX, 'pages_par_recherche': PAGES_PAR_ITERATION,
                'lecteurs_par_chercheur': LOTS_PAR_CHERCHEUR, 'appels': lim.appels, 'duree_s': lim.duree}
    # 1 planification + 3 lecteurs + 1 vérification + 3 lecteurs + 1 rédaction
    return {'recherches': ITERATIONS_MAX, 'pages_par_recherche': PAGES_PAR_ITERATION, 'jetons_par_lecture': LOT_JETONS,
            'appels': 1 + ITERATIONS_MAX * LOTS_PAR_ITERATION + (ITERATIONS_MAX - 1) + 1, 'duree_s': lim.duree}


def resultat(etat: dict, ctx: RechercheContext, erreur: str | None, mode: str, aiguillage: dict | None = None) -> dict:
    c, loop = ctx.compteurs, asyncio.get_running_loop()
    redaction = etat.get('redaction') or {
        'reponse': '', 'citations_invalides': 0,
        'limites': [f'La recherche s’est arrêtée sur une erreur : {erreur}'] if erreur else []}
    arret = etat.get('arret') or (f'erreur : {erreur}' if erreur else 'précision demandée' if etat.get('clarification') else 'réponse rédigée')
    return {'mode': mode, 'aiguillage': {k: v for k, v in aiguillage.items() if k != 'jetons'} if aiguillage else None,
            'clarification': etat.get('clarification'),
            'reponse': redaction['reponse'], 'limites': redaction['limites'], 'citations_invalides': redaction['citations_invalides'],
            'sources': list((etat.get('sources') or {}).values()), 'faits': etat.get('faits') or [],
            'contradictions': etat.get('contradictions') or [], 'manques': etat.get('manques') or [],
            'corrections': etat.get('corrections') or [],
            'sous_questions': [{'id': d['id'], 'question': d['question'], 'faits': len(d['faits'])} for d in (etat.get('par_sq') or {}).values()],
            'statistiques': {'iterations': etat.get('iteration') or etat.get('tour', 0), 'appels_qwen': c.appels,
                             'pages_lues': len(etat.get('sources') or {}), 'pages_essayees': len(etat.get('urls') or []) or None,
                             'jetons_par_etape': c.jetons, 'jetons_total': c.total(),
                             'duree_s': round(loop.time() - c.debut, 1), 'raison_arret': arret, 'reflexion': ctx.reflexion,
                             'filtre': ctx.filtre}}


async def executer(mode: str, ctx: RechercheContext, question: str, emettre: Callable[[dict], Any]) -> dict:
    """Exécute le graphe du mode (« auto » : Qwen choisit d'abord) ; chaque étape est passée à `emettre` dès qu'elle est
    finie. Rend le résultat final. Une erreur (Qwen, recherche web, limite) arrête la recherche : événement « erreur »,
    résultat partiel."""
    return (await executer_detail(mode, ctx, question, emettre))[0]


async def executer_detail(mode: str, ctx: RechercheContext, question: str, emettre: Callable[[dict], Any]) -> tuple[dict, dict]:
    """Comme executer, mais rend aussi l'état final du graphe (contexte, faits… : pour l'évaluation)."""
    dernier: dict = {}
    erreur, choix = None, None
    try:
        ctx.consignes = charger_consignes()
        ctx.limites = LIMITES['tres_approfondie' if mode == 'auto' else mode]
        if mode == 'auto':
            choix = await aiguiller(ctx, question)
            await emettre({'type': 'aiguillage', 'mode': choix['mode'], 'raison': choix['raison'],
                           'limites': limites_publiques(choix['mode']), 'jetons': choix['jetons']})
            if choix['clarification']:
                await emettre({'type': 'clarification', 'question': choix['clarification'], 'jetons': None})
                dernier = {'clarification': choix['clarification']}
                mode = None
            else:
                mode, ctx.clarifier, ctx.limites = choix['mode'], False, LIMITES[choix['mode']]
        if mode:
            async with asyncio.timeout(ctx.limites.duree + 60):
                async for genre, morceau in GRAPHES[mode].astream({'question': question}, context=ctx,
                                                                 stream_mode=['custom', 'values'], config={'recursion_limit': 60}):
                    if genre == 'custom':
                        await emettre(morceau)
                    else:
                        dernier = morceau
    except AgentErreur as e:
        erreur = str(e)
    except TimeoutError:
        erreur = f'durée maximale dépassée ({ctx.limites.duree} s)'
    if erreur:
        await emettre({'type': 'erreur', 'message': erreur})
    return resultat(dernier, ctx, erreur, (choix or {}).get('mode') or mode, choix), dernier
