import {useCallback, useEffect, useRef, useState} from 'react';
import {APIClient, APIError, errorMessage} from '../lib/api';
import {consumeCompletion} from '../lib/stream';
import {MAX_IMAGES, documentSize, isDocument, isImage, prepareImage, thumbnailURL, toRef} from '../lib/images';
import type {Activity, AttachmentRef, Auth, Conversation, ConversationSummary, Legacy, Library, LibraryItem, Message, Notice, PendingImage, Settings, ContextUsage} from '../types';

function readLegacy(): Legacy | null {
  try { return JSON.parse(localStorage.getItem('observatoir-chat-v1') || localStorage.getItem('qwen-chat-v1') || 'null') as Legacy | null; }
  catch { return null; }
}
function readSettings(userId: string, legacy: Legacy | null): Settings {
  let saved: Partial<Settings> | null = null;
  try { saved = JSON.parse(localStorage.getItem(`observatoire-settings:${userId}`) || 'null') as Partial<Settings> | null; } catch {}
  saved ||= legacy?.settings || {};
  return {
    effort: ['none', 'low', 'medium', 'xhigh'].includes(saved.effort || '') ? saved.effort! : 'none',
    temperature: typeof saved.temperature === 'number' && Number.isFinite(saved.temperature) && saved.temperature >= 0 && saved.temperature <= 2 ? saved.temperature : 0.7,
  };
}
const normalize = (chat: Conversation): Conversation => ({...chat, message_count: chat.messages.length});
const aborted = (error: unknown) => error instanceof Error && error.name === 'AbortError';

