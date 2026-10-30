import {useEffect, useState} from 'react';
import {useObservatoire} from './hooks/useObservatoire';
import {Login} from './components/Login';
import {Sidebar} from './components/Sidebar';
import {MessageList} from './components/MessageList';
import {Composer} from './components/Composer';
import {PasswordDialog} from './components/PasswordDialog';
import {Icon} from './components/Icon';

export default function App() {
  const chat = useObservatoire();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  useEffect(() => {setSidebarOpen(false); setPasswordOpen(false);}, [chat.auth?.user.id]);
  useEffect(() => {
    function key(event: KeyboardEvent) {
      if (event.key === 'Escape') setSidebarOpen(false);
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'n') {event.preventDefault(); void chat.newChat();}
    }
    document.addEventListener('keydown', key); return () => document.removeEventListener('keydown', key);
  }, [chat.newChat]);
  if (!chat.auth) return <Login initializing={chat.initializing} pending={chat.signingIn} error={chat.loginError} onLogin={chat.login}/>;
  const empty = !chat.current?.messages.length;
  return <>
    <div className="app" id="chat-app">
      <Sidebar user={chat.auth.user} chats={chat.chats} currentId={chat.current?.id} open={sidebarOpen} collapsed={sidebarCollapsed}
        navigating={chat.navigating || chat.compacting} canImport={chat.canImport} importing={chat.importing} onClose={() => {if (innerWidth <= 760) setSidebarOpen(false); else setSidebarCollapsed(true);}}
        onNew={() => {void chat.newChat().then(() => setSidebarOpen(false));}}
        onSelect={id => {void chat.openChat(id).then(() => setSidebarOpen(false));}}
        onDelete={id => {void chat.deleteChat(id);}} onImport={() => {void chat.importLegacy();}}
        onPassword={() => setPasswordOpen(true)} onLogout={() => {void chat.logout();}}/>
      <button id="sidebar-backdrop" className="sidebar-backdrop" aria-label="Fermer les conversations" tabIndex={-1} onClick={() => setSidebarOpen(false)}/>
      <div className={`workspace${empty ? ' empty' : ''}`} id="workspace">
        <header className="topbar"><button id="menu" className="icon-button" aria-label="Ouvrir les conversations" title="Conversations" onClick={() => {if (innerWidth <= 760) setSidebarOpen(value => !value); else setSidebarCollapsed(value => !value);}}><Icon name="sidebar"/></button>
          <span className="topbar-title">L’Observatoire</span><span id="connection" className="sr-only" role="status">{chat.navigating ? 'Chargement…' : chat.auth.configured ? 'API configurée' : 'Configuration requise'}</span>
        </header>
        <MessageList chat={chat.current} busy={chat.busy} summaryFocus={chat.summaryFocus} onRegenerate={() => {void chat.regenerate();}} onError={chat.notify}/>
        <Composer prompt={chat.prompt} onPrompt={chat.setPrompt} onSend={value => {void chat.send(value);}} onStop={chat.stop}
          onRegenerate={() => {void chat.regenerate();}} settings={chat.settings} onSettings={chat.setSettings} busy={chat.busy}
          contextUsage={chat.contextUsage} compacting={chat.compacting} onCompact={() => {void chat.compactContext();}}
          disabled={!chat.auth.configured || chat.navigating || chat.compacting || !chat.current} notice={chat.notice} chatId={chat.current?.id}/>
      </div>
    </div>
    <PasswordDialog open={passwordOpen} onClose={() => setPasswordOpen(false)} onChange={chat.changePassword}/>
  </>;
}
