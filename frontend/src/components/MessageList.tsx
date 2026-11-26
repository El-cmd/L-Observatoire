import {lazy, memo, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import type {AttachmentRef, Conversation, Message} from '../types';
import {documentSize, isDocument, thumbnailURL} from '../lib/images';
import {CopyButton} from './CopyButton';
import {FeedbackButtons} from './FeedbackButtons';
import {ANSWER_REASONS, type Feedback} from '../lib/feedback';
const Markdown = lazy(() => import('./Markdown').then(module => ({default:module.Markdown})));
import {Icon} from './Icon';
import {ToolTrace, citationSources, provisionalReport} from './ToolTrace';
import {SourceList, splitSources} from './Sources';

function MessageDocument({file, removed, onOpen, onAsk}: {file: AttachmentRef; removed: boolean; onOpen: (file: AttachmentRef) => void; onAsk: (file: AttachmentRef) => void}) {
  if (removed) return <span className="message-image is-missing" title={file.name}>Document supprimé</span>;
  return <div className="message-document">
    <button type="button" className="message-document-open" aria-label={`Voir le texte lu dans ${file.name}`} title="Voir le texte lu" onClick={() => onOpen(file)}>
      <Icon name="document"/><span className="message-document-name">{file.name}</span><span className="message-document-size">{documentSize(file)}</span>
    </button>
    <button type="button" className="message-image-ask" aria-label={`Poser une question sur ${file.name}`} title="Poser une question sur ce document" onClick={() => onAsk(file)}><Icon name="ask"/></button>
  </div>;
}

function MessageImage({image, removed, onOpen, onAsk}: {image: AttachmentRef; removed: boolean; onOpen: (image: AttachmentRef) => void; onAsk: (image: AttachmentRef) => void}) {
  const [missing, setMissing] = useState(false);
  if (isDocument(image)) return <MessageDocument file={image} removed={removed} onOpen={onOpen} onAsk={onAsk}/>;
  if (missing || removed) return <span className="message-image is-missing" title={image.name}>Image supprimée</span>;
  // At most 360 px wide and 240 px high, in the image's own proportions.
  const width = Math.max(48, Math.round(Math.min(360, 240 * image.width / image.height)));
  return <div className="message-image" style={{width:`min(${width}px, 100%)`, aspectRatio:`${image.width} / ${image.height}`}}>
    <button type="button" className="message-image-open" aria-label={`Agrandir ${image.name}`} title={image.name} onClick={() => onOpen(image)}>
      <img src={thumbnailURL(image.id)} alt={image.name} loading="lazy" onError={() => setMissing(true)}/>
    </button>
    <button type="button" className="message-image-ask" aria-label={`Poser une question sur ${image.name}`} title="Poser une question sur cette image" onClick={() => onAsk(image)}><Icon name="ask"/></button>
  </div>;
}

const MessageItem = memo(function MessageItem({message, index, vote, onVote, streaming, last, removedImages, onRegenerate, onContinue, onOpenImage, onAskImage, onError}: {
  message: Message; index: number; vote: Feedback | null; onVote?: (index: number, vote: Feedback | null) => Promise<void>;
  streaming: boolean; last: boolean; removedImages: ReadonlySet<string>; onRegenerate: () => void; onContinue: () => void;
  onOpenImage: (image: AttachmentRef) => void; onAskImage: (image: AttachmentRef) => void; onError: (message: string) => void;
}) {
  const user = message.role === 'user';
  const sources = useMemo(() => citationSources(message.outils), [message.outils]);
  // Very deep search: its parts appear as soon as they are written, under the summary being written.
  const shown = useMemo(() => provisionalReport(message.content, message.outils, streaming), [message.content, message.outils, streaming]);
  // The list of sources written at the end of a web search answer is shown as cards with the icon of each site.
  const cards = useMemo(() => {
    const split = sources.size ? splitSources(shown) : null;
    return split && split.cited.every(number => sources.has(number)) ? split : null;
  }, [shown, sources]);
  return <article className={`message ${message.role}${streaming ? ' streaming' : ''}`}>
    {!user && <div className="assistant-heading">L’Observatoire</div>}
    {!user && message.outils?.length ? <ToolTrace events={message.outils} streaming={streaming}/> : null}
    {user && message.attachments?.length ? <div className="message-images">{message.attachments.map(image => <MessageImage key={image.id} image={image} removed={removedImages.has(image.id)} onOpen={onOpenImage} onAsk={onAskImage}/>)}</div> : null}
    {(!user || message.content) && <div className="message-content">{user ? message.content : shown ? <Suspense fallback={<span className="typing">Affichage de la réponse…</span>}><Markdown content={cards ? cards.body : shown} onError={onError} sources={sources}/>{cards && <SourceList numbers={cards.cited} sources={sources}/>}</Suspense> : <span className="typing">{streaming ? message.outils?.length ? message.outils.some(e => e.outil === 'recherche_web') ? 'Recherche sur Internet…' : 'Lecture de la page…' : 'L’Observatoire prépare sa réponse…' : 'Aucune réponse finale reçue.'}</span>}</div>}
    {!streaming && <div className="message-footer">
      <CopyButton text={message.content} label={user ? 'Copier la question' : 'Copier la réponse'} onError={onError}/>
      {!user && onVote && message.content.trim() && <FeedbackButtons value={vote} reasons={ANSWER_REASONS} what="réponse" className="message-feedback"
        onChange={value => onVote(index, value)}/>}
      {!user && last && message.truncated && <button className="message-action continue-response" type="button" title="La réponse a atteint la longueur maximale" onClick={onContinue}>Continuer la réponse</button>}
      {!user && last && <button className="message-action retry-response" type="button" aria-label="Relancer la réponse" title="Relancer la réponse" onClick={onRegenerate}><Icon name="retry"/></button>}
    </div>}
  </article>;
});

export function MessageList({chat, busy, summaryFocus, removedImages, onRegenerate, onContinue, onOpenImage, onAskImage, onError, ephemeral = false, loadVotes, sendVote}: {
  chat?: Conversation; busy: boolean; ephemeral?: boolean; summaryFocus: number; removedImages: ReadonlySet<string>; onRegenerate: () => void; onContinue: () => void;
  /** Thumbs up or down on the answers (not in an ephemeral chat: nothing of it is kept). */
  loadVotes?: (id: string) => Promise<(Feedback & {index: number})[]>; sendVote?: (id: string, index: number, vote: Feedback | null) => Promise<void>;
  onOpenImage: (image: AttachmentRef) => void; onAskImage: (image: AttachmentRef) => void; onError: (message: string) => void;
}) {
  const scroll = useRef<HTMLElement>(null);
  const atBottom = useRef(true);
  const previousId = useRef<string | undefined>(undefined);
  const messages = chat?.messages || [];
  const chatId = chat?.id;
  const latest = useRef(messages); latest.current = messages;
  // The functions of the page change at each render: kept in a ref, so that the answers are not drawn again.
  const api = useRef({loadVotes, sendVote}); api.current = {loadVotes, sendVote};
  // Each vote with the answer it was given to: an answer replaced by "Relancer" has no vote any more.
  const [votes, setVotes] = useState<{chat?: string; map: Record<number, {vote: Feedback; content: string}>}>({map: {}});
  useEffect(() => {
    const load = api.current.loadVotes;
    if (!chatId || ephemeral || !load) return;
    let current = true;
    load(chatId).then(list => {
      if (!current) return;
      const map: Record<number, {vote: Feedback; content: string}> = {};
      for (const {index, ...vote} of list) map[index] = {vote, content: latest.current[index]?.content ?? ''};
      setVotes({chat: chatId, map});
    }, () => {});
    return () => {current = false;};
  }, [chatId, ephemeral]);
  const onVote = useCallback(async (index: number, vote: Feedback | null) => {
    const send = api.current.sendVote;
    if (!chatId || !send) return;
    const content = latest.current[index]?.content ?? '';
    await send(chatId, index, vote);
    setVotes(current => {
      const map = {...(current.chat === chatId ? current.map : {})};
      if (vote) map[index] = {vote, content}; else delete map[index];
      return {chat: chatId, map};
    });
  }, [chatId]);
  const voteOf = (index: number, message: Message) => {
    const found = votes.chat === chatId ? votes.map[index] : undefined;
    return found && found.content === message.content ? found.vote : null;
  };
  const canVote = !ephemeral && sendVote ? onVote : undefined;
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
    <section className="welcome" id="welcome" hidden={messages.length > 0}>{ephemeral ? <>
      <h1>Chat éphémère</h1>
      <p className="welcome-note">Ce chat n’apparaît pas dans votre historique et n’est enregistré nulle part : il disparaît dès que vous le quittez ou fermez la page.</p>
    </> : <h1>Qu’avez-vous en tête aujourd’hui ?</h1>}</section>
    {ephemeral && messages.length > 0 && <p className="ephemeral-banner" role="note"><Icon name="ephemeral"/>Chat éphémère : rien n’est enregistré</p>}
    <div id="messages" className="messages" role="log" aria-label="Conversation" aria-live="polite" aria-relevant="additions">
      {through > 0 && chat?.context_summary && <div className="context-memory">
        <details className="context-summary" ref={summary} key={chat.id}>
          <summary>Résumé du début · {through} messages</summary>
          <div className="message-content"><Suspense fallback={<span className="typing">Chargement du résumé…</span>}><Markdown content={chat.context_summary} onError={onError}/></Suspense></div>
        </details>
        <details className="archived-messages"><summary>Voir les {through} messages d’origine</summary>
          {messages.slice(0, through).map((message, index) => <MessageItem key={`${chat.id}:${index}`} message={message} index={index} vote={voteOf(index, message)} onVote={canVote} streaming={false} last={false} removedImages={removedImages} onRegenerate={onRegenerate} onContinue={onContinue} onOpenImage={onOpenImage} onAskImage={onAskImage} onError={onError}/>)}
        </details>
      </div>}
      {messages.slice(through).map((message, offset) => {const index = through + offset; return <MessageItem key={`${chat?.id}:${index}`} message={message} index={index} vote={voteOf(index, message)} onVote={canVote}
        last={index === messages.length - 1} streaming={busy && message.role === 'assistant' && index === messages.length - 1}
        removedImages={removedImages} onRegenerate={onRegenerate} onContinue={onContinue} onOpenImage={onOpenImage} onAskImage={onAskImage} onError={onError}/>;})}
    </div>
  </main>;
}
