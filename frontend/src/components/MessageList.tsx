import {lazy, memo, Suspense, useLayoutEffect, useRef} from 'react';
import type {Conversation, Message} from '../types';
import {CopyButton} from './CopyButton';
const Markdown = lazy(() => import('./Markdown').then(module => ({default:module.Markdown})));
import {Icon} from './Icon';

const MessageItem = memo(function MessageItem({message, streaming, last, onRegenerate, onError}: {
  message: Message; streaming: boolean; last: boolean; onRegenerate: () => void; onError: (message: string) => void;
}) {
  const user = message.role === 'user';
  return <article className={`message ${message.role}${streaming ? ' streaming' : ''}`}>
    {!user && <div className="assistant-heading">L’Observatoire</div>}
    <div className="message-content">{user ? message.content : message.content ? <Suspense fallback={<span className="typing">Affichage de la réponse…</span>}><Markdown content={message.content} onError={onError}/></Suspense> : <span className="typing">{streaming ? 'L’Observatoire prépare sa réponse…' : 'Aucune réponse finale reçue.'}</span>}</div>
    {!streaming && <div className="message-footer">
      <CopyButton text={message.content} label={user ? 'Copier la question' : 'Copier la réponse'} onError={onError}/>
      {!user && last && <button className="message-action retry-response" type="button" aria-label="Relancer la réponse" title="Relancer la réponse" onClick={onRegenerate}><Icon name="retry"/></button>}
    </div>}
  </article>;
});

export function MessageList({chat, busy, onRegenerate, onError}: {
  chat?: Conversation; busy: boolean; onRegenerate: () => void; onError: (message: string) => void;
}) {
  const scroll = useRef<HTMLElement>(null);
  const atBottom = useRef(true);
  const previousId = useRef<string | undefined>(undefined);
  const messages = chat?.messages || [];
  useLayoutEffect(() => {
    const element = scroll.current; if (!element) return;
    if (previousId.current !== chat?.id || atBottom.current) element.scrollTop = element.scrollHeight;
    previousId.current = chat?.id;
  }, [chat?.id, messages, busy]);
  return <main className="main" id="main" ref={scroll} onScroll={() => {
    const element = scroll.current;
    if (element) atBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 130;
  }}>
    <section className="welcome" id="welcome" hidden={messages.length > 0}><h1>Qu’avez-vous en tête aujourd’hui ?</h1></section>
    <div id="messages" className="messages" role="log" aria-label="Conversation" aria-live="polite" aria-relevant="additions">
      {messages.map((message, index) => <MessageItem key={`${chat?.id}:${index}`} message={message}
        last={index === messages.length - 1} streaming={busy && message.role === 'assistant' && index === messages.length - 1}
        onRegenerate={onRegenerate} onError={onError}/>)}
    </div>
  </main>;
}
