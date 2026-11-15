import type {ReactNode} from 'react';
import type {ToolEvent} from '../types';
import type {Source} from '../lib/sites';

const DEPTHS: Record<string, string> = {web: 'rapide', approfondie: 'approfondie', tres_approfondie: 'très approfondie'};
const COVERAGE: Record<string, string> = {couverte: 'couverte', partielle: 'partielle', absente: 'absente'};
const PAGE_STATES: Record<string, string> = {lue: 'lue', erreur: 'échec', delai: 'trop lente', incomplete: 'incomplète', non_essayee: 'non lue'};

type Page = {url?: string; titre?: string; etat?: string; source?: number | null};
const list = (value: unknown): string[] => Array.isArray(value) ? value.map(String) : [];
const text = (value: unknown) => typeof value === 'string' ? value : '';
const safe = (url?: string) => url && /^https?:\/\//i.test(url) ? url : undefined;

function Pages({pages}: {pages: unknown}) {
  if (!Array.isArray(pages) || !pages.length) return null;
  return <ul className="tool-pages">{(pages as Page[]).map((page, index) => <li key={index}>
    <span className={`tool-page-state is-${page.etat}`}>{page.source ? `[${page.source}]` : PAGE_STATES[page.etat || ''] || page.etat}</span>
    {safe(page.url) ? <a href={safe(page.url)} target="_blank" rel="noopener noreferrer nofollow" title={page.url}>{page.titre || page.url}</a> : <span>{page.titre}</span>}
  </li>)}</ul>;
}

/** One step in plain words; null for steps that are not shown (in progress, or used elsewhere). */
function describe(event: ToolEvent): {label: string; detail?: ReactNode} | null {
  const e = event as Record<string, unknown>;
  const pages = Array.isArray(e.pages) ? e.pages as Page[] : [];
  const read = pages.filter(page => page.etat === 'lue').length;
  switch (event.type) {
    case 'appel': {
      const args = (e.arguments || {}) as Record<string, unknown>;
      return {label: `Question cherchée : « ${text(args.question)} »${DEPTHS[text(args.profondeur)] ? ` (recherche ${DEPTHS[text(args.profondeur)]})` : ''}`};
    }
    case 'planification': return {label: `Requêtes : ${list(e.requetes).join(' · ')}`};
    case 'recherche': return {label: `Recherche ${e.iteration ?? ''} : ${read} page(s) lue(s), ${e.passages ?? 0} passage(s) gardé(s)`, detail: <Pages pages={pages}/>};
    case 'lecture': return {label: `Lecture : ${e.faits ?? 0} fait(s) relevé(s)`};
    case 'verification': return {label: e.decision === 'rechercher'
      ? `Il manque des informations : nouvelle recherche (${list(e.nouvelles_requetes).join(' · ')})` : 'Assez d’informations pour répondre'};
    case 'cahier': return {label: `Plan : ${text(e.objectif)}`, detail: <ol className="tool-plan">{(Array.isArray(e.sous_questions) ? e.sous_questions as {id: string; question: string}[] : [])
      .map(q => <li key={q.id}><b>{q.id}</b> {q.question}</li>)}</ol>};
    case 'chercheur': return {label: `${text(e.id)} (tour ${e.tour ?? 1}) : ${read} page(s) lue(s), ${e.faits ?? 0} fait(s)`, detail: <Pages pages={pages}/>};
    case 'supervision': {
      const coverage = (Array.isArray(e.couverture) ? e.couverture as {id: string; statut: string}[] : []).map(c => `${c.id} ${COVERAGE[c.statut] || c.statut}`).join(', ');
      const again = list(e.relances);
      return {label: `Bilan du tour ${e.tour ?? ''} : ${coverage}${again.length ? ` → nouvelle recherche pour ${again.join(', ')}` : ' → rédaction'}`};
    }
    case 'compression': return {label: `${text(e.id)} : faits rangés en ${e.notes ?? 0} note(s)`};
    case 'section': return {label: `Partie ${text(e.id)} écrite`};
    case 'arret': return {label: `Fin des recherches : ${text(e.raison)}`};
    case 'redaction_debut': return {label: 'Rédaction de la réponse'};
    case 'attente': return {label: text(e.message) || 'Une autre recherche est en cours : celle-ci attend son tour.'};
    case 'fin': {
      const limits = list(e.limites);
      return limits.length ? {label: 'À savoir', detail: <ul className="tool-limits">{limits.map((limit, index) => <li key={index}>{limit}</li>)}</ul>} : null;
    }
    case 'echec': case 'indisponible': case 'erreur': return {label: text(e.message) || 'Échec de la recherche.'};
    default: return null;
  }
}

