import {useEffect, useRef, useState} from 'react';
import type {Activity, Conversation, User} from '../types';
import {Icon} from './Icon';

export function Sidebar({user, chats, activity, currentId, open, collapsed, navigating, canImport, importing, onClose, onNew,
  onSelect, onDelete, onImport, onPassword, onLogout}: {
  user: User; chats: Conversation[]; activity: Record<string, Activity>; currentId?: string; open: boolean; collapsed: boolean; navigating: boolean;
  canImport: boolean; importing: boolean; onClose: () => void; onNew: () => void;
  onSelect: (id: string) => void; onDelete: (id: string) => void; onImport: () => void;
  onPassword: () => void; onLogout: () => void;
}) {
  const [accountOpen, setAccountOpen] = useState(false);
  const account = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!accountOpen) return;
    function outside(event: MouseEvent) {if (!account.current?.contains(event.target as Node)) setAccountOpen(false);}
    function escape(event: KeyboardEvent) {if (event.key === 'Escape') setAccountOpen(false);}
    document.addEventListener('click', outside); document.addEventListener('keydown', escape);
    return () => {document.removeEventListener('click', outside); document.removeEventListener('keydown', escape);};
  }, [accountOpen]);
  const visible = chats.filter(chat => chat.message_count || chat.messages.length);
  return <aside className={`sidebar${open ? ' open' : ''}${collapsed ? ' collapsed' : ''}`} id="sidebar" aria-label="Conversations">
    <div className="sidebar-header"><a className="brand" href="/">L’Observatoire</a><button id="sidebar-close" type="button" className="icon-button" aria-label="Fermer la barre latérale" title="Fermer la barre latérale" onClick={onClose}><Icon name="sidebar"/></button></div>
    <button className="new-chat" id="new-chat" type="button" title="Ctrl / Cmd + Maj + N" disabled={navigating} onClick={onNew}><Icon name="new"/><span>Nouveau chat</span></button>
    <div className="history-label">Conversations</div>
    <div className="history" id="history" aria-label="Historique des conversations">
      {!visible.length && <p className="history-empty">Vos conversations apparaîtront ici.</p>}
      {visible.map(chat => <div className={`history-row${chat.id === currentId ? ' active' : ''}`} key={chat.id}>
        <button type="button" className="history-item" title={chat.title} onClick={() => onSelect(chat.id)}>{chat.title}</button>
        {activity[chat.id]
          ? <span className="history-activity" role="status" aria-label={activity[chat.id] === 'compacting' ? 'Résumé en cours' : 'Réponse en cours'} title={activity[chat.id] === 'compacting' ? 'Résumé en cours' : 'Réponse en cours'}/>
          : <button type="button" className="delete-conversation" aria-label={`Supprimer ${chat.title}`} title="Supprimer la conversation" onClick={() => onDelete(chat.id)}><Icon name="trash"/></button>}
      </div>)}
    </div>
    <div className="account-area" ref={account}>
      <div id="account-panel" className="account-panel" hidden={!accountOpen}>
        <button id="import-legacy" type="button" hidden={!canImport} disabled={importing} onClick={() => {setAccountOpen(false); onImport();}}>Importer les anciens chats de ce navigateur</button>
        <button id="change-password" type="button" onClick={() => {setAccountOpen(false); onPassword();}}>Changer mon mot de passe</button>
        <button id="logout" type="button" onClick={() => {setAccountOpen(false); onLogout();}}>Se déconnecter</button>
      </div>
      <button id="account-toggle" className="account-toggle" type="button" aria-label="Mon compte" aria-expanded={accountOpen} aria-controls="account-panel" onClick={() => setAccountOpen(value => !value)}>
        <Icon name="user"/><span id="account-name">{user.username}</span><span className="account-dots">···</span>
      </button>
    </div>
  </aside>;
}
