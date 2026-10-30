'use strict';
const $ = id => document.getElementById(id);
const STORAGE = 'observatoir-chat-v1';
const SETTINGS = {effort: 'none', temperature: 0.7, maxTokens: 4096};
const data = {chats: []};
let currentId, user = null, csrf = '', busy = false, controller = null, configured = false;
let legacy = null;
try { legacy = JSON.parse(localStorage.getItem(STORAGE) || localStorage.getItem('qwen-chat-v1')); } catch {}
class APIError extends Error { constructor(message, status) { super(message); this.status = status; } }
async function api(path, options = {}) {
  const method = options.method || 'GET';
  const headers = {...options.headers};
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (!['GET', 'HEAD'].includes(method) && csrf) headers['X-CSRF-Token'] = csrf;
  let response;
  try { response = await fetch(path, {...options, method, headers, credentials: 'same-origin', body: options.body === undefined ? undefined : JSON.stringify(options.body)}); }
  catch (error) { if (error.name === 'AbortError') throw error; throw new APIError('Impossible de joindre le serveur.', 0); }
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    if (response.status === 401 && !path.startsWith('/api/auth/')) showLogin('Ta session a expiré. Reconnecte-toi.');
    throw new APIError(detail.error || `Erreur HTTP ${response.status}`, response.status);
  }
  if (options.stream) return response;
  return response.status === 204 ? null : response.json();
}
function current() { return data.chats.find(chat => chat.id === currentId); }
function save() {
  if (!user) return;
  try { localStorage.setItem(`observatoire-settings:${user.id}`, JSON.stringify(SETTINGS)); }
  catch { showError('Le navigateur ne permet pas de mémoriser les réglages. Les conversations restent sauvegardées sur le serveur.'); }
}
function loadSettings() {
  let saved;
  try { saved = JSON.parse(localStorage.getItem(`observatoire-settings:${user.id}`)); } catch {}
  saved ||= legacy?.settings || {};
  SETTINGS.effort = ['none', 'low', 'medium', 'xhigh'].includes(saved.effort) ? saved.effort : 'none';
  SETTINGS.temperature = typeof saved.temperature === 'number' && saved.temperature >= 0 && saved.temperature <= 2 ? saved.temperature : 0.7;
  updateGenerationControls();
}
function showLogin(message = '') {
  controller?.abort(); user = null; csrf = ''; configured = false; busy = false; currentId = undefined;
  data.chats = [];
  $('messages').replaceChildren(); $('history').replaceChildren(); $('prompt').value = '';
  $('chat-app').hidden = true; $('auth-screen').hidden = false; $('login-form').hidden = false;
  $('auth-loading').hidden = true; $('login-error').textContent = message;
  $('account-panel').hidden = true; toggleGenerationSettings(false);
  if ($('password-dialog').open) $('password-dialog').close();
}
async function startAccount(auth) {
  user = auth.user; csrf = auth.csrf_token; configured = auth.configured;
  $('account-name').textContent = user.username;
  $('auth-screen').hidden = true; $('chat-app').hidden = false;
  $('login-password').value = ''; $('login-error').textContent = '';
  loadSettings();
  let imported = false;
  try { imported = Boolean(localStorage.getItem(`observatoire-imported:${user.id}`)); } catch {}
  $('import-legacy').hidden = imported || !legacy?.chats?.some(c => c.messages?.length);
  await loadConversations();
  if (!configured) showError('L’API Qwen n’est pas configurée. Vérifie les variables QWEN_BASE_URL et QWEN_API_KEY.');
}
async function loadConversations() {
  const chats = await api('/api/conversations');
  data.chats = chats.map(chat => ({...chat, messages: [], loaded: false}));
  if (data.chats.length) await selectChat(data.chats[0].id);
  else await createChat();
}
async function selectChat(id) {
  if (busy || !user) return;
  try {
    const chat = await api(`/api/conversations/${id}`);
    chat.message_count = chat.messages.length; chat.loaded = true;
    const index = data.chats.findIndex(c => c.id === id);
    if (index >= 0) data.chats[index] = chat; else data.chats.unshift(chat);
    currentId = id; $('error').hidden = true; $('sidebar').classList.remove('open'); render();
  } catch (error) { showError(error.message); }
}
async function createChat() {
  if (busy || !user) return;
  const empty = data.chats.find(chat => !chat.message_count && !chat.messages.length);
  if (empty) { await selectChat(empty.id); $('prompt').focus(); return; }
  try {
    const chat = await api('/api/conversations', {method: 'POST'});
    chat.loaded = true; chat.message_count = 0; data.chats.unshift(chat); currentId = chat.id;
    $('error').hidden = true; $('sidebar').classList.remove('open'); render(); $('prompt').focus();
  } catch (error) { showError(error.message); }
}
function renderHistory() {
  const history = $('history'); history.replaceChildren();
  const chats = data.chats.filter(chat => chat.message_count || chat.messages.length);
  if (!chats.length) { const p = document.createElement('p'); p.className = 'history-empty'; p.textContent = 'Vos conversations apparaîtront ici.'; history.append(p); }
  for (const chat of chats) {
    const row = document.createElement('div'); row.className = `history-row${chat.id === currentId ? ' active' : ''}`;
    const button = document.createElement('button'); button.className = 'history-item'; button.textContent = chat.title; button.title = chat.title;
    button.onclick = () => selectChat(chat.id);
    const remove = document.createElement('button'); remove.className = 'delete-conversation'; remove.setAttribute('aria-label', `Supprimer ${chat.title}`); remove.title = 'Supprimer la conversation';
    remove.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5M14 11v5"/></svg>';
    remove.onclick = async () => {
      if (busy || !confirm('Supprimer cette conversation de ton compte ?')) return;
      try {
        await api(`/api/conversations/${chat.id}`, {method: 'DELETE'});
        data.chats = data.chats.filter(c => c.id !== chat.id);
        if (currentId === chat.id) { if (data.chats.length) await selectChat(data.chats[0].id); else await createChat(); }
        else renderHistory();
      } catch (error) { showError(error.message); }
    };
    row.append(button, remove); history.append(row);
  }
}
function markdown(text) { return renderMarkdown(text); }
function copyButton(content, label) {
  const button = document.createElement('button');
  button.className = 'message-action copy-response';
  button.type = 'button';
  button.innerHTML = chatIcons.copy;
  button.setAttribute('aria-label', label);
  button.title = label;
  button.onclick = () => copyText(content, button);
  return button;
}
function messageElement(message, index) {
  const node = document.createElement('article'); node.className = `message ${message.role}`; node.dataset.index = index;
  if (message.role === 'user') {
    const content = document.createElement('div'); content.className = 'message-content'; content.textContent = message.content;
    const footer = document.createElement('div'); footer.className = 'message-footer';
    footer.append(copyButton(message.content, 'Copier la question'));
    node.append(content, footer);
  }
  else {
    node.innerHTML = '<div class="assistant-heading">L’Observatoire</div><div class="message-content"></div><div class="message-footer"></div>';
    updateAssistant(node, message, false);
  }
  return node;
}
function updateAssistant(node, message, streaming) {
  node.classList.toggle('streaming', streaming);
  if (node.renderedText !== message.content || node.renderedStreaming !== streaming) {
    node.querySelector('.message-content').innerHTML = message.content ? markdown(message.content) : (streaming ? '<span class="typing">L’Observatoire prépare sa réponse…</span>' : '<span class="typing">Aucune réponse finale reçue.</span>');
    node.renderedText = message.content;
    node.renderedStreaming = streaming;
  }
  const footer = node.querySelector('.message-footer'); footer.replaceChildren();
  if (!streaming) {
    footer.append(copyButton(message.content, 'Copier la réponse'));
    if (indexIsLastAssistant(node.dataset.index)) { const retry = document.createElement('button'); retry.className = 'message-action retry-response'; retry.type = 'button'; retry.setAttribute('aria-label', 'Relancer la réponse'); retry.title = 'Relancer la réponse'; retry.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 7a7 7 0 0 1 11.5-1L20 9M4 15l2.4 3A7 7 0 0 0 17.9 17"/></svg>'; retry.onclick = regenerate; footer.append(retry); }
  }
}
function indexIsLastAssistant(index) { return Number(index) === current().messages.length - 1; }
function render() {
  renderHistory();
  const messages = current()?.messages || [];
  $('welcome').hidden = messages.length > 0;
  $('workspace').classList.toggle('empty', messages.length === 0);
  $('messages').replaceChildren(...messages.map(messageElement));
  $('main').scrollTop = $('main').scrollHeight;
  updateSend();
}
function showError(message, retry = false) {
  const box = $('error'); box.textContent = message; box.hidden = false;
  if (retry) { const button = document.createElement('button'); button.textContent = 'Réessayer'; button.onclick = regenerate; box.append(button); }
}
async function copyText(text, button) {
  try {
    await navigator.clipboard.writeText(text);
    button.dataset.copyLabel ||= button.getAttribute('aria-label') || 'Copier';
    clearTimeout(button.copyReset);
    button.innerHTML = chatIcons.check;
    button.title = 'Copié !';
    button.setAttribute('aria-label', 'Copié !');
    button.copyReset = setTimeout(() => {
      button.innerHTML = chatIcons.copy;
      button.title = button.dataset.copyLabel;
      button.setAttribute('aria-label', button.dataset.copyLabel);
    }, 1800);
  }
  catch { showError('La copie nécessite un navigateur autorisant le presse-papiers. Tu peux sélectionner le texte directement.'); }
}
$('messages').addEventListener('click', event => { const button = event.target.closest('.copy-code'); if (button) copyText(button.closest('pre').querySelector('code').textContent, button); });
function updateSend() { $('send').disabled = busy || !user || !configured || !$('prompt').value.trim(); $('send').hidden = busy; $('stop').hidden = !busy; }
function resizePrompt() { $('prompt').style.height = 'auto'; $('prompt').style.height = `${Math.min($('prompt').scrollHeight, 180)}px`; updateSend(); }
async function persistChat(chat) {
  const saved = await api(`/api/conversations/${chat.id}`, {method: 'PUT', body: {version: chat.version, messages: chat.messages}});
  Object.assign(chat, saved, {message_count: saved.messages.length, loaded: true});
}
async function submit(event) {
  event?.preventDefault();
  if (busy || !configured || !user) return;
  const content = $('prompt').value.trim(); if (!content) return;
  const chat = current(); if (!chat) return;
  if (chat.messages.length >= 98) { showError('Cette conversation est longue. Ouvre un nouveau chat pour continuer.'); return; }
  chat.messages.push({role: 'user', content}); chat.message_count = chat.messages.length;
  if (chat.messages.length === 1) chat.title = content.slice(0, 80);
  $('prompt').value = ''; resizePrompt(); await requestAnswer();
}
async function regenerate() {
  if (busy || !configured || !user) return;
  const chat = current(); const last = chat?.messages.findLastIndex(message => message.role === 'user');
  if (last === undefined || last < 0) return;
  chat.messages = chat.messages.slice(0, last + 1); await requestAnswer();
}
async function requestAnswer() {
  const chat = current(); const accountId = user.id;
  busy = true; controller = new AbortController(); const abort = controller;
  $('error').hidden = true; toggleGenerationSettings(false); render();
  let assistant, node, baseVersion = chat.version;
  const started = performance.now(); let complete = false, limited = false;
  try {
    await persistChat(chat); baseVersion = chat.version;
    assistant = {role: 'assistant', content: '', reasoning: ''}; chat.messages.push(assistant);
    render(); node = $('messages').lastElementChild; updateAssistant(node, assistant, true);
    const response = await api(`/api/conversations/${chat.id}/generate`, {method: 'POST', stream: true,
      body: {version: chat.version, reasoning_effort: SETTINGS.effort, temperature: SETTINGS.temperature, max_tokens: SETTINGS.maxTokens}, signal: abort.signal});
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
    function processEvent(event) {
      const raw = event.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
      if (!raw) return;
      if (raw.trim() === '[DONE]') { complete = true; return; }
      const packet = JSON.parse(raw); if (packet.error) throw new Error(packet.error.message || 'Le flux Qwen a rencontré une erreur.');
      const choice = packet.choices?.[0], delta = choice?.delta || {};
      if (typeof delta.content === 'string') assistant.content += delta.content;
      const reasoning = delta.reasoning_content ?? delta.reasoning ?? delta.provider_specific_fields?.reasoning;
      if (typeof reasoning === 'string') assistant.reasoning += reasoning;
      if (packet.usage) assistant.tokens = packet.usage.completion_tokens;
      if (choice?.finish_reason === 'length') limited = true;
    }
    while (true) {
      const {value, done} = await reader.read();
      buffer = (buffer + decoder.decode(value || new Uint8Array(), {stream: !done})).replace(/\r\n/g, '\n');
      let split;
      const nearBottom = $('main').scrollHeight - $('main').scrollTop - $('main').clientHeight < 130;
      while ((split = buffer.indexOf('\n\n')) >= 0) { processEvent(buffer.slice(0, split)); buffer = buffer.slice(split + 2); }
      if (user?.id !== accountId) return;
      updateAssistant(node, assistant, true);
      if (nearBottom) $('main').scrollTop = $('main').scrollHeight;
      if (done) { if (buffer.trim()) processEvent(buffer); break; }
    }
    if (!complete) throw new Error('La connexion a été interrompue avant la fin de la réponse.');
    if (!assistant.content.trim()) showError('Le modèle n’a pas produit de réponse finale. Essaie un niveau de réflexion plus léger.', true);
    else if (limited) showError('La réponse a atteint sa limite de longueur. Demande au modèle de continuer.', true);
  } catch (error) {
    abort.abort(); if (assistant) assistant.interrupted = true;
    if (user?.id === accountId) showError(error.name === 'AbortError' ? 'Génération arrêtée.' : error.message, true);
  } finally {
    if (user?.id === accountId) {
      try {
        // [DONE] is emitted by the API only after the database commit. On cancel,
        // give the API a short window to store the partial response.
        for (let attempt = 0; attempt < 8; attempt++) {
          const saved = await api(`/api/conversations/${chat.id}`);
          if (saved.version > baseVersion || !assistant) { Object.assign(chat, saved, {message_count: saved.messages.length}); break; }
          if (complete) break;
          await new Promise(resolve => setTimeout(resolve, 100));
        }
      } catch (error) { showError(error.message); }
      if (assistant && !assistant.content && !assistant.reasoning && chat.messages.at(-1) === assistant) chat.messages.pop();
      busy = false; controller = null; render(); $('prompt').focus();
    }
  }
}
function toggleGenerationSettings(open, restoreFocus = false) {
  $('generation-settings').hidden = !open; $('generation-toggle').setAttribute('aria-expanded', String(open));
  if (restoreFocus) $('generation-toggle').focus();
}
function updateGenerationControls() {
  $('effort').value = SETTINGS.effort; $('temperature').value = SETTINGS.temperature;
  $('temperature-value').textContent = SETTINGS.temperature.toLocaleString('fr-FR', {minimumFractionDigits: 1, maximumFractionDigits: 1});
  const labels = {none: 'désactivée', low: 'légère', medium: 'intermédiaire', xhigh: 'approfondie'};
  $('generation-toggle').title = `Réflexion ${labels[SETTINGS.effort]} · Température ${$('temperature-value').textContent}`;
}
$('generation-toggle').onclick = () => toggleGenerationSettings($('generation-settings').hidden);
$('generation-close').onclick = () => toggleGenerationSettings(false, true);
$('effort').onchange = () => { SETTINGS.effort = $('effort').value; updateGenerationControls(); save(); };
$('temperature').oninput = () => { SETTINGS.temperature = Number($('temperature').value); updateGenerationControls(); save(); };
document.addEventListener('click', event => {
  if (!$('generation-settings').hidden && !$('generation-settings').contains(event.target) && !$('generation-toggle').contains(event.target)) toggleGenerationSettings(false);
  if (!$('account-panel').hidden && !$('account-panel').contains(event.target) && !$('account-toggle').contains(event.target)) $('account-panel').hidden = true;
});
$('menu').onclick = () => { if (innerWidth <= 760) $('sidebar').classList.toggle('open'); else $('sidebar').classList.toggle('collapsed'); };
$('sidebar-close').onclick = () => { if (innerWidth <= 760) $('sidebar').classList.remove('open'); else $('sidebar').classList.add('collapsed'); };
$('sidebar-backdrop').onclick = () => $('sidebar').classList.remove('open');
$('new-chat').onclick = createChat; $('chat-form').onsubmit = submit; $('stop').onclick = () => controller?.abort();
$('prompt').oninput = resizePrompt;
$('prompt').onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit(); } };
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') { $('sidebar').classList.remove('open'); $('account-panel').hidden = true; if (!$('generation-settings').hidden) toggleGenerationSettings(false, true); }
  if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'n') { event.preventDefault(); createChat(); }
});
$('login-form').onsubmit = async event => {
  event.preventDefault(); $('login-submit').disabled = true; $('login-error').textContent = '';
  try { const auth = await api('/api/auth/login', {method: 'POST', body: {username: $('login-username').value, password: $('login-password').value}}); await startAccount(auth); }
  catch (error) { if (user) showError(error.message); else $('login-error').textContent = error.message; }
  finally { $('login-submit').disabled = false; $('login-password').value = ''; }
};
$('account-toggle').onclick = () => { $('account-panel').hidden = !$('account-panel').hidden; };
$('logout').onclick = async () => {
  try { controller?.abort(); await api('/api/auth/logout', {method: 'POST'}); showLogin(); }
  catch (error) { showError(error.message); }
};
$('change-password').onclick = () => { $('account-panel').hidden = true; $('password-error').textContent = ''; $('password-form').reset(); $('password-dialog').showModal(); };
$('password-cancel').onclick = () => $('password-dialog').close();
$('password-form').onsubmit = async event => {
  event.preventDefault(); $('password-submit').disabled = true; $('password-error').textContent = '';
  try {
    if ($('new-password').value !== $('confirm-password').value) throw new Error('Les nouveaux mots de passe ne correspondent pas.');
    await api('/api/auth/password', {method: 'PUT', body: {current_password: $('current-password').value, new_password: $('new-password').value}});
    $('password-dialog').close(); showLogin('Mot de passe modifié. Reconnecte-toi.');
  } catch (error) { $('password-error').textContent = error.message; }
  finally { $('password-submit').disabled = false; }
};
$('import-legacy').onclick = async () => {
  if (!user || !confirm('Importer les conversations de ce navigateur dans ton compte ? Ne le fais que si elles t’appartiennent.')) return;
  const button = $('import-legacy'); button.disabled = true;
  try {
    const chats = legacy.chats.filter(chat => chat.messages?.length).map(chat => ({messages: chat.messages}));
    await api('/api/conversations/import', {method: 'POST', body: {chats}});
    try { localStorage.setItem(`observatoire-imported:${user.id}`, 'true'); } catch {}
    button.hidden = true; $('account-panel').hidden = true; await loadConversations();
  } catch (error) { showError(error.message); }
  finally { button.disabled = false; }
};
updateGenerationControls();
(async () => {
  try { await startAccount(await api('/api/auth/me')); }
  catch (error) { if (error.status === 401) showLogin(); else if (user) showError(error.message); else showLogin(error.message); }
})();
