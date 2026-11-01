import {lazy, Suspense, useEffect, useRef, useState} from 'react';
import type {AttachmentRef} from '../types';
import {imageURL} from '../lib/images';
import {Icon} from './Icon';
const Markdown = lazy(() => import('./Markdown').then(module => ({default:module.Markdown})));

/** The text read from a document, as Qwen receives it: [?] marks the readings Qwen was unsure of. */
export function DocumentViewer({file, load, onClose, onError}: {
  file: AttachmentRef | null; load: (id: string) => Promise<string>; onClose: () => void; onError: (message: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [text, setText] = useState<{id: string; content: string | null} | null>(null);
  // The loader changes at each render of the app: the text is fetched again only for another file.
  const loader = useRef(load); loader.current = load;
  useEffect(() => {
    const element = dialog.current; if (!element) return;
    if (file && !element.open) element.showModal();
    if (!file && element.open) element.close();
    if (!file) {setText(null); return;}
    let live = true; setText({id:file.id, content:null});
    loader.current(file.id).then(content => {if (live) setText({id:file.id, content});})
      .catch(() => {if (live) setText({id:file.id, content:'*Ce document a été supprimé de la bibliothèque.*'});});
    return () => {live = false;};
  }, [file]);
  return <dialog ref={dialog} className="document-viewer" aria-label={file ? `Texte lu dans ${file.name}` : undefined} onClose={onClose}
    onClick={event => {if (event.target === dialog.current) onClose();}}>
    {file && <>
      <div className="image-viewer-bar">
        <span title={file.name}>Texte lu · {file.name}</span>
        <a className="icon-button" href={`${imageURL(file.id)}?download=1`} download={file.name} aria-label="Télécharger le fichier d’origine" title="Télécharger le fichier d’origine"><Icon name="download"/></a>
        <button type="button" className="icon-button" aria-label="Fermer" title="Fermer" onClick={onClose}><Icon name="close"/></button>
      </div>
      <p className="document-viewer-note">Voici ce que L’Observatoire a lu dans ce document. « [?] » signale un passage incertain, à vérifier sur l’original.</p>
      <div className="document-viewer-text message-content">{text?.id === file.id && text.content !== null
        ? <Suspense fallback={<span className="typing">Affichage…</span>}><Markdown content={text.content} onError={onError}/></Suspense>
        : <span className="typing">Chargement du texte…</span>}</div>
    </>}
  </dialog>;
}
