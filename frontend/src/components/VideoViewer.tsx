import {useEffect, useRef, useState} from 'react';
import type {AttachmentRef, LibraryItem} from '../types';
import {formatBytes, imageURL} from '../lib/images';
import {errorMessage} from '../lib/api';
import {formatDuration} from '../lib/video';
import {Icon} from './Icon';

/** A video of the library, played large, with how it was made and its downloads (MP4, GIF, WebP). */
export function VideoViewer({video, loadInfo, exportVideo, onClose}: {
  video: AttachmentRef | null; loadInfo: (id: string) => Promise<LibraryItem>;
  exportVideo: (attachment: string, format: 'gif' | 'webp') => Promise<Blob>; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [info, setInfo] = useState<LibraryItem | null>(null);
  const [working, setWorking] = useState<'gif' | 'webp' | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const element = dialog.current; if (!element) return;
    if (video && !element.open) element.showModal();
    if (!video && element.open) element.close();
  }, [video]);
  useEffect(() => {
    setInfo(null); setError('');
    if (!video) return;
    let current = true;
    loadInfo(video.id).then(value => {if (current) setInfo(value);}, () => {});
    return () => {current = false;};
  }, [video?.id]);

  async function exportAs(format: 'gif' | 'webp') {
    if (!video) return;
    setError(''); setWorking(format);
    try {
      const blob = await exportVideo(video.id, format);
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob); link.download = `${video.name.replace(/\.[^.]+$/, '') || 'video'}.${format}`;
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 60000);
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setWorking(null); }
  }

  const g = info?.generation;
  return <dialog ref={dialog} className="image-viewer video-viewer" aria-label={video?.name} onClose={onClose}
    onClick={event => {if (event.target === dialog.current) onClose();}}>
    {video && <div className="image-viewer-main">
      <video src={imageURL(video.id)} controls autoPlay loop playsInline/>
      {g?.video && <p className="video-viewer-text" title={g.sent}>{g.prompt || g.improved || g.sent}<small>
        {g.resolution} · {g.duration} s · {g.steps} étapes{g.smooth ? ' · 32 i/s' : ''} · graine {g.seed}{typeof g.seconds === 'number' ? ` · faite en ${formatDuration(g.seconds)}` : ''}{info ? ` · ${formatBytes(info.size)}` : ''}</small></p>}
      {error && <p className="studio-error" role="alert">{error}</p>}
      <div className="image-viewer-bar">
        <span>{video.name}</span>
        <a className="icon-button" href={`${imageURL(video.id)}?download=1`} download={video.name} aria-label="Télécharger la vidéo (MP4)" title="Télécharger (MP4)"><Icon name="download"/></a>
        <button type="button" className="studio-secondary" disabled={working !== null} onClick={() => {void exportAs('gif');}}>{working === 'gif' ? 'GIF…' : 'GIF'}</button>
        <button type="button" className="studio-secondary" disabled={working !== null} onClick={() => {void exportAs('webp');}}>{working === 'webp' ? 'WebP…' : 'WebP'}</button>
        <button type="button" className="icon-button" aria-label="Fermer" title="Fermer" onClick={onClose}><Icon name="close"/></button>
      </div>
    </div>}
  </dialog>;
}
