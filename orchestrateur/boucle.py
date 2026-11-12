"""Boucle d'outils de l'orchestrateur (LangGraph) : Qwen répond, ou appelle un outil puis reprend la main.

    START → modele ─(appel d'outil)→ outils ─(résultat à reprendre)→ modele … → END
                 └──────(réponse)─────→ END        └──(réponse finale de l'outil)→ END

- modele : un appel en flux à Qwen avec les outils permis. Le texte et la réflexion partent aussitôt vers le backend,
  dans le format de Qwen (morceaux « choices[0].delta ») ; les appels d'outils sont rassemblés, pas transmis.
- outils : exécute l'appel (un seul par outil et par tour). Sa progression part dans le flux sous
  {"observatoire": {"<outil>": évènement}} ; les morceaux « texte » d'une réponse en cours d'écriture partent comme du
  texte normal. Un outil qui rend une réponse finale (« reponse », sans « erreur ») termine le message : son texte
  vérifié remplace ce qui a été montré ({"observatoire": {"contenu": …}}). En cas d'échec, Qwen reçoit l'erreur et
  répond sans cet outil.

À la fin : un morceau avec la raison de fin, puis l'usage (jetons du premier appel, celui du contexte mesuré par le
backend), puis [DONE]. Au plus TOURS_MAX appels d'outils par message.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import tomllib
from typing import Any, Callable, TypedDict
from zoneinfo import ZoneInfo

import httpx
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from outils import OutilErreur, Registre

TOURS_MAX = 3
DELAI_QWEN = 30 * 60
CONSIGNES = Path(__file__).parent / 'consignes.toml'
JOURS = ('lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche')
MOIS = ('janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre')


class QwenErreur(Exception):
    """Qwen injoignable ou en erreur : signalé au backend comme une réponse interrompue."""


def aujourd_hui() -> str:
    m = datetime.now(ZoneInfo('Europe/Paris'))
    return f'{JOURS[m.weekday()]} {"1er" if m.day == 1 else m.day} {MOIS[m.month - 1]} {m.year}'


def consigne_outils(forcer: str | None) -> str:
    """Consigne système ajoutée quand des outils sont proposés (consignes.toml, relu à chaque message)."""
    brut = tomllib.loads(CONSIGNES.read_text(encoding='utf-8'))
    texte = brut['outils'].strip().replace('{jour}', aujourd_hui())
    if forcer:
        texte += ' ' + brut['outil_impose'].strip().replace('{outil}', forcer)
    return texte


def avec_consigne(messages: list[dict], consigne: str) -> list[dict]:
    """Une seule consigne système, en tête (le gabarit de Qwen n'en accepte pas deux) : fusionnée avec la mémoire de
    la conversation si le backend en envoie une."""
    if messages and messages[0].get('role') == 'system' and isinstance(messages[0].get('content'), str):
        return [{'role': 'system', 'content': consigne + '\n\n' + messages[0]['content']}, *messages[1:]]
    return [{'role': 'system', 'content': consigne}, *messages]


def morceau(delta: dict | None = None, fin: str | None = None) -> dict:
    return {'choices': [{'index': 0, 'delta': delta or {}, **({'finish_reason': fin} if fin else {})}]}


@dataclass
class Contexte:
    http: httpx.AsyncClient
    qwen_url: str
    qwen_cle: str
    registre: Registre
    base: dict                        # paramètres de la requête du backend, sans « messages »
    outils: list[dict]                # définitions proposées à Qwen
    choix: Any                        # tool_choice du premier tour (« auto » ou un outil imposé)
    reflexion: bool = False           # réglage de réflexion de l'utilisateur, transmis aux outils
    exclus: set = field(default_factory=set)
    usage: dict = field(default_factory=dict)   # prompt_tokens du premier appel, completion_tokens cumulés


class Etat(TypedDict, total=False):
    messages: list[dict]
    tours: int
    appels: list[dict]                # appels d'outils du dernier tour de Qwen
    avant: str                        # texte écrit par Qwen avant l'outil (gardé devant la réponse de l'outil)
    fin: str
    fini: bool


async def appel_qwen(ctx: Contexte, messages: list[dict], outils: list[dict], choix: Any, ecrire: Callable[[dict], None]) -> dict:
    """Un appel en flux ; rend {texte, appels, fin}. Le texte et la réflexion sont écrits au fil de l'eau."""
    corps = {**ctx.base, 'messages': messages, 'stream': True, 'stream_options': {'include_usage': True}}
    if outils:
        corps.update(tools=outils, tool_choice=choix)
    texte, appels, fin = [], {}, None
    try:
        async with ctx.http.stream('POST', ctx.qwen_url + '/chat/completions', json=corps, timeout=DELAI_QWEN,
                                   headers={'Authorization': f'Bearer {ctx.qwen_cle}'}) as r:
            if r.status_code != 200:
                await r.aread()
                raise QwenErreur(f'Qwen a répondu HTTP {r.status_code}.')
            async for ligne in r.aiter_lines():
                if not ligne.startswith('data:'):
                    continue
                donnee = ligne[5:].strip()
                if donnee == '[DONE]':
                    break
                try:
                    valeur = json.loads(donnee)
                except ValueError:
                    continue
                if valeur.get('error'):
                    raise QwenErreur('Qwen a signalé une erreur.')
                if usage := valeur.get('usage'):
                    ctx.usage.setdefault('prompt_tokens', usage.get('prompt_tokens'))
                    ctx.usage['completion_tokens'] = ctx.usage.get('completion_tokens', 0) + int(usage.get('completion_tokens') or 0)
                for choix_ in valeur.get('choices') or []:
                    delta = choix_.get('delta') or {}
                    for a in delta.get('tool_calls') or []:
                        c = appels.setdefault(a.get('index', 0), {'id': '', 'nom': '', 'arguments': ''})
                        c['id'] = a.get('id') or c['id']
                        f = a.get('function') or {}
                        c['nom'] = f.get('name') or c['nom']
                        c['arguments'] += f.get('arguments') or ''
                    visible = {k: v for k, v in delta.items() if k in ('content', 'reasoning_content', 'reasoning') and v}
                    if visible:
                        texte.append(visible.get('content') or '')
                        ecrire(morceau(visible))
                    fin = choix_.get('finish_reason') or fin
    except httpx.HTTPError:
        raise QwenErreur('Qwen est injoignable.') from None
    return {'texte': ''.join(texte), 'appels': [appels[k] for k in sorted(appels)], 'fin': fin}


async def modele(etat: Etat, runtime: Runtime[Contexte]) -> dict:
    ctx, tours = runtime.context, etat.get('tours', 0)
    outils = [o for o in ctx.outils if o['function']['name'] not in ctx.exclus] if tours < TOURS_MAX else []
    choix = ctx.choix if tours == 0 else 'auto'
    if isinstance(choix, dict) and choix['function']['name'] in ctx.exclus:
        choix = 'auto'
    r = await appel_qwen(ctx, etat['messages'], outils, choix, runtime.stream_writer)
    appels = [a for a in r['appels'] if a['nom']]
    if not appels:
        return {'appels': [], 'fin': r['fin'] or 'stop'}
    message = {'role': 'assistant', 'content': r['texte'] or None,
               'tool_calls': [{'id': a['id'] or f'appel-{tours}-{i}', 'type': 'function',
                               'function': {'name': a['nom'], 'arguments': a['arguments'] or '{}'}} for i, a in enumerate(appels)]}
    return {'messages': [*etat['messages'], message], 'appels': message['tool_calls'],
            'avant': (etat.get('avant', '') + r['texte']).strip()}


def apres_modele(etat: Etat) -> str:
    return 'outils' if etat.get('appels') else END


async def outils(etat: Etat, runtime: Runtime[Contexte]) -> dict:
    """Exécute les appels du dernier tour (un seul par outil) ; la progression part dans le flux pendant l'appel."""
    ctx, ecrire = runtime.context, runtime.stream_writer
    reponses, deja = [], set()
    for appel in etat['appels']:
        nom = appel['function']['name']
        if nom in deja:
            reponses.append({'role': 'tool', 'tool_call_id': appel['id'], 'content': json.dumps(
                {'erreur': 'un seul appel à la fois : seul le premier a été fait'}, ensure_ascii=False)})
            continue
        deja.add(nom)
        try:
            arguments = json.loads(appel['function']['arguments'] or '{}')
        except ValueError:
            arguments = None
        file: asyncio.Queue = asyncio.Queue()

        async def progression(message: str):
            await file.put(message)
        try:
            if not isinstance(arguments, dict):
                raise OutilErreur('arguments illisibles')
            ecrire({'observatoire': {nom: {'type': 'appel', 'arguments': arguments}}})
            tache = asyncio.ensure_future(ctx.registre.appeler(nom, arguments, progression,
                                                               meta={'observatoire': {'reflexion': ctx.reflexion}}))
            try:
                while True:
                    attente = asyncio.ensure_future(file.get())
                    fini, _ = await asyncio.wait({attente, tache}, return_when=asyncio.FIRST_COMPLETED)
                    if attente not in fini:
                        attente.cancel()
                        break
                    relayer(nom, attente.result(), ecrire)
            finally:
                # Message abandonné (l'utilisateur a arrêté) : l'appel à l'outil est annulé lui aussi.
                if not tache.done():
                    tache.cancel()
            while not file.empty():
                relayer(nom, file.get_nowait(), ecrire)
            sortie = tache.result()
        except OutilErreur as erreur:
            sortie = {'erreur': str(erreur)}
        if sortie.get('reponse') and not sortie.get('erreur'):
            # Réponse finale de l'outil (déjà vérifiée) : elle termine le message.
            if sortie.get('sources'):
                ecrire({'observatoire': {nom: {'type': 'sources', 'sources': sortie['sources']}}})
            ecrire({'observatoire': {nom: {'type': 'fin', **{k: sortie.get(k) for k in ('mode', 'duree_s', 'appels', 'pages_lues', 'limites', 'arret')}}}})
            avant = etat.get('avant', '')
            ecrire({'observatoire': {'contenu': (avant + '\n\n' if avant else '') + sortie['reponse']}})
            return {'fini': True, 'fin': 'stop', 'appels': []}
        ecrire({'observatoire': {nom: {'type': 'echec', 'message': str(sortie.get('erreur') or 'échec')[:300]}}})
        ctx.exclus.add(nom)
        reponses.append({'role': 'tool', 'tool_call_id': appel['id'], 'content': json.dumps(
            {'erreur': sortie.get('erreur'), 'consigne': 'Réponds sans cet outil, avec tes connaissances, en le signalant.'},
            ensure_ascii=False)})
    return {'messages': [*etat['messages'], *reponses], 'tours': etat.get('tours', 0) + 1, 'appels': []}


def relayer(nom: str, message: str, ecrire: Callable[[dict], None]):
    """Progression d'un outil : « texte » part comme du texte de réponse, le reste dans le déroulé."""
    try:
        evenement = json.loads(message)
    except ValueError:
        evenement = {'type': 'etape', 'message': message[:500]}
    if not isinstance(evenement, dict):
        return
    if evenement.get('type') == 'texte':
        if evenement.get('delta'):
            ecrire(morceau({'content': str(evenement['delta'])}))
        return
    ecrire({'observatoire': {nom: evenement}})


def apres_outils(etat: Etat) -> str:
    return END if etat.get('fini') else 'modele'


def construire():
    g = StateGraph(Etat, context_schema=Contexte)
    g.add_node('modele', modele)
    g.add_node('outils', outils)
    g.add_edge(START, 'modele')
    g.add_conditional_edges('modele', apres_modele, ['outils', END])
    g.add_conditional_edges('outils', apres_outils, ['modele', END])
    return g.compile()


GRAPHE = construire()


def ligne(valeur: dict) -> bytes:
    return f'data: {json.dumps(valeur, ensure_ascii=False)}\n\n'.encode()


def outils_demandes(demandes: dict, disponibles: dict[str, dict]) -> tuple[list[dict], Any, list[str]]:
    """Demandes du backend ({"recherche_web": "auto" | "approfondie" | "tres_approfondie"}) -> outils proposés à Qwen,
    tool_choice du premier tour, outils demandés mais indisponibles. Un mode autre qu'« auto » impose l'outil et sa
    profondeur."""
    outils, choix, absents = [], 'auto', []
    for nom, mode in demandes.items():
        definition = disponibles.get(nom)
        if definition is None:
            absents.append(nom)
            continue
        if mode != 'auto':
            definition = json.loads(json.dumps(definition))
            proprietes = definition['function']['parameters'].get('properties', {})
            if 'profondeur' in proprietes:
                proprietes['profondeur'] = {**proprietes['profondeur'], 'enum': [mode]}
            choix = {'type': 'function', 'function': {'name': nom}}
        outils.append(definition)
    return outils, choix, absents


NOMS = {'recherche_web': 'La recherche web'}


async def flux(corps: dict, demandes: dict, http: httpx.AsyncClient, qwen_url: str, qwen_cle: str, registre: Registre):
    """Réponse en flux (format de Qwen, plus les évènements « observatoire »), avec les outils demandés."""
    disponibles = await registre.disponibles()
    outils_, choix, absents = outils_demandes(demandes, disponibles)
    for nom in absents:
        yield ligne({'observatoire': {nom: {'type': 'indisponible',
                                            'message': f'{NOMS.get(nom, nom)} est indisponible pour le moment : réponse sans elle.'}}})
    messages = corps.get('messages') or []
    if outils_:
        forcer = choix['function']['name'] if isinstance(choix, dict) else None
        messages = avec_consigne(messages, consigne_outils(forcer))
    ctx = Contexte(http=http, qwen_url=qwen_url, qwen_cle=qwen_cle, registre=registre,
                   base={k: v for k, v in corps.items() if k not in ('messages', 'stream', 'stream_options', 'tools', 'tool_choice')},
                   outils=outils_, choix=choix, reflexion=corps.get('reasoning_effort') not in (None, 'none'))
    fin = 'stop'
    try:
        async for genre, valeur in GRAPHE.astream({'messages': messages}, context=ctx, stream_mode=['custom', 'values'],
                                                 config={'recursion_limit': 4 * TOURS_MAX + 4}):
            if genre == 'custom':
                yield ligne(valeur)
            else:
                fin = valeur.get('fin') or fin
    except QwenErreur as erreur:
        yield ligne({'error': {'message': str(erreur)}})
        return
    yield ligne(morceau(fin=fin))
    yield ligne({'choices': [], 'usage': {'prompt_tokens': ctx.usage.get('prompt_tokens') or 0,
                                          'completion_tokens': ctx.usage.get('completion_tokens') or 0}})
    yield b'data: [DONE]\n\n'
