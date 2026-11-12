import {describe, expect, it} from 'vitest';
import {provisionalReport} from '../components/ToolTrace';
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
