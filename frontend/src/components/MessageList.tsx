import {lazy, memo, Suspense, useLayoutEffect, useRef, useState} from 'react';
import type {AttachmentRef, Conversation, Message} from '../types';
import {thumbnailURL} from '../lib/images';
import {CopyButton} from './CopyButton';
const Markdown = lazy(() => import('./Markdown').then(module => ({default:module.Markdown})));
import {Icon} from './Icon';

function MessageImage({image, removed, onOpen}: {image: AttachmentRef; removed: boolean; onOpen: (image: AttachmentRef) => void}) {
  const [missing, setMissing] = useState(false);
  if (missing || removed) return <span className="message-image is-missing" title={image.name}>Image supprimée</span>;
  return <button type="button" className="message-image" aria-label={`Agrandir ${image.name}`} title={image.name} onClick={() => onOpen(image)}>
    <img src={thumbnailURL(image.id)} alt={image.name} loading="lazy" width={image.width} height={image.height} onError={() => setMissing(true)}/>
  </button>;
}

const MessageItem = memo(function MessageItem({message, streaming, last, removedImages, onRegenerate, onContinue, onOpenImage, onError}: {
  message: Message; streaming: boolean; last: boolean; removedImages: ReadonlySet<string>; onRegenerate: () => void; onContinue: () => void;
  onOpenImage: (image: AttachmentRef) => void; onError: (message: string) => void;
}) {
  const user = message.role === 'user';
  return <article className={`message ${message.role}${streaming ? ' streaming' : ''}`}>
    {!user && <div className="assistant-heading">L’Observatoire</div>}
    {user && message.attachments?.length ? <div className="message-images">{message.attachments.map(image => <MessageImage key={image.id} image={image} removed={removedImages.has(image.id)} onOpen={onOpenImage}/>)}</div> : null}
    {(!user || message.content) && <div className="message-content">{user ? message.content : message.content ? <Suspense fallback={<span className="typing">Affichage de la réponse…</span>}><Markdown content={message.content} onError={onError}/></Suspense> : <span className="typing">{streaming ? 'L’Observatoire prépare sa réponse…' : 'Aucune réponse finale reçue.'}</span>}</div>}
    {!streaming && <div className="message-footer">
      <CopyButton text={message.content} label={user ? 'Copier la question' : 'Copier la réponse'} onError={onError}/>
      {!user && last && message.truncated && <button className="message-action continue-response" type="button" title="La réponse a atteint la longueur maximale" onClick={onContinue}>Continuer la réponse</button>}
      {!user && last && <button className="message-action retry-response" type="button" aria-label="Relancer la réponse" title="Relancer la réponse" onClick={onRegenerate}><Icon name="retry"/></button>}
    </div>}
  </article>;
});

export function MessageList({chat, busy, summaryFocus, removedImages, onRegenerate, onContinue, onOpenImage, onError}: {
  chat?: Conversation; busy: boolean; summaryFocus: number; removedImages: ReadonlySet<string>; onRegenerate: () => void; onContinue: () => void;
  onOpenImage: (image: AttachmentRef) => void; onError: (message: string) => void;
}) {
  const scroll = useRef<HTMLElement>(null);
  const atBottom = useRef(true);
  const previousId = useRef<string | undefined>(undefined);
  const messages = chat?.messages || [];
  const through = Math.min(chat?.compacted_through || 0, messages.length);
  const summary = useRef<HTMLDetailsElement>(null);
  const previousFocus = useRef(summaryFocus);
  useLayoutEffect(() => {
    const element = scroll.current; if (!element) return;
    if (previousFocus.current !== summaryFocus) {
      if (summary.current) summary.current.open = true;
      element.scrollTop = 0;
    } else if (previousId.current !== chat?.id || atBottom.current) element.scrollTop = element.scrollHeight;
    previousFocus.current = summaryFocus;
    previousId.current = chat?.id;
  }, [chat?.id, messages, busy, summaryFocus]);
  return <main className="main" id="main" ref={scroll} onScroll={() => {
    const element = scroll.current;
    if (element) atBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 130;
  }}>
    <section className="welcome" id="welcome" hidden={messages.length > 0}><h1>Qu’avez-vous en tête aujourd’hui ?</h1></section>
    <div id="messages" className="messages" role="log" aria-label="Conversation" aria-live="polite" aria-relevant="additions">
      {through > 0 && chat?.context_summary && <div className="context-memory">
        <details className="context-summary" ref={summary} key={chat.id}>
          <summary>Résumé du début · {through} messages</summary>
          <div className="message-content"><Suspense fallback={<span className="typing">Chargement du résumé…</span>}><Markdown content={chat.context_summary} onError={onError}/></Suspense></div>
        </details>
        <details className="archived-messages"><summary>Voir les {through} messages d’origine</summary>
          {messages.slice(0, through).map((message, index) => <MessageItem key={`${chat.id}:${index}`} message={message} streaming={false} last={false} removedImages={removedImages} onRegenerate={onRegenerate} onContinue={onContinue} onOpenImage={onOpenImage} onError={onError}/>)}
        </details>
      </div>}
      {messages.slice(through).map((message, offset) => {const index = through + offset; return <MessageItem key={`${chat?.id}:${index}`} message={message}
        last={index === messages.length - 1} streaming={busy && message.role === 'assistant' && index === messages.length - 1}
        removedImages={removedImages} onRegenerate={onRegenerate} onContinue={onContinue} onOpenImage={onOpenImage} onError={onError}/>;})}
    </div>
  </main>;
}
