import {useEffect, useRef} from 'react';
import type {AttachmentRef} from '../types';
import {imageURL} from '../lib/images';
import {Icon} from './Icon';

export function ImageViewer({image, onClose}: {image: AttachmentRef | null; onClose: () => void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current; if (!element) return;
    if (image && !element.open) element.showModal();
    if (!image && element.open) element.close();
  }, [image]);
  return <dialog ref={dialog} className="image-viewer" aria-label={image?.name} onClose={onClose}
    onClick={event => {if (event.target === dialog.current) onClose();}}>
    {image && <>
      <img src={imageURL(image.id)} alt={image.name}/>
      <div className="image-viewer-bar">
        <span title={image.name}>{image.name}</span>
        <a className="icon-button" href={`${imageURL(image.id)}?download=1`} download={image.name} aria-label="Télécharger l’image" title="Télécharger"><Icon name="download"/></a>
        <button type="button" className="icon-button" aria-label="Fermer" title="Fermer" onClick={onClose}><Icon name="close"/></button>
      </div>
    </>}
  </dialog>;
}
