import {useEffect, useState} from 'react';
import type {AttachmentRef, Library, LibraryItem} from '../types';
import {formatBytes, imageURL, readingSummary, thumbnailURL, toRef} from '../lib/images';
import {Icon} from './Icon';

type Links = {id: string; items: {id: string; title: string}[] | null};

/** The user's images and documents; in picking mode, a selection to attach to the next message. */
export function LibraryView({library, picking, room, onLoad, onClose, onOpen, onDelete, onPick, onStartChat, onOpenChat, findConversations, onError}: {
  library: Library | null; picking: boolean; room: number; onLoad: () => void; onClose: () => void;
  onOpen: (image: AttachmentRef) => void; onDelete: (id: string) => void; onPick: (images: AttachmentRef[]) => void; onStartChat: (image: AttachmentRef) => void;
  onOpenChat: (id: string) => void; findConversations: (id: string) => Promise<{id: string; title: string}[]>; onError: (message: string) => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [links, setLinks] = useState<Links | null>(null);
  // Loaded each time the view opens: files sent since are listed.
  useEffect(() => {onLoad();}, []);
  // Followed while documents are being read.
  const reading = library?.items.some(item => item.status === 'reading');
  useEffect(() => {
    if (!reading) return;
    const timer = setTimeout(onLoad, 2000); return () => clearTimeout(timer);
  }, [library, reading]);
  const ref = (item: LibraryItem): AttachmentRef => toRef(item);
  const state = (item: LibraryItem) => item.status === 'reading' ? `Lecture… ${item.progress} / ${item.pages} pages`
    : item.status === 'failed' ? item.error || 'Ce document n’a pas pu être lu.' : readingSummary(item);
  function toggle(id: string) {
    setSelected(list => list.includes(id) ? list.filter(value => value !== id) : list.length < room ? [...list, id] : list);
  }
  async function showLinks(id: string) {
    if (links?.id === id) {setLinks(null); return;}
    setLinks({id, items:null});
    try { const items = await findConversations(id); setLinks(value => value?.id === id ? {id, items} : value); }
    catch { setLinks(null); onError('Impossible de retrouver les conversations de cette image.'); }
  }
  const used = library ? Math.min(100, library.used_bytes / library.quota_bytes * 100) : 0;
  return <section className={`library${picking ? ' picking' : ''}`} id="library" aria-label="Bibliothèque">
    <header className="library-header">
      <h2>{picking ? 'Choisir dans la bibliothèque' : 'Bibliothèque'}</h2>
      {library && <p className="library-usage">{formatBytes(library.used_bytes)} sur {formatBytes(library.quota_bytes)}
        <span className="library-meter" aria-hidden="true"><span style={{width:`${used}%`}}/></span></p>}
      <button type="button" className="icon-button" aria-label="Fermer la bibliothèque" title="Fermer" onClick={onClose}><Icon name="close"/></button>
    </header>
    {!library ? <p className="library-empty" role="status">Chargement…</p>
      : !library.items.length ? <p className="library-empty">Les images et documents que tu envoies apparaîtront ici.</p>
      : <ul className="library-grid">{library.items.map(item => {
        const chosen = selected.includes(item.id);
        const document = item.kind === 'document', ready = item.status === 'ready';
        return <li key={item.id} className={`library-item${chosen ? ' selected' : ''}${document ? ` is-document is-${item.status}` : ''}`}>
          <button type="button" className="library-thumb" aria-label={picking ? `Choisir ${item.name}` : document ? `Voir le texte lu dans ${item.name}` : `Agrandir ${item.name}`}
            aria-pressed={picking ? chosen : undefined} disabled={!ready || picking && !chosen && selected.length >= room}
            onClick={() => picking ? toggle(item.id) : onOpen(ref(item))}>{document
              ? <span className="library-document"><Icon name="document"/><span>{item.name.split('.').pop()?.slice(0, 5).toUpperCase()}</span></span>
              : <img src={thumbnailURL(item.id)} alt="" loading="lazy"/>}</button>
          <div className="library-meta">
            <span className="library-name" title={item.name}>{item.name}</span>
            <span>{new Date(item.created_at).toLocaleDateString('fr-FR')} · {formatBytes(item.size)}</span>
            {document && <span className={`library-state${item.status === 'failed' ? ' error' : ''}`} role={item.status === 'reading' ? 'status' : undefined}>{state(item)}</span>}
          </div>
          {!picking && <div className="library-actions">
            <button type="button" className="icon-button" aria-label={`Nouvelle conversation avec ${item.name}`} title={document ? 'Nouvelle conversation avec ce document' : 'Nouvelle conversation avec cette image'} disabled={!ready} onClick={() => onStartChat(ref(item))}><Icon name="ask"/></button>
            <a className="icon-button" href={`${imageURL(item.id)}?download=1`} download={item.name} aria-label={`Télécharger ${item.name}`} title="Télécharger"><Icon name="download"/></a>
            <button type="button" className="icon-button" aria-label={`Conversations avec ${item.name}`} title="Conversations" aria-expanded={links?.id === item.id} onClick={() => {void showLinks(item.id);}}><Icon name="link"/></button>
            <button type="button" className="icon-button library-delete" aria-label={`Supprimer ${item.name}`} title="Supprimer" onClick={() => onDelete(item.id)}><Icon name="trash"/></button>
          </div>}
          {links?.id === item.id && <div className="library-links">
            {!links.items ? <span>Recherche…</span> : !links.items.length ? <span>Dans aucune conversation.</span>
              : links.items.map(chat => <button key={chat.id} type="button" onClick={() => onOpenChat(chat.id)}>{chat.title}</button>)}
          </div>}
        </li>;
      })}</ul>}
    {picking && <footer className="library-footer">
      <span>{room > 0 ? `${selected.length} sur ${room} possible${room > 1 ? 's' : ''}` : 'Ce message a déjà 5 fichiers.'}</span>
      <button type="button" className="library-cancel" onClick={onClose}>Annuler</button>
      <button type="button" className="auth-submit" disabled={!selected.length}
        onClick={() => onPick(library?.items.filter(item => selected.includes(item.id)).map(ref) || [])}>Ajouter{selected.length ? ` (${selected.length})` : ''}</button>
    </footer>}
  </section>;
}
