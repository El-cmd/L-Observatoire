import {useCallback, useEffect, useRef, useState} from 'react';
import {APIClient, APIError, errorMessage} from '../lib/api';
import {consumeCompletion} from '../lib/stream';
import type {Auth, Conversation, ConversationSummary, Legacy, Message, Notice, Settings} from '../types';

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
    maxTokens: 4096,
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
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [navigating, setNavigating] = useState(false);
  const navigation = useRef<{id: number; controller?: AbortController}>({id: 0});
  const creating = useRef(false);
  const loadingList = useRef(false);
  const generation = useRef<AbortController | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [prompt, setPrompt] = useState('');
  const [settings, setSettings] = useState<Settings>({effort:'none', temperature:0.7, maxTokens:4096});
  const [canImport, setCanImport] = useState(false);
  const [importing, setImporting] = useState(false);

  const notify = useCallback((message: string) => setNotice({message}), []);
  const replaceChats = useCallback((value: Conversation[]) => { chatsRef.current = value; setChats(value); }, []);
  const replaceChat = useCallback((chat: Conversation) => {
    const exists = chatsRef.current.some(c => c.id === chat.id);
    const next = exists ? chatsRef.current.map(c => c.id === chat.id ? chat : c) : [chat, ...chatsRef.current];
    chatsRef.current = next; setChats(next);
  }, []);

  const clearSession = useCallback((message = '') => {
    epoch.current++; generation.current?.abort(); navigation.current.controller?.abort();
    generation.current = null; authRef.current = null; client.setCSRF('');
    setAuth(null); replaceChats([]); setCurrentId(undefined); setPrompt('');
    busyRef.current = false; creating.current = false; loadingList.current = false; setBusy(false); setNavigating(false);
    setNotice(null); setCanImport(false); setLoginError(message); setInitializing(false);
  }, [client, replaceChats]);

  const failure = useCallback((error: unknown) => {
    if (error instanceof APIError && error.status === 401) clearSession('Ta session a expiré. Reconnecte-toi.');
    else if (!aborted(error)) setNotice({message:errorMessage(error)});
  }, [clearSession]);

  async function openChat(id: string) {
    if (busyRef.current || !authRef.current) return;
    const account = epoch.current;
    navigation.current.controller?.abort();
    const requestId = ++navigation.current.id;
    const controller = new AbortController(); navigation.current.controller = controller;
    setNavigating(true);
    try {
      const chat = normalize(await client.json<Conversation>(`/api/conversations/${id}`, {signal:controller.signal}));
      if (epoch.current !== account || requestId !== navigation.current.id) return;
      replaceChat(chat); setCurrentId(id); setNotice(null);
    } catch (error) { if (epoch.current === account) failure(error); }
    finally { if (epoch.current === account && requestId === navigation.current.id) setNavigating(false); }
  }

  async function newChat(fromList = false) {
    if (busyRef.current || creating.current || loadingList.current && !fromList || !authRef.current) return;
    const empty = chatsRef.current.find(chat => !chat.message_count && !chat.messages.length);
    if (empty) { await openChat(empty.id); return; }
    const account = epoch.current; creating.current = true; setNavigating(true);
    try {
      const chat = normalize(await client.json<Conversation>('/api/conversations', {method:'POST'}));
      if (epoch.current !== account) return;
      replaceChat(chat); setCurrentId(chat.id); setNotice(null);
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
    generation.current?.abort(); navigation.current.controller?.abort();
    const account = ++epoch.current;
    authRef.current = value; client.setCSRF(value.csrf_token);
    busyRef.current = false; setBusy(false); replaceChats([]); setCurrentId(undefined);
    setSettings(readSettings(value.user.id, legacy)); setNavigating(true); setAuth(value); setLoginError(''); setNotice(null); setInitializing(false);
    let alreadyImported = false;
    try {alreadyImported = Boolean(localStorage.getItem(`observatoire-imported:${value.user.id}`));} catch {}
    setCanImport(!alreadyImported && Array.isArray(legacy?.chats) && legacy.chats.some(chat => chat.messages?.length));
    await loadConversations(account);
    if (epoch.current === account && !value.configured) notify('L’API Qwen n’est pas configurée. Vérifie QWEN_BASE_URL et QWEN_API_KEY.');
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

  useEffect(() => () => {generation.current?.abort(); navigation.current.controller?.abort();}, []);

  async function login(username: string, password: string) {
    if (signingIn) return;
    setSigningIn(true); setLoginError('');
    try {await startSession(await client.json<Auth>('/api/auth/login', {method:'POST', body:{username, password}}));}
    catch (error) {if (authRef.current) failure(error); else setLoginError(errorMessage(error));}
    finally {setSigningIn(false);}
  }

  async function logout() {
    generation.current?.abort(); navigation.current.controller?.abort();
    try {await client.json('/api/auth/logout', {method:'POST'}); clearSession();}
    catch (error) {failure(error);}
  }

  async function changePassword(current_password: string, new_password: string) {
    await client.json('/api/auth/password', {method:'PUT', body:{current_password, new_password}});
    clearSession('Mot de passe modifié. Reconnecte-toi.');
  }

  async function deleteChat(id: string) {
    if (busyRef.current || !authRef.current || !confirm('Supprimer cette conversation de ton compte ?')) return;
    const account = epoch.current;
    try {
      await client.json(`/api/conversations/${id}`, {method:'DELETE'});
      if (epoch.current !== account) return;
      const next = chatsRef.current.filter(chat => chat.id !== id); replaceChats(next);
      if (id === currentId) {if (next.length) await openChat(next[0].id); else await newChat();}
    } catch (error) {if (epoch.current === account) failure(error);}
  }

  async function requestAnswer(draft: Conversation, recoveryText?: string) {
    if (busyRef.current || !authRef.current?.configured) return;
    const account = epoch.current;
    const controller = new AbortController(); generation.current = controller;
    busyRef.current = true; setBusy(true); setNotice(null);
    replaceChat(draft);
    let baseVersion = draft.version, savedQuestion = false, complete = false;
    let assistant: Message | null = null;
    let savedChat = draft;
    try {
      savedChat = normalize(await client.json<Conversation>(`/api/conversations/${draft.id}`, {method:'PUT', body:{version:draft.version, messages:draft.messages}, signal:controller.signal}));
      baseVersion = savedChat.version; savedQuestion = true;
      if (epoch.current !== account) return;
      assistant = {role:'assistant', content:'', reasoning:''};
      replaceChat({...savedChat, messages:[...savedChat.messages, assistant]});
      const response = await client.response(`/api/conversations/${draft.id}/generate`, {method:'POST', signal:controller.signal,
        body:{version:baseVersion, reasoning_effort:settings.effort, temperature:settings.temperature, max_tokens:settings.maxTokens}});
      const result = await consumeCompletion(response, value => {
        if (epoch.current !== account) return;
        assistant = {role:'assistant', content:value.content, reasoning:value.reasoning};
        replaceChat({...savedChat, messages:[...savedChat.messages, assistant]});
      });
      complete = true;
      if (epoch.current !== account) return;
      if (!result.content.trim()) setNotice({message:'Le modèle n’a pas produit de réponse finale. Essaie un niveau de réflexion plus léger.', retry:true});
      else if (result.limited) setNotice({message:'La réponse a atteint sa limite de longueur. Demande au modèle de continuer.', retry:true});
    } catch (error) {
      controller.abort();
      if (epoch.current !== account) return;
      if (error instanceof APIError && error.status === 401) failure(error);
      else setNotice({message:aborted(error) ? 'Génération arrêtée.' : errorMessage(error), retry:true});
      if (!savedQuestion && recoveryText) setPrompt(recoveryText);
    } finally {
      if (epoch.current === account) {
        try {
          for (let attempt = 0; attempt < 8; attempt++) {
            const saved = normalize(await client.json<Conversation>(`/api/conversations/${draft.id}`));
            if (epoch.current !== account) break;
            if (saved.version > baseVersion || !savedQuestion || !assistant?.content && !assistant?.reasoning) {replaceChat(saved); break;}
            if (complete) break;
            await new Promise(resolve => setTimeout(resolve, 100));
          }
        } catch (error) {if (epoch.current === account) failure(error);}
        if (epoch.current === account) {busyRef.current = false; setBusy(false); generation.current = null;}
      }
    }
  }

  async function send(content: string) {
    const chat = chatsRef.current.find(value => value.id === currentId);
    if (!chat || busyRef.current || navigating || !content.trim()) return;
    if (chat.messages.length >= 98) {notify('Cette conversation est longue. Ouvre un nouveau chat pour continuer.'); return;}
    setPrompt('');
    await requestAnswer({...chat, title:chat.messages.length ? chat.title : content.slice(0,80),
      messages:[...chat.messages, {role:'user', content:content.trim()}], message_count:chat.messages.length+1}, content);
  }

  async function regenerate() {
    const chat = chatsRef.current.find(value => value.id === currentId);
    if (!chat || busyRef.current) return;
    const last = chat.messages.findLastIndex(message => message.role === 'user');
    if (last >= 0) await requestAnswer({...chat, messages:chat.messages.slice(0,last+1)});
  }

  async function importLegacy() {
    if (!authRef.current || importing || !Array.isArray(legacy?.chats) || !confirm('Importer les conversations de ce navigateur dans ton compte ? Ne le fais que si elles t’appartiennent.')) return;
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

  return {auth, initializing, loginError, signingIn, login, logout, changePassword,
    chats, current:chats.find(chat => chat.id === currentId), busy, navigating, notice, notify,
    prompt, setPrompt, settings, setSettings, newChat, openChat, deleteChat, send, regenerate,
    stop:() => generation.current?.abort(), canImport, importing, importLegacy};
}
