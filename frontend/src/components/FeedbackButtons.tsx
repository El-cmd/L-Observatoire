import {useEffect, useState} from 'react';
import type {Feedback, Reason} from '../lib/feedback';
import {errorMessage} from '../lib/api';
import {Icon} from './Icon';

/** Thumbs up or down, only recorded. A thumbs down opens a small form: reasons to tick and a comment, optional. */
export function FeedbackButtons({value, reasons, what, className = '', onChange}: {
  value: Feedback | null; reasons: Reason[]; what: string; className?: string;
  onChange: (vote: Feedback | null) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [ticked, setTicked] = useState<string[]>(value?.reasons ?? []);
  const [comment, setComment] = useState(value?.comment ?? '');
  const [state, setState] = useState<'' | 'sending' | 'thanks'>('');
  const [error, setError] = useState('');
  useEffect(() => {setTicked(value?.reasons ?? []); setComment(value?.comment ?? '');}, [value?.rating]);

  async function send(vote: Feedback | null, close = false) {
    setError(''); setState('sending');
    try {
      await onChange(vote);
      setState(close ? 'thanks' : '');
      if (close) { setOpen(false); setTimeout(() => setState(value => value === 'thanks' ? '' : value), 2000); }
    } catch (failure) { setError(errorMessage(failure)); setState(''); }
  }
  const up = value?.rating === 1, down = value?.rating === -1;
  return <div className={`feedback ${className}${value ? ' voted' : ''}`}>
    <button type="button" className="feedback-thumb" aria-pressed={up} aria-label={up ? 'Retirer le pouce en l’air' : `Bonne ${what}`}
      title={up ? 'Retirer mon avis' : `Bonne ${what}`} disabled={state === 'sending'}
      onClick={() => {setOpen(false); void send(up ? null : {rating: 1, reasons: [], comment: null});}}><Icon name="thumbUp"/></button>
    <button type="button" className="feedback-thumb" aria-pressed={down} aria-expanded={open} aria-label={down ? 'Retirer le pouce en bas' : `Mauvaise ${what}`}
      title={down ? 'Retirer mon avis' : `Mauvaise ${what}`} disabled={state === 'sending'}
      onClick={() => {
        if (down) { setOpen(false); void send(null); return; }
        setTicked([]); setComment(''); setOpen(true); void send({rating: -1, reasons: [], comment: null});
      }}><Icon name="thumbDown"/></button>
    {state === 'thanks' && <span className="feedback-thanks" role="status">Merci</span>}
    {error && <span className="feedback-error" role="alert">{error}</span>}
    {open && down && <div className="feedback-form" role="group" aria-label="Qu’est-ce qui n’allait pas ?">
      <span className="feedback-title">Qu’est-ce qui n’allait pas ? <small>(facultatif)</small></span>
      <div className="feedback-reasons">{reasons.map(reason => <button key={reason.id} type="button" aria-pressed={ticked.includes(reason.id)}
        onClick={() => setTicked(list => list.includes(reason.id) ? list.filter(id => id !== reason.id) : [...list, reason.id])}>{reason.name}</button>)}</div>
      <textarea rows={2} maxLength={1000} value={comment} placeholder="Précisez si vous voulez…" aria-label="Commentaire"
        onChange={event => setComment(event.target.value)}/>
      <div className="feedback-actions">
        <button type="button" className="studio-link" onClick={() => setOpen(false)}>Fermer</button>
        <button type="button" className="studio-secondary" disabled={state === 'sending' || (!ticked.length && !comment.trim())}
          onClick={() => {void send({rating: -1, reasons: ticked, comment: comment.trim() || null}, true);}}>Envoyer</button>
      </div>
    </div>}
  </div>;
}
