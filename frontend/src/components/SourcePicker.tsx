import {useEffect, useRef, useState} from 'react';
import type {AttachmentRef, Library} from '../types';
import {thumbnailURL, toRef} from '../lib/images';
import {errorMessage} from '../lib/api';
import {Icon} from './Icon';

/** "Image → image": chooses the starting image, among the images of the library or from the device
 * (sent to the library first, like an image sent in a conversation). */
export function SourcePicker({open, other = false, library, removed, upload, onChoose, onClose}: {
  /** `other`: another image of a retouch, after the starting image. */
  open: boolean; other?: boolean; library: Library | null; removed: ReadonlySet<string>;
  upload: (file: File) => Promise<AttachmentRef>; onChoose: (image: AttachmentRef) => void; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (open) { setError(''); setSending(false); if (!dialog.current?.open) dialog.current?.showModal(); }
    else dialog.current?.close();
  }, [open]);

  async function send(file: File | undefined) {
    if (!file || sending) return;
    setError(''); setSending(true);
    try { onChoose(await upload(file)); onClose(); }
    catch (failure) { setError(errorMessage(failure)); }
    finally { setSending(false); if (input.current) input.current.value = ''; }
  }

  const images = library?.items.filter(item => item.kind === 'image' && item.status === 'ready' && !removed.has(item.id)) ?? [];
  return <dialog id="source-picker" className="password-dialog source-picker" ref={dialog} aria-labelledby="source-picker-title" onCancel={onClose} onClose={onClose}>
    <header className="source-picker-head">
      <h2 id="source-picker-title">{other ? 'Ajouter une image' : 'Partir d’une image'}</h2>
      <button type="button" className="icon-button" aria-label="Fermer" title="Fermer" onClick={onClose}><Icon name="close"/></button>
    </header>
    <p className="password-hint">{other
      ? 'Une personne, un objet, un vêtement ou un décor à prendre dans cette image : désignez-la par son numéro dans la description.'
      : 'L’image est redessinée selon votre description : sa composition et ses couleurs servent de point de départ.'}</p>
    <button type="button" id="source-upload" className="studio-secondary source-upload" disabled={sending} onClick={() => input.current?.click()}>
      <Icon name="plus"/>{sending ? 'Envoi…' : 'Depuis votre appareil'}</button>
    <input ref={input} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={event => {void send(event.target.files?.[0]);}}/>
    <p className="auth-error" role="alert">{error}</p>
    <h3>Dans votre bibliothèque</h3>
    {!library ? <p className="library-empty" role="status">Chargement…</p>
      : !images.length ? <p className="library-empty">Aucune image dans votre bibliothèque.</p>
      : <ul className="source-grid">{images.map(item => <li key={item.id}>
        <button type="button" aria-label={other ? `Ajouter ${item.name}` : `Partir de ${item.name}`} title={item.name} onClick={() => {onChoose(toRef(item)); onClose();}}>
          <img src={thumbnailURL(item.id)} alt="" loading="lazy"/></button></li>)}</ul>}
  </dialog>;
}
