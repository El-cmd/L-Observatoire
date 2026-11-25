import {useEffect, useState} from 'react';
import {useObservatoire} from './hooks/useObservatoire';
import {Login} from './components/Login';
import {Sidebar} from './components/Sidebar';
import {MessageList} from './components/MessageList';
import {Composer} from './components/Composer';
import {PasswordDialog} from './components/PasswordDialog';
import {Icon} from './components/Icon';
import {ImageViewer} from './components/ImageViewer';
import {DocumentViewer} from './components/DocumentViewer';
import {LibraryView} from './components/LibraryView';
import {NewsView} from './components/NewsView';
import {ImageStudio} from './components/ImageStudio';
import {hasUnreadNews, markNewsRead, newsFor} from './lib/news';
import {MAX_IMAGES, formatBytes, isDocument} from './lib/images';
import type {AttachmentRef} from './types';

export default function App() {
  const chat = useObservatoire();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  // The library replaces the conversation in the workspace: to browse it, or to pick images.
  const [library, setLibrary] = useState<'closed' | 'browse' | 'pick'>('closed');
  const [viewer, setViewer] = useState<AttachmentRef | null>(null);
  const [news, setNews] = useState(false);
  // Images tab: creates images into the library; replaces the conversation like the library.
  const [studio, setStudio] = useState(false);
  const [unreadNews, setUnreadNews] = useState(false);
  const userId = chat.auth?.user.id;
  const searcher = chat.auth?.user.recherche_web === true;
  useEffect(() => {
    setSidebarOpen(false); setPasswordOpen(false); setLibrary('closed'); setViewer(null); setNews(false); setStudio(false);
    setUnreadNews(chat.auth ? hasUnreadNews(chat.auth.user) : false);
  }, [userId, searcher]);
  useEffect(() => {
    function key(event: KeyboardEvent) {
      if (event.key === 'Escape') setSidebarOpen(false);
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'n') {event.preventDefault(); setLibrary('closed'); setNews(false); setStudio(false); void chat.newChat();}
    }
    document.addEventListener('keydown', key); return () => document.removeEventListener('keydown', key);
  }, [chat.newChat]);
  if (!chat.auth) return <Login initializing={chat.initializing} pending={chat.signingIn} error={chat.loginError} onLogin={chat.login}/>;
  const empty = library === 'closed' && !news && !studio && !chat.current?.messages.length;
  // The chosen image waits above the input: the user only has to type the question.
  const askAbout = () => document.getElementById('prompt')?.focus();
  const page = studio ? 'Images' : library === 'pick' ? 'Choisir dans la bibliothèque' : library !== 'closed' ? 'Bibliothèque' : null;
  return <>
    <div className="app" id="chat-app">
      <Sidebar user={chat.auth.user} chats={chat.chats} activity={chat.activity} currentId={chat.current?.id} libraryOpen={library === 'browse'} imagesOpen={studio}
        onLibrary={() => {setNews(false); setStudio(false); setLibrary('browse'); setSidebarOpen(false);}}
        onImages={() => {setNews(false); setLibrary('closed'); setStudio(true); setSidebarOpen(false);}} newsOpen={news} unreadNews={unreadNews}
        onNews={() => {setLibrary('closed'); setStudio(false); setNews(true); setSidebarOpen(false); markNewsRead(chat.auth!.user); setUnreadNews(false);}} open={sidebarOpen} collapsed={sidebarCollapsed}
        navigating={chat.navigating} canImport={chat.canImport} importing={chat.importing} onClose={() => {if (innerWidth <= 760) setSidebarOpen(false); else setSidebarCollapsed(true);}}
        onNew={() => {setLibrary('closed'); setNews(false); setStudio(false); void chat.newChat().then(() => setSidebarOpen(false));}}
        onSelect={id => {setLibrary('closed'); setNews(false); setStudio(false); void chat.openChat(id).then(() => setSidebarOpen(false));}}
        onRename={(id, title) => {void chat.renameChat(id, title);}} onDelete={id => {void chat.deleteChat(id);}} onImport={() => {void chat.importLegacy();}}
        onPassword={() => setPasswordOpen(true)} onLogout={() => {void chat.logout();}}/>
      <button id="sidebar-backdrop" className="sidebar-backdrop" aria-label="Fermer les conversations" tabIndex={-1} onClick={() => setSidebarOpen(false)}/>
      <div className={`workspace${empty ? ' empty' : ''}`} id="workspace">
        <header className="topbar"><button id="menu" className="icon-button" aria-label="Ouvrir les conversations" title="Conversations" onClick={() => {if (innerWidth <= 760) setSidebarOpen(value => !value); else setSidebarCollapsed(value => !value);}}><Icon name="sidebar"/></button>
          {/* The open page names itself here, fixed above its content. */}
          <span className={`topbar-title${page ? ' page' : ''}`} id="page-title">{page ?? 'L’Observatoire'}</span>
          {library !== 'closed' && !studio && chat.library && <p className="library-usage topbar-usage">{formatBytes(chat.library.used_bytes)} sur {formatBytes(chat.library.quota_bytes)}
            <span className="library-meter" aria-hidden="true"><span style={{width: `${Math.min(100, chat.library.used_bytes / chat.library.quota_bytes * 100)}%`}}/></span></p>}
          {!studio && library === 'closed' && <button id="ephemeral-toggle" type="button" className={`icon-button ephemeral-toggle${chat.ephemeral ? ' active' : ''}`} aria-pressed={chat.ephemeral}
            aria-label={chat.ephemeral ? 'Quitter le chat éphémère' : 'Ouvrir un chat éphémère, qui n’est pas enregistré'}
            title={chat.ephemeral ? 'Quitter le chat éphémère' : 'Chat éphémère : rien n’est enregistré'}
            onClick={() => {setNews(false); void chat.toggleEphemeral();}}><Icon name="ephemeral"/></button>}<span id="connection" className="sr-only" role="status">{chat.navigating ? 'Chargement…' : chat.auth.configured ? 'API configurée' : 'Configuration requise'}</span>
        </header>
        {news ? <NewsView items={newsFor(chat.auth.user)} onClose={() => setNews(false)}/> : studio ? <ImageStudio userId={chat.auth.user.id} library={chat.library}
          loadConfig={chat.creationConfig} improvePrompt={chat.improvePrompt} createImage={chat.createImage} cutoutImage={chat.cutoutImage} uploadImage={chat.uploadImage} styles={chat.styles} onLoad={() => {void chat.loadLibrary();}}
          onOpen={setViewer} onDelete={id => {void chat.deleteImage(id);}} removed={chat.removedImages}
          onStartChat={image => {setStudio(false); void chat.newChat().then(() => {chat.addFromLibrary([image]); askAbout();});}}/> : library !== 'closed' ? <LibraryView library={chat.library} picking={library === 'pick'} room={MAX_IMAGES - chat.pending.length}
          onLoad={() => {void chat.loadLibrary();}} onClose={() => setLibrary('closed')} onOpen={setViewer} onDelete={id => {void chat.deleteImage(id);}}
          onPick={images => {chat.addFromLibrary(images); setLibrary('closed');}}
          onStartChat={image => {setLibrary('closed'); void chat.newChat().then(() => {chat.addFromLibrary([image]); askAbout();});}} onOpenChat={id => {setLibrary('closed'); void chat.openChat(id);}}
          findConversations={chat.imageConversations} onError={chat.notify}/> : <>
        <MessageList chat={chat.current} ephemeral={chat.ephemeral} busy={chat.busy} summaryFocus={chat.summaryFocus} removedImages={chat.removedImages} onRegenerate={() => {void chat.regenerate();}} onContinue={() => {void chat.continueAnswer();}} onOpenImage={setViewer} onAskImage={image => {chat.addFromLibrary([image]); askAbout();}} onError={chat.notify}/>
        <Composer prompt={chat.prompt} onPrompt={chat.setPrompt} pending={chat.pending} onAddImages={files => {void chat.addImages(files);}}
          onRemovePending={chat.removePending} onOpenLibrary={() => setLibrary('pick')} onSend={value => {void chat.send(value);}} onStop={chat.stop}
          onRegenerate={() => {void chat.regenerate();}} onContinue={() => {void chat.continueAnswer();}} settings={chat.settings} onSettings={chat.setSettings} busy={chat.busy}
          contextUsage={chat.contextUsage} compacting={chat.compacting} onCompact={() => {void chat.compactContext();}}
          disabled={!chat.auth.configured || chat.navigating || chat.compacting || !chat.current} notice={chat.notice} chatId={chat.current?.id}
          webAllowed={chat.auth.user.recherche_web === true} filesAllowed={!chat.ephemeral}/>
        </>}
      </div>
    </div>
    <PasswordDialog open={passwordOpen} onClose={() => setPasswordOpen(false)} onChange={chat.changePassword}/>
    <ImageViewer image={viewer && !isDocument(viewer) ? viewer : null} loadInfo={chat.attachmentInfo} onClose={() => setViewer(null)}/>
    <DocumentViewer file={viewer && isDocument(viewer) ? viewer : null} load={chat.documentText} onClose={() => setViewer(null)} onError={chat.notify}/>
  </>;
}
