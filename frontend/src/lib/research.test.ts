import {describe, expect, it} from 'vitest';
import {citationSources, provisionalReport} from '../components/ToolTrace';
import type {ToolEvent} from '../types';

const e = (type: string, extra: Record<string, unknown> = {}): ToolEvent => ({outil: 'recherche_web', type, ...extra});

describe('very deep search written part by part', () => {
  const plan = e('cahier', {sous_questions: [{id: 'Q1', question: 'a'}, {id: 'Q2', question: 'b'}]});
  it('shows the parts already written in the order of the plan, under the summary being written', () => {
    const events = [plan, e('section', {id: 'Q2', texte: '### Deux'}), e('section', {id: 'Q1', texte: '### Un'})];
    expect(provisionalReport('', events, true)).toBe('## Synthèse\n\n*La synthèse sera écrite quand toutes les parties seront prêtes…*\n\n### Un\n\n### Deux');
    expect(provisionalReport('En bref', events, true)).toContain('## Synthèse\n\nEn bref\n\n### Un');
  });
  it('shows the content itself once the search is over, or without parts', () => {
    const events = [plan, e('section', {id: 'Q1', texte: '### Un'})];
    expect(provisionalReport('Rapport final', [...events, e('fin')], true)).toBe('Rapport final');
    expect(provisionalReport('Rapport final', events, false)).toBe('Rapport final');
    expect(provisionalReport('Réponse', [plan, e('section', {id: 'Q1'})], true)).toBe('Réponse');
  });
});

describe('sources of an answer', () => {
  const page = (numero: number, url: string): ToolEvent => ({outil: 'lire_page', type: 'sources', sources: [{numero, url, titre: `Page ${numero}`}]});
  it('uses the pages read for Qwen when there is no web search', () => {
    const sources = citationSources([page(1, 'https://a.fr/'), page(2, 'https://b.fr/'), page(3, 'javascript:alert(1)')]);
    expect([...sources.keys()]).toEqual([1, 2]);
    expect(sources.get(2)?.url).toBe('https://b.fr/');
  });
  it('prefers the sources of the web search when it wrote the answer', () => {
    const sources = citationSources([page(1, 'https://a.fr/'), e('sources', {sources: [{numero: 1, url: 'https://r.org/', titre: 'R'}]})]);
    expect(sources.get(1)?.url).toBe('https://r.org/');
  });
});
