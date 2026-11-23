import {useEffect, useRef, useState} from 'react';
import type {AttachmentRef, Generation, LibraryItem} from '../types';
import {formatBytes, imageURL} from '../lib/images';
import {Icon} from './Icon';

/** Qwen's rewriting: stored since 22/11, found in the prompt sent before (minus the style words). */
export function improvedOf(generation: Generation): string | null {
  if (generation.improved !== undefined) return generation.improved || null;
  const sent = generation.sent.split('\n\nStyle: ')[0].trim();
  return sent && sent !== generation.prompt.trim() ? sent : null;
}

const when = (date: string) => new Date(date).toLocaleString('fr-FR', {day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit'});

/** An image shown large, with everything known about it on the right (below on a phone): for a
 * created image, its descriptions (yours, improved, sent to the model) and how it was made. */
export function ImageViewer({image, loadInfo, onClose}: {image: AttachmentRef | null; loadInfo: (id: string) => Promise<LibraryItem>; onClose: () => void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [info, setInfo] = useState<LibraryItem | null>(null);
  const [failed, setFailed] = useState(false);
  const [copied, setCopied] = useState('');
  useEffect(() => {
    const element = dialog.current; if (!element) return;
    if (image && !element.open) element.showModal();
    if (!image && element.open) element.close();
  }, [image]);
  useEffect(() => {
    setInfo(null); setFailed(false); setCopied('');
    if (!image) return;
    let current = true;
    loadInfo(image.id).then(value => {if (current) setInfo(value);}, () => {if (current) setFailed(true);});
    return () => {current = false;};
  }, [image?.id]);

  function copy(key: string, text: string) {
    void navigator.clipboard?.writeText(text).then(() => setCopied(key), () => setCopied(''));
  }
  const generation = info?.generation ?? null;
  const texts: [string, string, string | null][] = generation ? [
    ['prompt', 'Votre description', generation.prompt],
    ['improved', 'Améliorée par Qwen', improvedOf(generation)],
    ['sent', 'Envoyée au modèle d’images', generation.sent],
  ] : [];
  const details: [string, string][] = info ? [
    ...(generation ? [['Style', generation.style_name ?? generation.style], ['Graine', String(generation.seed)], ['Durée de création', `${generation.seconds} s`]] as [string, string][] : []),
    ['Dimensions', `${info.width} × ${info.height} px`],
    ['Format', info.mime === 'image/png' ? 'PNG' : 'JPEG'],
    ['Poids', formatBytes(info.size)],
    [generation ? 'Créée le' : 'Ajoutée le', when(info.created_at)],
  ] : [];

  return <dialog ref={dialog} className="image-viewer" aria-label={image?.name} onClose={onClose}
    onClick={event => {if (event.target === dialog.current) onClose();}}>
    {image && <div className="image-viewer-layout">
      <div className="image-viewer-main">
        <img src={imageURL(image.id)} alt={image.name}/>
        <div className="image-viewer-bar">
          <span title={image.name}>{image.name}</span>
          <a className="icon-button" href={`${imageURL(image.id)}?download=1`} download={image.name} aria-label="Télécharger l’image" title="Télécharger"><Icon name="download"/></a>
          <button type="button" className="icon-button" aria-label="Fermer" title="Fermer" onClick={onClose}><Icon name="close"/></button>
        </div>
      </div>
      <aside className="image-viewer-info" id="image-info" aria-label="Informations sur l’image">
        {!info ? <p className="image-info-empty" role="status">{failed ? 'Informations indisponibles pour cette image.' : 'Chargement…'}</p> : <>
          {texts.map(([key, label, text]) => <section key={key} className="image-info-text">
            <header><h3>{label}</h3>{text && <button type="button" className="studio-link" onClick={() => copy(key, text)}>
              <Icon name={copied === key ? 'check' : 'copy'}/>{copied === key ? 'Copié' : 'Copier'}</button>}</header>
            {text ? <p id={`image-info-${key}`}>{text}</p> : <p className="image-info-none">Pas d’amélioration pour cette image.</p>}
          </section>)}
          {!generation && <p className="image-info-none">Image envoyée, pas créée ici : pas de description.</p>}
          <dl className="image-info-details">{details.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
        </>}
      </aside>
    </div>}
  </dialog>;
}
