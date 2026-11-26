/** Thumbs up or down (see backend/src/feedback.rs, which checks the same reason ids). */
export interface Feedback { rating: 1 | -1; reasons: string[]; comment: string | null }
export type Reason = {id: string; name: string};

export const ANSWER_REASONS: Reason[] = [
  {id: 'faux', name: 'Faux'}, {id: 'incomplet', name: 'Incomplet'}, {id: 'hors_sujet', name: 'Hors sujet'},
  {id: 'trop_long', name: 'Trop long'}, {id: 'mal_compris', name: 'Question mal comprise'}, {id: 'sources', name: 'Sources douteuses'},
];
export const IMAGE_REASONS: Reason[] = [
  {id: 'demande', name: 'Pas ce que j’ai demandé'}, {id: 'personnage', name: 'Personnage raté'}, {id: 'defauts', name: 'Défauts (mains, visage…)'},
  {id: 'style', name: 'Style raté'}, {id: 'retouche', name: 'Retouche ratée'},
];
