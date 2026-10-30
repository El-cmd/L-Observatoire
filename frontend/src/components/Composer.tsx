import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import type {Effort, Notice, Settings, ContextUsage} from '../types';
import {Icon} from './Icon';
import {ContextMeter} from './ContextMeter';

const effortLabels = {none:'désactivée', low:'légère', medium:'intermédiaire', xhigh:'approfondie'};

export function Composer({prompt, onPrompt, onSend, onStop, onRegenerate, settings, onSettings, busy, disabled, notice, chatId, contextUsage, compacting, onCompact}: {
  prompt: string; onPrompt: (value: string) => void; onSend: (value: string) => void; onStop: () => void;
  onRegenerate: () => void; settings: Settings; onSettings: (value: Settings) => void; busy: boolean;
  disabled: boolean; notice: Notice | null; chatId?: string;
  contextUsage: ContextUsage | null; compacting: boolean; onCompact: () => void;
}) {
  const [open, setOpen] = useState(false);
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
  return <div className="composer-area">
    <div id="error" className="error" role="alert" hidden={!notice}>{notice?.message}{notice?.retry && <button type="button" onClick={onRegenerate}>Réessayer</button>}</div>
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
    <form id="chat-form" className="composer" onSubmit={event => {event.preventDefault(); if (!busy && !disabled && prompt.trim()) onSend(prompt);}}>
      <label className="sr-only" htmlFor="prompt">Votre message</label>
      <textarea id="prompt" ref={area} rows={1} placeholder="Demander à L’Observatoire" maxLength={100000} value={prompt} onChange={event => onPrompt(event.target.value)}
        onKeyDown={event => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {event.preventDefault(); if (!busy && !disabled && prompt.trim()) onSend(prompt);}
        }}/>
      <ContextMeter usage={contextUsage} compacting={compacting} disabled={busy || disabled && !compacting} onCompact={onCompact}/>
      <button id="generation-toggle" ref={toggle} type="button" className="generation-toggle icon-button" aria-label="Régler la température et la réflexion" title={`Réflexion ${effortLabels[settings.effort]} · Température ${temperature}`} aria-controls="generation-settings" aria-expanded={open} onClick={() => setOpen(value => !value)}><Icon name="settings"/></button>
      <button id="send" type="submit" className="send-button" aria-label="Envoyer le message" disabled={busy || disabled || !prompt.trim()} hidden={busy}><Icon name="send"/></button>
      <button id="stop" type="button" className="stop-button" aria-label="Arrêter la réponse" hidden={!busy} onClick={onStop}><Icon name="stop"/></button>
    </form>
    <p className="composer-note">L’Observatoire peut faire des erreurs.</p>
  </div>;
}
