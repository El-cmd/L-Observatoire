import {useEffect, useRef, useState} from 'react';
import type {MyStyle} from '../types';
import {errorMessage} from '../lib/api';
import {Icon} from './Icon';

export type StyleApi = {
  add: (body: {name: string; words: string}) => Promise<MyStyle>;
  edit: (id: string, body: {name: string; words: string}) => Promise<MyStyle>;
  remove: (id: string) => Promise<void>;
  example: (id: string) => Promise<MyStyle>;
  suggest: (description: string) => Promise<string>;
};

/** Creates or changes a style of "Mes styles": a name and the words added after the description,
 * written by hand or proposed by Qwen from a description in French. */
export function StyleDialog({style, open, limits, api, onSaved, onDeleted, onClose}: {
  style: MyStyle | null; open: boolean; limits: {name: number; words: number}; api: StyleApi;
  onSaved: (style: MyStyle, created: boolean) => void; onDeleted: (id: string) => void; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState(''); const [words, setWords] = useState(''); const [description, setDescription] = useState('');
  const [error, setError] = useState(''); const [pending, setPending] = useState<'' | 'save' | 'suggest' | 'delete'>(''); const [confirming, setConfirming] = useState(false);
  useEffect(() => {
    if (open) {
      setName(style?.name ?? ''); setWords(style?.words ?? ''); setDescription(''); setError(''); setPending(''); setConfirming(false);
      dialog.current?.showModal();
    } else dialog.current?.close();
  }, [open, style]);

  async function suggest() {
    if (!description.trim() || pending) return;
    setError(''); setPending('suggest');
    try { setWords(await api.suggest(description.trim())); }
    catch (failure) { setError(errorMessage(failure)); }
    finally { setPending(''); }
  }

  async function remove() {
    if (!style || pending) return;
    if (!confirming) { setConfirming(true); return; }
    setError(''); setPending('delete');
    try { await api.remove(style.id); onDeleted(style.id); onClose(); }
    catch (failure) { setError(errorMessage(failure)); setPending(''); }
  }

  return <dialog id="style-dialog" className="password-dialog style-dialog" ref={dialog} onCancel={onClose} onClose={onClose}>
    <form id="style-form" onSubmit={async event => {
      event.preventDefault(); if (pending) return; setError(''); setPending('save');
      try {
        const body = {name, words};
        const saved = style ? await api.edit(style.id, body) : await api.add(body);
        onSaved(saved, !style); onClose();
      } catch (failure) { setError(errorMessage(failure)); setPending(''); }
    }}>
      <h2>{style ? 'Modifier le style' : 'Créer un style'}</h2>
      <label htmlFor="style-name">Nom</label>
      <input id="style-name" required maxLength={limits.name} value={name} placeholder="Par exemple : Néon rétro" onChange={event => setName(event.target.value)}/>

      <label htmlFor="style-description">Décrivez le style voulu <span className="style-optional">facultatif</span></label>
      <div className="style-suggest">
        <textarea id="style-description" rows={2} maxLength={600} value={description} placeholder="Par exemple : des néons roses et bleus, ambiance années 80, reflets chromés"
          onChange={event => setDescription(event.target.value)}
          onKeyDown={event => {if (event.key === 'Enter' && !event.shiftKey) {event.preventDefault(); void suggest();}}}/>
        <button type="button" id="style-suggest" className="studio-secondary" disabled={!description.trim() || pending !== ''} onClick={() => {void suggest();}}>
          <Icon name="news"/>{pending === 'suggest' ? 'Recherche…' : 'Proposer les mots'}</button>
      </div>

      <label htmlFor="style-words">Mots ajoutés à chaque description</label>
      <textarea id="style-words" required rows={3} maxLength={limits.words} value={words} placeholder="neon glow, synthwave palette, chrome reflections"
        onChange={event => setWords(event.target.value)}/>
      <p className="password-hint">En anglais de préférence, séparés par des virgules : le modèle d’images les suit mieux. Ils sont ajoutés après votre description, comme pour les autres styles. {style ? 'Si vous changez les mots, une nouvelle image d’exemple est créée.' : 'Une image d’exemple est créée à l’enregistrement.'} <span className="style-count">{words.length} / {limits.words}</span></p>
      <p id="style-error" className="auth-error" role="alert">{error}</p>

      <div className="password-actions">
        {style && <button type="button" id="style-delete" className={`style-delete${confirming ? ' confirming' : ''}`} disabled={pending !== ''} onClick={() => {void remove();}}>
          <Icon name="trash"/>{confirming ? 'Confirmer la suppression' : 'Supprimer'}</button>}
        <button type="button" onClick={onClose}>Annuler</button>
        <button id="style-submit" className="auth-submit" type="submit" disabled={pending !== '' || !name.trim() || !words.trim()}>{pending === 'save' ? 'Enregistrement…' : 'Enregistrer'}</button>
      </div>
    </form>
  </dialog>;
}
