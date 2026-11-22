import {useEffect, useRef, useState} from 'react';
import type {LibraryItem} from '../types';
import {Icon} from './Icon';

/** Qwen's rewriting: stored since 22/11, found in the prompt sent before (minus the style words). */
export function improvedOf(generation: NonNullable<LibraryItem['generation']>): string | null {
  if (generation.improved !== undefined) return generation.improved || null;
  const sent = generation.sent.split('\n\nStyle: ')[0].trim();
  return sent && sent !== generation.prompt.trim() ? sent : null;
}

/** The descriptions of a created image: the user's idea, Qwen's rewriting, what the image model received. */
export function PromptsDialog({item, onClose}: {item: LibraryItem | null; onClose: () => void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [copied, setCopied] = useState('');
  useEffect(() => {
    if (item?.generation) {setCopied(''); dialog.current?.showModal();} else dialog.current?.close();
  }, [item]);
  const generation = item?.generation;
  const rows: [string, string, string | null][] = generation ? [
    ['prompt', 'Votre description', generation.prompt],
    ['improved', 'Améliorée par Qwen', improvedOf(generation)],
    ['sent', 'Envoyée au modèle d’images', generation.sent],
  ] : [];
  function copy(key: string, text: string) {
    void navigator.clipboard?.writeText(text).then(() => setCopied(key), () => setCopied(''));
  }
  return <dialog id="prompts-dialog" className="password-dialog prompts-dialog" ref={dialog} onCancel={onClose} onClose={onClose}>
    {generation && <>
      <h2>Descriptions de l’image</h2>
      {rows.map(([key, label, text]) => <section key={key} className="prompts-row">
        <header><h3>{label}</h3>{text && <button type="button" className="studio-link" onClick={() => copy(key, text)}>
          <Icon name={copied === key ? 'check' : 'copy'}/>{copied === key ? 'Copié' : 'Copier'}</button>}</header>
        {text ? <p id={`prompts-${key}`}>{text}</p> : <p className="prompts-none">Pas d’amélioration pour cette image.</p>}
      </section>)}
      <p className="password-hint">Style : {generation.style_name ?? generation.style} · {generation.size.replace('x', '×')} · graine {generation.seed} · {generation.seconds} s</p>
      <div className="password-actions"><button type="button" onClick={onClose}>Fermer</button></div>
    </>}
  </dialog>;
}