export function useObservatoire() {
  const [client] = useState(() => new APIClient());
  const [legacy] = useState(readLegacy);
  const [auth, setAuth] = useState<Auth | null>(null);
  const authRef = useRef<Auth | null>(null);
  // Epochs invalidate every in-flight response when an account is changed, even
  // if the same user logs in again before an old generation finishes.
  const epoch = useRef(0);
  const [initializing, setInitializing] = useState(true);
  const [loginError, setLoginError] = useState('');
  const [signingIn, setSigningIn] = useState(false);
  const [chats, setChats] = useState<Conversation[]>([]);
  const chatsRef = useRef<Conversation[]>([]);
  const [currentId, setCurrentId] = useState<string>();
  const currentRef = useRef<string | undefined>(undefined);
  // Each conversation generates or summarizes on its own; several can stream at once.
  const [activity, setActivityState] = useState<Record<string, Activity>>({});
  const activityRef = useRef<Record<string, Activity>>({});
  const controllers = useRef(new Map<string, AbortController>());
  const [navigating, setNavigating] = useState(false);
  const navigation = useRef<{id: number; controller?: AbortController}>({id: 0});
  const creating = useRef(false);
  const loadingList = useRef(false);
  // Notices belong to a conversation; '' holds the ones about the account.
  const [notices, setNotices] = useState<Record<string, Notice>>({});
  const [prompt, setPrompt] = useState('');
  const [pending, setPendingState] = useState<PendingImage[]>([]);
  const pendingRef = useRef<PendingImage[]>([]);
  const [library, setLibrary] = useState<Library | null>(null);
  // The browser keeps images shown in the page in memory: deleted ones are hidden from here.
  const [removedImages, setRemovedImages] = useState<ReadonlySet<string>>(() => new Set());
  const [settings, setSettings] = useState<Settings>({effort:'none', temperature:0.7});
  const [canImport, setCanImport] = useState(false);
  const [importing, setImporting] = useState(false);
  const [contextUsage, setContextUsage] = useState<ContextUsage | null>(null);
  const [summaryFocus, setSummaryFocus] = useState(0);

  const setNotice = useCallback((id: string, value: Notice | null) => setNotices(previous => {
    const next = {...previous}; if (value) next[id] = value; else delete next[id]; return next;
  }), []);
  const notify = useCallback((message: string) => setNotice(currentRef.current ?? '', {message}), [setNotice]);
  const setActivity = useCallback((id: string, value?: Activity) => {
    const next = {...activityRef.current}; if (value) next[id] = value; else delete next[id];
    activityRef.current = next; setActivityState(next);
  }, []);
  const abortAll = useCallback(() => {
    controllers.current.forEach(controller => controller.abort()); controllers.current.clear();
    activityRef.current = {}; setActivityState({});
  }, []);
  const selectChat = useCallback((id?: string) => { currentRef.current = id; setCurrentId(id); }, []);
  const setPending = useCallback((update: (previous: PendingImage[]) => PendingImage[]) => {
    pendingRef.current = update(pendingRef.current); setPendingState(pendingRef.current);
  }, []);
  const replaceChats = useCallback((value: Conversation[]) => { chatsRef.current = value; setChats(value); }, []);
  const replaceChat = useCallback((chat: Conversation) => {
    const exists = chatsRef.current.some(c => c.id === chat.id);
    const next = exists ? chatsRef.current.map(c => c.id === chat.id ? chat : c) : [chat, ...chatsRef.current];
    chatsRef.current = next; setChats(next);
  }, []);

  const clearSession = useCallback((message = '') => {
    epoch.current++; abortAll(); navigation.current.controller?.abort();
    authRef.current = null; client.setCSRF('');
    setAuth(null); replaceChats([]); selectChat(undefined); setPrompt(''); setPending(() => []); setLibrary(null);
    creating.current = false; loadingList.current = false; setNavigating(false);
    setNotices({}); setCanImport(false); setContextUsage(null); setLoginError(message); setInitializing(false);
  }, [client, replaceChats, abortAll, selectChat, setPending]);

  const failure = useCallback((error: unknown, id = currentRef.current ?? '') => {
    if (error instanceof APIError && error.status === 401) clearSession('Ta session a expiré. Reconnecte-toi.');
    else if (!aborted(error)) setNotice(id, {message:errorMessage(error)});
  }, [clearSession, setNotice]);

  async function openChat(id: string) {
    if (!authRef.current) return;
    const account = epoch.current;
    navigation.current.controller?.abort();
    const requestId = ++navigation.current.id;
    setNotice('', null);
    // A conversation being written is live in memory: reloading it would drop the partial answer.
    if (activityRef.current[id]) {selectChat(id); setNavigating(false); return;}
    const controller = new AbortController(); navigation.current.controller = controller;
    setNavigating(true);
    try {
      const chat = normalize(await client.json<Conversation>(`/api/conversations/${id}`, {signal:controller.signal}));
      if (epoch.current !== account || requestId !== navigation.current.id) return;
      if (!activityRef.current[id]) replaceChat(chat);
      selectChat(id);
    } catch (error) { if (epoch.current === account) failure(error); }
    finally { if (epoch.current === account && requestId === navigation.current.id) setNavigating(false); }
  }

  async function newChat(fromList = false) {
    if (creating.current || loadingList.current && !fromList || !authRef.current) return;
    const empty = chatsRef.current.find(chat => !chat.message_count && !chat.messages.length && !activityRef.current[chat.id]);
    if (empty) { await openChat(empty.id); return; }
    const account = epoch.current; creating.current = true; setNavigating(true);
    try {
      const chat = normalize(await client.json<Conversation>('/api/conversations', {method:'POST'}));
      if (epoch.current !== account) return;
      replaceChat(chat); selectChat(chat.id); setNotice('', null);
    } catch (error) { if (epoch.current === account) failure(error); }
    finally { if (epoch.current === account) {creating.current = false; setNavigating(false);} }
  }

  async function loadConversations(account: number) {
    loadingList.current = true; setNavigating(true);
    try {
      const summaries = await client.json<ConversationSummary[]>('/api/conversations');
      if (epoch.current !== account) return;
      replaceChats(summaries.map(chat => ({...chat, messages:[]})));
      if (summaries.length) await openChat(summaries[0].id); else await newChat(true);
    } finally {
      if (epoch.current === account) {loadingList.current = false; setNavigating(false);}
    }
  }

  async function startSession(value: Auth) {
    abortAll(); navigation.current.controller?.abort();
    const account = ++epoch.current;
    authRef.current = value; client.setCSRF(value.csrf_token);
    replaceChats([]); selectChat(undefined);
    setSettings(readSettings(value.user.id, legacy)); setNavigating(true); setAuth(value); setLoginError(''); setNotices({}); setInitializing(false);
    let alreadyImported = false;
    try {alreadyImported = Boolean(localStorage.getItem(`observatoire-imported:${value.user.id}`));} catch {}
    setCanImport(!alreadyImported && Array.isArray(legacy?.chats) && legacy.chats.some(chat => chat.messages?.length));
    await loadConversations(account);
    if (epoch.current === account && !value.configured) setNotice('', {message:'L’API Qwen n’est pas configurée. Vérifie QWEN_BASE_URL et QWEN_API_KEY.'});
  }

  useEffect(() => {
    const controller = new AbortController(); let active = true;
    client.json<Auth>('/api/auth/me', {signal:controller.signal}).then(value => {
      if (active) return startSession(value);
    }).catch(error => {
      if (!active || aborted(error)) return;
      if (error instanceof APIError && error.status === 401) clearSession();
      else if (authRef.current) failure(error); else clearSession(errorMessage(error));
    });
    return () => {active = false; controller.abort();};
    // The client is stable for the lifetime of this mounted application.
  }, [client]);

  useEffect(() => {
    if (!auth) return;
    try {localStorage.setItem(`observatoire-settings:${auth.user.id}`, JSON.stringify(settings));}
    catch {notify('Le navigateur ne permet pas de mémoriser les réglages. Les conversations restent sauvegardées sur le serveur.');}
  }, [auth?.user.id, settings, notify]);

  const activeChat = chats.find(chat => chat.id === currentId);
  useEffect(() => {
    if (!auth || !activeChat) {setContextUsage(null); return;}
    const controller = new AbortController(); const account = epoch.current;
    client.json<ContextUsage>(`/api/conversations/${activeChat.id}/context`, {signal:controller.signal}).then(value => {
      if (epoch.current === account && !controller.signal.aborted) setContextUsage(value);
    }).catch(error => {
      if (epoch.current === account && error instanceof APIError && error.status === 401) failure(error);
    });
    return () => controller.abort();
  }, [auth?.user.id, activeChat?.id, activeChat?.version, client]);

  async function compactContext() {
    const chat = chatsRef.current.find(value => value.id === currentRef.current);
    if (!chat || activityRef.current[chat.id] || !authRef.current?.configured) return;
    const id = chat.id, account = epoch.current, controller = new AbortController();
    controllers.current.set(id, controller); setActivity(id, 'compacting'); setNotice(id, null);
    try {
      const saved = normalize(await client.json<Conversation>(`/api/conversations/${id}/compact`, {method:'POST', body:{version:chat.version}, signal:controller.signal}));
      if (epoch.current !== account) return;
      replaceChat(saved);
      if (currentRef.current === id) setSummaryFocus(value => value + 1);
      setNotice(id, {message:'Le début de la conversation a été résumé. Les messages d’origine sont conservés.'});
    } catch (error) {if (epoch.current === account) failure(error, id);}
    finally {if (epoch.current === account) {controllers.current.delete(id); setActivity(id);}}
  }

  useEffect(() => () => {abortAll(); navigation.current.controller?.abort();}, [abortAll]);

  async function login(username: string, password: string) {
    if (signingIn) return;
    setSigningIn(true); setLoginError('');
    try {await startSession(await client.json<Auth>('/api/auth/login', {method:'POST', body:{username, password}}));}
    catch (error) {if (authRef.current) failure(error); else setLoginError(errorMessage(error));}
    finally {setSigningIn(false);}
  }

  async function logout() {
    abortAll(); navigation.current.controller?.abort();
    try {await client.json('/api/auth/logout', {method:'POST'}); clearSession();}
    catch (error) {failure(error);}
  }

  async function changePassword(current_password: string, new_password: string) {
    await client.json('/api/auth/password', {method:'PUT', body:{current_password, new_password}});
    clearSession('Mot de passe modifié. Reconnecte-toi.');
  }

  async function deleteChat(id: string) {
    if (!authRef.current) return;
    if (activityRef.current[id]) {notify('Attends la fin de la réponse avant de supprimer cette conversation.'); return;}
    if (!confirm('Supprimer cette conversation de ton compte ?')) return;
    const account = epoch.current;
    try {
      await client.json(`/api/conversations/${id}`, {method:'DELETE'});
      if (epoch.current !== account) return;
      const next = chatsRef.current.filter(chat => chat.id !== id); replaceChats(next); setNotice(id, null);
      if (id === currentRef.current) {if (next.length) await openChat(next[0].id); else await newChat();}
    } catch (error) {if (epoch.current === account) failure(error);}
  }

  /** With resume, the last assistant message (cut by the length limit) is extended in place. */
  async function requestAnswer(draft: Conversation, recoveryText?: string, recoveryImages: PendingImage[] = [], resume = false) {
    const id = draft.id;
    if (activityRef.current[id] || !authRef.current?.configured) return;
    const account = epoch.current;
    const controller = new AbortController(); controllers.current.set(id, controller);
    setActivity(id, 'generating'); setNotice(id, null);
    replaceChat(draft);
    let baseVersion = draft.version, savedQuestion = false, complete = false;
    let assistant: Message | null = null;
    let savedChat = draft;
    try {
      if (!resume) savedChat = normalize(await client.json<Conversation>(`/api/conversations/${id}`, {method:'PUT', body:{version:draft.version, messages:draft.messages}, signal:controller.signal}));
      baseVersion = savedChat.version; savedQuestion = true;
      if (epoch.current !== account) return;
      const history = resume ? savedChat.messages.slice(0, -1) : savedChat.messages;
      const start: Message = resume ? {...savedChat.messages[savedChat.messages.length - 1], truncated:false} : {role:'assistant', content:'', reasoning:''};
      assistant = start;
      replaceChat({...savedChat, messages:[...history, assistant]});
      const response = await client.response(`/api/conversations/${id}/generate`, {method:'POST', signal:controller.signal,
        body:{version:baseVersion, reasoning_effort:settings.effort, temperature:settings.temperature, ...(resume ? {continue:true} : {})}});
      // The title Qwen chose is applied once; a rename made meanwhile in the sidebar is kept.
      let named: string | undefined;
      const result = await consumeCompletion(response, value => {
        if (epoch.current !== account) return;
        let title = chatsRef.current.find(chat => chat.id === id)?.title ?? savedChat.title;
        if (value.title && value.title !== named) {named = value.title; title = value.title;}
        assistant = {...start, content:start.content + value.content, reasoning:(start.reasoning || '') + value.reasoning};
        replaceChat({...savedChat, title, messages:[...history, assistant]});
      });
      complete = true;
      if (epoch.current !== account) return;
      if (!result.content.trim() && !resume) setNotice(id, {message:'Le modèle n’a pas produit de réponse finale. Essaie un niveau de réflexion plus léger.', retry:true});
      else if (result.limited) setNotice(id, {message:'La réponse a atteint la longueur maximale.', resume:true});
    } catch (error) {
      controller.abort();
      if (epoch.current !== account) return;
      if (error instanceof APIError && error.status === 401) failure(error, id);
      else setNotice(id, {message:aborted(error) ? 'Génération arrêtée.' : errorMessage(error), retry:true});
      if (!savedQuestion && currentRef.current === id) {
        if (recoveryText) setPrompt(recoveryText);
        if (recoveryImages.length) setPending(() => recoveryImages);
      }
    } finally {
      if (epoch.current === account) {
        try {
          for (let attempt = 0; attempt < 8; attempt++) {
            const saved = normalize(await client.json<Conversation>(`/api/conversations/${id}`));
            if (epoch.current !== account) break;
            if (saved.version > baseVersion || !savedQuestion || !assistant?.content && !assistant?.reasoning) {replaceChat(saved); break;}
            if (complete) break;
            await new Promise(resolve => setTimeout(resolve, 100));
          }
        } catch (error) {if (epoch.current === account) failure(error, id);}
        if (epoch.current === account) {controllers.current.delete(id); setActivity(id);}
      }
    }
  }

  async function renameChat(id: string, title: string) {
    const name = title.trim(); const chat = chatsRef.current.find(value => value.id === id);
    if (!chat || !name || name === chat.title || !authRef.current) return;
    const account = epoch.current;
    try {
      const saved = await client.json<{title: string}>(`/api/conversations/${id}/title`, {method:'PUT', body:{title:name}});
      if (epoch.current !== account) return;
      const latest = chatsRef.current.find(value => value.id === id);
      if (latest) replaceChat({...latest, title:saved.title});
    } catch (error) {if (epoch.current === account) failure(error);}
  }

  /** A document is sent as it is; the server reads it (a PDF page by page with Qwen), and its
   *  progress is followed until it is ready to be attached. */
  async function addDocument(file: File, account: number) {
    const key = crypto.randomUUID();
    const update = (change: Partial<PendingImage>) => setPending(list => list.map(item => item.key === key ? {...item, ...change} : item));
    setPending(list => [...list, {key, name:file.name || 'document', document:true, status:'uploading'}]);
    try {
      let item = await client.json<LibraryItem>(`/api/attachments?name=${encodeURIComponent(file.name || 'document')}`, {method:'POST', body:file});
      setLibrary(null);
      while (item.status === 'reading') {
        if (epoch.current !== account || !pendingRef.current.some(value => value.key === key)) return;
        update({status:'reading', progress:`${item.progress} / ${item.pages} pages`});
        await new Promise(resolve => setTimeout(resolve, 1500));
        item = await client.json<LibraryItem>(`/api/attachments/${item.id}/status`);
      }
      if (epoch.current !== account) return;
      setLibrary(null);
      if (item.status === 'failed') update({status:'error', error:item.error || 'Ce document n’a pas pu être lu.'});
      else update({status:'ready', ref:toRef(item), progress:documentSize(toRef(item))});
    } catch (error) {
      if (epoch.current !== account) return;
      if (error instanceof APIError && error.status === 401) failure(error);
      update({status:'error', error:errorMessage(error)});
    }
  }

  /** Each image is prepared in the browser, then sent to the library as soon as it is chosen. */
  async function addImages(files: File[]) {
    if (!authRef.current) return;
    const room = MAX_IMAGES - pendingRef.current.length;
    if (files.length > room) notify(`${MAX_IMAGES} fichiers au maximum par message.`);
    const account = epoch.current;
    await Promise.all(files.slice(0, Math.max(0, room)).map(async file => {
      if (!isImage(file)) return addDocument(file, account);
      const key = crypto.randomUUID(); const preview = URL.createObjectURL(file);
      setPending(list => [...list, {key, name:file.name || 'image', preview, status:'uploading'}]);
      try {
        const blob = await prepareImage(file);
        const ref = await client.json<AttachmentRef>(`/api/attachments?name=${encodeURIComponent(file.name || 'image')}`, {method:'POST', body:blob});
        if (epoch.current !== account) return;
        setPending(list => list.map(item => item.key === key ? {...item, status:'ready', ref, preview:thumbnailURL(ref.id)} : item));
        setLibrary(null);
      } catch (error) {
        if (epoch.current !== account) return;
        if (error instanceof APIError && error.status === 401) failure(error);
        setPending(list => list.map(item => item.key === key ? {...item, status:'error', error:errorMessage(error)} : item));
      } finally { URL.revokeObjectURL(preview); }
    }));
  }

  function addFromLibrary(refs: AttachmentRef[]) {
    const room = MAX_IMAGES - pendingRef.current.length;
    if (refs.length > room) notify(`${MAX_IMAGES} fichiers au maximum par message.`);
    setPending(list => [...list, ...refs.slice(0, Math.max(0, room)).filter(ref => !list.some(item => item.ref?.id === ref.id))
      .map(ref => isDocument(ref) ? {key:crypto.randomUUID(), name:ref.name, document:true, status:'ready' as const, ref, progress:documentSize(ref)}
        : {key:crypto.randomUUID(), name:ref.name, preview:thumbnailURL(ref.id), status:'ready' as const, ref})]);
  }

  const removePending = (key: string) => setPending(list => list.filter(item => item.key !== key));

  async function send(content: string) {
    const chat = chatsRef.current.find(value => value.id === currentRef.current);
    const images = pendingRef.current;
    if (!chat || activityRef.current[chat.id] || navigating || !content.trim() && !images.length) return;
    if (images.some(item => item.status === 'uploading')) {notify('Attends la fin de l’envoi des fichiers.'); return;}
    if (images.some(item => item.status === 'reading')) {notify('Attends la fin de la lecture des documents.'); return;}
    if (images.some(item => item.status === 'error')) {notify('Retire les fichiers refusés avant d’envoyer.'); return;}
    if (chat.messages.length >= 9998) {notify('Cette conversation est longue. Ouvre un nouveau chat pour continuer.'); return;}
    const attachments = images.map(item => item.ref!);
    setPrompt(''); setPending(() => []);
    const question: Message = {role:'user', content:content.trim(), ...(attachments.length ? {attachments} : {})};
    await requestAnswer({...chat, title:chat.messages.length ? chat.title : (content.trim() || attachments[0].name).slice(0,80),
      messages:[...chat.messages, question], message_count:chat.messages.length+1}, content, images);
  }

  async function loadLibrary() {
    if (!authRef.current) return;
    const account = epoch.current;
    try {
      const value = await client.json<Library>('/api/attachments');
      if (epoch.current === account) setLibrary(value);
    } catch (error) {if (epoch.current === account) failure(error);}
  }

  async function deleteImage(id: string) {
    if (!authRef.current || !confirm('Supprimer ce fichier de ta bibliothèque ? Il sera remplacé par une mention « supprimé » dans les conversations.')) return;
    const account = epoch.current;
    try {
      await client.json(`/api/attachments/${id}`, {method:'DELETE'});
      if (epoch.current !== account) return;
      setPending(list => list.filter(item => item.ref?.id !== id));
      setRemovedImages(previous => new Set(previous).add(id));
      await loadLibrary();
    } catch (error) {if (epoch.current === account) failure(error);}
  }

  const imageConversations = (id: string) => client.json<{id: string; title: string}[]>(`/api/attachments/${id}/conversations`);
  const documentText = (id: string) => client.json<{content: string}>(`/api/attachments/${id}/text`).then(value => value.content);

  async function continueAnswer() {
    const chat = chatsRef.current.find(value => value.id === currentRef.current);
    if (!chat || activityRef.current[chat.id] || chat.messages[chat.messages.length - 1]?.role !== 'assistant') return;
    await requestAnswer(chat, undefined, [], true);
  }

  async function regenerate() {
    const chat = chatsRef.current.find(value => value.id === currentRef.current);
    if (!chat || activityRef.current[chat.id]) return;
    const last = chat.messages.findLastIndex(message => message.role === 'user');
    if (last >= 0) await requestAnswer({...chat, messages:chat.messages.slice(0,last+1)});
  }

  async function importLegacy() {
    if (!authRef.current || importing || !Array.isArray(legacy?.chats)) return;
    if (Object.keys(activityRef.current).length) {notify('Attends la fin des réponses en cours avant d’importer.'); return;}
    if (!confirm('Importer les conversations de ce navigateur dans ton compte ? Ne le fais que si elles t’appartiennent.')) return;
    const account = epoch.current; setImporting(true);
    try {
      const chats = legacy.chats.filter(chat => chat.messages?.length).map(chat => ({messages:chat.messages}));
      await client.json('/api/conversations/import', {method:'POST', body:{chats}});
      if (epoch.current !== account) return;
      try {localStorage.setItem(`observatoire-imported:${authRef.current!.user.id}`, 'true');} catch {}
      setCanImport(false); await loadConversations(account);
    } catch (error) {if (epoch.current === account) failure(error);}
    finally {if (epoch.current === account) setImporting(false);}
  }

  const currentActivity = currentId ? activity[currentId] : undefined;
  return {auth, initializing, loginError, signingIn, login, logout, changePassword,
    chats, current:activeChat, activity, busy:currentActivity === 'generating', navigating,
    notice:(currentId && notices[currentId]) || notices[''] || null, notify,
    prompt, setPrompt, pending, addImages, addFromLibrary, removePending, library, loadLibrary, deleteImage, imageConversations, documentText, removedImages,
    settings, setSettings, newChat, openChat, deleteChat, renameChat, send, regenerate, continueAnswer,
    contextUsage:contextUsage && contextUsage.conversation_id === currentId && contextUsage.version === activeChat?.version ? contextUsage : null,
    compacting:currentActivity === 'compacting', compactContext, summaryFocus,
    stop:() => {if (currentRef.current) controllers.current.get(currentRef.current)?.abort();}, canImport, importing, importLegacy};
}
