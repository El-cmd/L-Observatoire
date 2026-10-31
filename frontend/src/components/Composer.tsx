import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import type {Effort, Notice, PendingImage, Settings, ContextUsage} from '../types';
import {Icon} from './Icon';
import {ContextMeter} from './ContextMeter';

const effortLabels = {none:'désactivée', low:'légère', medium:'intermédiaire', xhigh:'approfondie'};

export function Composer({prompt, onPrompt, pending, onAddImages, onRemovePending, onOpenLibrary, onSend, onStop, onRegenerate, onContinue, settings, onSettings, busy, disabled, notice, chatId, contextUsage, compacting, onCompact}: {
  pending: PendingImage[]; onAddImages: (files: File[]) => void; onRemovePending: (key: string) => void; onOpenLibrary: () => void;
  prompt: string; onPrompt: (value: string) => void; onSend: (value: string) => void; onStop: () => void;
  onRegenerate: () => void; onContinue: () => void; settings: Settings; onSettings: (value: Settings) => void; busy: boolean;
  disabled: boolean; notice: Notice | null; chatId?: string;
  contextUsage: ContextUsage | null; compacting: boolean; onCompact: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [dragging, setDragging] = useState(false);
  const files = useRef<HTMLInputElement>(null);
  const addMenu = useRef<HTMLDivElement>(null);
  const images = (list: FileList | null | undefined) => Array.from(list || []).filter(file => file.type.startsWith('image/'));
  const uploading = pending.some(item => item.status === 'uploading');
  const ready = pending.length > 0 && pending.every(item => item.status === 'ready');
  const canSend = !busy && !disabled && !uploading && (Boolean(prompt.trim()) || ready);
  useEffect(() => {
    if (!adding) return;
    function outside(event: MouseEvent) {if (!addMenu.current?.contains(event.target as Node)) setAdding(false);}
    function escape(event: KeyboardEvent) {if (event.key === 'Escape') setAdding(false);}
    document.addEventListener('click', outside); document.addEventListener('keydown', escape);
    return () => {document.removeEventListener('click', outside); document.removeEventListener('keydown', escape);};
  }, [adding]);
  const area = useRef<HTMLTextAreaElement>(null);
  const panel = useRef<HTMLElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => {
    const element = area.current; if (!element) return;
    element.style.height = 'auto'; element.style.height = `${Math.min(element.scrollHeight, 180)}px`;
  }, [prompt]);
  useEffect(() => {if (!busy && !disabled) area.current?.focus(); if (busy) setOpen(false);}, [busy, disabled, chatId]);
  useEffect(() => {
    if (!open) return;
    function outside(event: MouseEvent) {
      if (!panel.current?.contains(event.target as Node) && !toggle.current?.contains(event.target as Node)) setOpen(false);
    }
    function escape(event: KeyboardEvent) {if (event.key === 'Escape') {setOpen(false); toggle.current?.focus();}}
    document.addEventListener('click', outside); document.addEventListener('keydown', escape);
    return () => {document.removeEventListener('click', outside); document.removeEventListener('keydown', escape);};
  }, [open]);
  const temperature = settings.temperature.toLocaleString('fr-FR', {minimumFractionDigits:1, maximumFractionDigits:1});
  return <div className={`composer-area${dragging ? ' dragging' : ''}`}
    onDragOver={event => {if (!disabled && event.dataTransfer.types.includes('Files')) {event.preventDefault(); setDragging(true);}}}
    onDragLeave={event => {if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false);}}
    onDrop={event => {setDragging(false); const list = images(event.dataTransfer.files); if (list.length && !disabled) {event.preventDefault(); onAddImages(list);}}}>
    <div id="error" className="error" role="alert" hidden={!notice}>{notice?.message}{notice?.resume && <button type="button" onClick={onContinue}>Continuer</button>}{notice?.retry && <button type="button" onClick={onRegenerate}>Réessayer</button>}</div>
    <section id="generation-settings" className="generation-settings" aria-label="Réglages de génération" hidden={!open} ref={panel}>
      <div className="generation-heading"><span>Réglages</span><button id="generation-close" type="button" className="icon-button" aria-label="Fermer les réglages" onClick={() => {setOpen(false); toggle.current?.focus();}}><Icon name="close"/></button></div>
      <label htmlFor="effort">Réflexion</label>
      <select id="effort" value={settings.effort} onChange={event => onSettings({...settings, effort:event.target.value as Effort})}>
        <option value="none">Désactivée</option><option value="low">Légère</option><option value="medium">Intermédiaire</option><option value="xhigh">Approfondie</option>
      </select>
      <label htmlFor="temperature">Température <output id="temperature-value" htmlFor="temperature">{temperature}</output></label>
      <input id="temperature" type="range" min="0" max="2" step="0.1" value={settings.temperature} onChange={event => onSettings({...settings, temperature:Number(event.target.value)})}/>
      <div className="temperature-scale"><span>Précis</span><span>Varié</span></div><p>Appliqué aux prochains messages.</p>
    </section>
    {pending.length > 0 && <ul className="pending-images" aria-label="Images jointes au message">
      {pending.map(item => <li key={item.key} className={`pending-image is-${item.status}`} title={item.error || item.name}>
        <img src={item.preview} alt={item.name}/>
        {item.status === 'uploading' && <span className="pending-state" role="status" aria-label={`Envoi de ${item.name}`}/>}
        {item.status === 'error' && <span className="pending-error" role="alert">{item.error}</span>}
        <button type="button" className="pending-remove" aria-label={`Retirer ${item.name}`} onClick={() => onRemovePending(item.key)}><Icon name="close"/></button>
      </li>)}
    </ul>}
    <form id="chat-form" className="composer" onSubmit={event => {event.preventDefault(); if (canSend) onSend(prompt);}}>
      <div className="attach" ref={addMenu}>
        <button id="attach-toggle" type="button" className="attach-toggle icon-button" aria-label="Ajouter des images" title="Ajouter des images" aria-haspopup="menu" aria-expanded={adding} disabled={disabled} onClick={() => setAdding(value => !value)}><Icon name="plus"/></button>
        {adding && <div className="attach-menu" role="menu">
          <button type="button" role="menuitem" onClick={() => {setAdding(false); files.current?.click();}}><Icon name="image"/>Images de l’ordinateur</button>
          <button type="button" role="menuitem" onClick={() => {setAdding(false); onOpenLibrary();}}><Icon name="link"/>Depuis la bibliothèque</button>
        </div>}
        <input ref={files} id="attach-files" type="file" accept="image/*" multiple hidden onChange={event => {const list = images(event.target.files); event.target.value = ''; if (list.length) onAddImages(list);}}/>
      </div>
      <label className="sr-only" htmlFor="prompt">Votre message</label>
      <textarea id="prompt" ref={area} rows={1} placeholder="Demander à L’Observatoire" maxLength={100000} value={prompt} onChange={event => onPrompt(event.target.value)}
        onPaste={event => {const list = images(event.clipboardData.files); if (list.length) {event.preventDefault(); onAddImages(list);}}}
        onKeyDown={event => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {event.preventDefault(); if (canSend) onSend(prompt);}
        }}/>
      <ContextMeter usage={contextUsage} compacting={compacting} disabled={busy || disabled && !compacting} onCompact={onCompact}/>
      <button id="generation-toggle" ref={toggle} type="button" className="generation-toggle icon-button" aria-label="Régler la température et la réflexion" title={`Réflexion ${effortLabels[settings.effort]} · Température ${temperature}`} aria-controls="generation-settings" aria-expanded={open} onClick={() => setOpen(value => !value)}><Icon name="settings"/></button>
      <button id="send" type="submit" className="send-button" aria-label="Envoyer le message" disabled={!canSend} hidden={busy}><Icon name="send"/></button>
      <button id="stop" type="button" className="stop-button" aria-label="Arrêter la réponse" hidden={!busy} onClick={onStop}><Icon name="stop"/></button>
    </form>
    <p className="composer-note">L’Observatoire peut faire des erreurs.</p>
  </div>;
}