function summary(events: ToolEvent[], streaming: boolean): string {
  const last = (type: string) => [...events].reverse().find(e => e.type === type) as Record<string, unknown> | undefined;
  if (last('indisponible')) return 'Recherche web indisponible : réponse sans elle';
  if (last('echec')) return 'Recherche web en échec : réponse sans elle';
  const end = last('fin');
  const depth = DEPTHS[text(((last('appel')?.arguments || {}) as Record<string, unknown>).profondeur)];
  if (end) return `Recherche web${depth ? ` ${depth}` : ''} · ${end.pages_lues ?? 0} page(s) lue(s)${typeof end.duree_s === 'number' ? ` · ${Math.round(end.duree_s)} s` : ''}`;
  if (!streaming) return 'Recherche web interrompue';
  const shown = [...events].reverse().map(describe).find(Boolean);
  return `Recherche web en cours${shown ? ` · ${shown.label}` : '…'}`;
}

/** Steps of the web search behind an answer, folded above it. */
export function ToolTrace({events, streaming}: {events: ToolEvent[]; streaming: boolean}) {
  const web = events.filter(event => event.outil === 'recherche_web');
  if (!web.length) return null;
  const steps = web.map(describe).filter((step): step is NonNullable<ReturnType<typeof describe>> => step !== null);
  const done = !streaming || web.some(e => ['fin', 'echec', 'indisponible'].includes(e.type));
  return <details className={`tool-trace${done ? '' : ' running'}`}>
    <summary>{summary(web, streaming)}</summary>
    <ol className="tool-steps">{steps.map((step, index) => <li key={index}><span>{step.label}</span>{step.detail}</li>)}</ol>
  </details>;
}

/** Text shown while a very deep search writes its report: the parts already written, in the order of the plan,
 *  under the summary being written (the content streamed so far). Once the search is over, the content itself. */
export function provisionalReport(content: string, events: ToolEvent[] | undefined, streaming: boolean): string {
  const web = (events || []).filter(event => event.outil === 'recherche_web');
  if (!streaming || web.some(event => event.type === 'fin' || event.type === 'echec')) return content;
  const parts = web.filter(event => event.type === 'section' && typeof event.texte === 'string');
  if (!parts.length) return content;
  const plan = web.find(event => event.type === 'cahier');
  const order = Array.isArray(plan?.sous_questions) ? (plan.sous_questions as {id: string}[]).map(q => q.id) : [];
  const rank = (id: unknown) => {const index = order.indexOf(String(id)); return index < 0 ? order.length : index;};
  const sorted = [...parts].sort((a, b) => rank(a.id) - rank(b.id));
  return `## Synthèse\n\n${content.trim() || '*La synthèse sera écrite quand toutes les parties seront prêtes…*'}\n\n`
    + sorted.map(part => String(part.texte)).join('\n\n');
}

/** Sources of the search (number -> page), for the clickable citations [n] of the answer. */
export function citationSources(events?: ToolEvent[]): Map<number, Source> {
  const sources = new Map<number, Source>();
  for (const event of events || []) {
    if (event.outil !== 'recherche_web' || event.type !== 'sources' || !Array.isArray(event.sources)) continue;
    for (const source of event.sources as {numero?: number; url?: string; titre?: string; icone?: string; site?: string}[]) {
      const url = safe(source.url);
      // Icon: a small PNG embedded by the server (the page only shows its own images and data: ones).
      const icone = typeof source.icone === 'string' && source.icone.startsWith('data:image/png;base64,') && source.icone.length < 16000 ? source.icone : undefined;
      const site = typeof source.site === 'string' ? source.site.trim().slice(0, 60) : '';
      if (typeof source.numero === 'number' && url) sources.set(source.numero, {url, titre: source.titre || url, ...(icone ? {icone} : {}), ...(site ? {site} : {})});
    }
  }
  return sources;
}
