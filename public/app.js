'use strict';
const $ = id => document.getElementById(id);
const STORAGE = 'observatoir-chat-v1';
let data;
try { data = JSON.parse(localStorage.getItem(STORAGE) || localStorage.getItem('qwen-chat-v1')); } catch { /* Empty or inaccessible storage. */ }
if (!data || !Array.isArray(data.chats)) data = {chats: []};
const savedSettings = data.settings || {};
const SETTINGS = {
  effort: ['none', 'low', 'medium', 'xhigh'].includes(savedSettings.effort) ? savedSettings.effort : 'none',
  temperature: typeof savedSettings.temperature === 'number' && Number.isFinite(savedSettings.temperature) && savedSettings.temperature >= 0 && savedSettings.temperature <= 2 ? savedSettings.temperature : 0.7,
  maxTokens: 4096
};
data.settings = SETTINGS;
data.chats = data.chats.filter(c => c && typeof c.id === 'string' && Array.isArray(c.messages));
let currentId = data.chats[0]?.id;
let busy = false, controller = null, configured = false;
function newId() { return globalThis.crypto?.randomUUID?.() || `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`; }
function current() { return data.chats.find(c => c.id === currentId); }
function save() {
  try { localStorage.setItem(STORAGE, JSON.stringify(data)); }
  catch { showError('Le stockage du navigateur est plein ou indisponible. Certaines conversations ne pourront pas être conservées.'); }
}
function createChat() {
  if (busy) return;
  const empty = data.chats.find(c => !c.messages.length);
  if (empty) currentId = empty.id;
  else { const chat = {id: newId(), title: 'Nouvelle conversation', messages: []}; data.chats.unshift(chat); currentId = chat.id; }
  $('error').hidden = true;
  $('sidebar').classList.remove('open');
  render(); save(); $('prompt').focus();
}
function renderHistory() {
  const history = $('history'); history.replaceChildren();
  const chats = data.chats.filter(c => c.messages.length);
  if (!chats.length) { const p = document.createElement('p'); p.className = 'history-empty'; p.textContent = 'Vos conversations apparaîtront ici.'; history.append(p); }
  for (const chat of chats) {
    const row = document.createElement('div'); row.className = `history-row${chat.id === currentId ? ' active' : ''}`;
    const button = document.createElement('button'); button.className = 'history-item';
    button.textContent = chat.title; button.title = chat.title;
    button.onclick = () => { if (busy) return; currentId = chat.id; $('error').hidden = true; $('sidebar').classList.remove('open'); render(); };
    const remove = document.createElement('button'); remove.className = 'delete-conversation';
    remove.setAttribute('aria-label', `Supprimer ${chat.title}`); remove.title = 'Supprimer la conversation';
    remove.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5M14 11v5"/></svg>';
    remove.onclick = () => {
      if (busy || !confirm('Supprimer cette conversation ?')) return;
      data.chats = data.chats.filter(c => c.id !== chat.id);
      if (currentId === chat.id) currentId = data.chats[0]?.id;
      if (!currentId) createChat(); else { save(); render(); }
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
function updateSend() { $('send').disabled = busy || !configured || !$('prompt').value.trim(); $('send').hidden = busy; $('stop').hidden = !busy; }
function resizePrompt() { $('prompt').style.height = 'auto'; $('prompt').style.height = `${Math.min($('prompt').scrollHeight, 180)}px`; updateSend(); }
async function submit(event) {
  event?.preventDefault();
  if (busy || !configured) return;
  const content = $('prompt').value.trim(); if (!content) return;
  const chat = current();
  if (chat.messages.length >= 98) { showError('Cette conversation est longue. Ouvre une nouvelle conversation pour continuer.'); return; }
  chat.messages.push({role: 'user', content});
  if (chat.messages.length === 1) chat.title = content.slice(0, 55);
  $('prompt').value = ''; resizePrompt(); await requestAnswer();
}
async function regenerate() {
  if (busy || !configured) return;
  const chat = current();
  const last = chat.messages.findLastIndex(message => message.role === 'user'); if (last < 0) return;
  chat.messages = chat.messages.slice(0, last + 1); await requestAnswer();
}
async function requestAnswer() {
  const chat = current();
  const outgoing = chat.messages.filter(message => !message.interrupted && typeof message.content === 'string' && message.content.trim()).map(({role, content}) => ({role, content}));
  const assistant = {role: 'assistant', content: '', reasoning: ''}; chat.messages.push(assistant);
  busy = true; controller = new AbortController(); $('error').hidden = true;
  render(); save();
  const node = $('messages').lastElementChild; updateAssistant(node, assistant, true);
  const started = performance.now(); let complete = false, limited = false;
  try {
    const response = await fetch('/api/chat', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({messages: outgoing, reasoning_effort: SETTINGS.effort, temperature: Number(SETTINGS.temperature), max_tokens: Number(SETTINGS.maxTokens)}), signal: controller.signal});
    if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.error || `Erreur HTTP ${response.status}`); }
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
    function processEvent(event) {
      const raw = event.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
      if (!raw) return;
      if (raw.trim() === '[DONE]') { complete = true; return; }
      const packet = JSON.parse(raw);
      if (packet.error) throw new Error(packet.error.message || 'Le flux Qwen a rencontré une erreur.');
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
      updateAssistant(node, assistant, true);
      if (nearBottom) $('main').scrollTop = $('main').scrollHeight;
      if (done) { if (buffer.trim()) processEvent(buffer); break; }
    }
    if (!complete) throw new Error('La connexion a été interrompue avant la fin de la réponse.');
    if (!assistant.content.trim()) showError('Le modèle n’a pas produit de réponse. Tu peux réessayer.', true);
    else if (limited) showError('La réponse a atteint sa limite de longueur. Demande au modèle de continuer.', true);
  } catch (error) {
    controller.abort(); assistant.interrupted = true;
    showError(error.name === 'AbortError' ? 'Génération arrêtée.' : error.message, true);
  } finally {
    assistant.seconds = Math.round((performance.now() - started) / 100) / 10;
    busy = false; controller = null;
    if (!assistant.content && !assistant.reasoning) chat.messages.pop();
    save(); render(); $('prompt').focus();
  }
}
function toggleGenerationSettings(open, restoreFocus = false) {
  $('generation-settings').hidden = !open;
  $('generation-toggle').setAttribute('aria-expanded', String(open));
  if (restoreFocus) $('generation-toggle').focus();
}
function updateGenerationControls() {
  $('effort').value = SETTINGS.effort;
  $('temperature').value = SETTINGS.temperature;
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
});
updateGenerationControls();
$('menu').onclick = () => {
  if (innerWidth <= 760) $('sidebar').classList.toggle('open');
  else $('sidebar').classList.toggle('collapsed');
};
$('sidebar-close').onclick = () => {
  if (innerWidth <= 760) $('sidebar').classList.remove('open');
  else $('sidebar').classList.add('collapsed');
};
$('sidebar-backdrop').onclick = () => $('sidebar').classList.remove('open');
$('new-chat').onclick = createChat;
$('chat-form').onsubmit = submit;
$('stop').onclick = () => controller?.abort();
$('prompt').oninput = resizePrompt;
$('prompt').onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit(); } };
document.addEventListener('keydown', event => { if (event.key === 'Escape') { $('sidebar').classList.remove('open'); if (!$('generation-settings').hidden) toggleGenerationSettings(false, true); } if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'n') { event.preventDefault(); createChat(); } });
if (!currentId) createChat(); else render();
fetch('/api/health').then(response => { if (!response.ok) throw new Error(); return response.json(); }).then(health => {
  configured = health.configured;
  $('connection').textContent = configured ? 'API configurée' : 'Configuration requise'; $('connection').classList.toggle('offline', !configured);
  if (!configured) showError('Ajoute ta clé dans QWEN_API_KEY (.env), puis redémarre avec make restart.');
  updateSend();
}).catch(() => { $('connection').textContent = 'Serveur indisponible'; $('connection').classList.add('offline'); showError('Impossible de joindre le serveur du chat.'); });
