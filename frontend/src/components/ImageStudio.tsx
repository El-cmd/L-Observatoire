import {useEffect, useRef, useState} from 'react';
import type {AttachmentRef, CreateBody, CreationConfig, CreationStyle, Library, LibraryItem, MyStyle} from '../types';
import {imageURL, thumbnailURL, toRef} from '../lib/images';
import {errorMessage} from '../lib/api';
import {Icon} from './Icon';
import {StyleDialog, type StyleApi} from './StyleDialog';
import {SourcePicker} from './SourcePicker';
import {MaskPainter, type Zone} from './MaskPainter';

/** Settings kept in the browser, per account. */
/** `edit`: what to do with a starting image, "retouche" (only what is asked changes) or "transformer" (redrawn with `strength`). */
interface Settings { style: string; format: string; size: string; count: number; improve: boolean; strength: string; edit: 'retouche' | 'transformer'; quality: string }
type Waiting = {key: string; size: string; label: string; error?: string};

/** Example of a style: a file for the built-in ones, created by the image model for "Mes styles". */
function example(style: CreationStyle | MyStyle): string | null {
  if (!('version' in style)) return `/creation/styles/${style.id}.webp`;
  return style.example ? `/api/creation/styles/${style.id}/example?v=${style.version}` : null;
}
const allStyles = (config: CreationConfig): (CreationStyle | MyStyle)[] => [...config.styles, ...config.my_styles];
const times = (size: string) => size.replace('x', '×');

/** Size of an image created in HD (×1.5) or Très HD (×2), at most 2 048 px on the longest side: the
 * image service's own rule, to show it before creating. */
function finalSize(size: string, quality: string): string {
  const [width, height] = size.split('x').map(Number);
  const scale = Math.min({hd: 1.5, 'tres-hd': 2}[quality] ?? 1, 2048 / Math.max(width, height));
  if (scale <= 1) return size;
  const w = Math.min(2048, Math.round(width * scale / 32) * 32);
  return `${w}x${Math.min(2048, Math.round(w * height / width / 32) * 32)}`;
}

/** Allowed size closest to the proportions of an image (the largest on a tie): the starting image is
 * cropped as little as possible. */
function sizeFor(config: CreationConfig, width: number, height: number): string {
  const gap = (size: string) => {const [w, h] = size.split('x').map(Number); return Math.abs(Math.log(w / h) - Math.log(width / height));};
  const area = (size: string) => size.split('x').map(Number).reduce((a, b) => a * b, 1);
  return [...config.sizes].sort((a, b) => gap(a) - gap(b) || area(b) - area(a))[0] ?? config.default_size;
}

function defaults(config: CreationConfig): Settings {
  const square = config.formats.find(format => format.name === '1:1');
  return {style: config.default_style, format: square ? '1:1' : 'custom', size: square?.size ?? config.default_size, count: 1, improve: false, strength: config.default_strength, edit: 'retouche', quality: config.default_quality};
}

function restore(config: CreationConfig, saved: Partial<Settings> | null): Settings {
  const value = {...defaults(config), ...saved};
  if (!allStyles(config).some(style => style.id === value.style)) value.style = config.default_style;
  const format = config.formats.find(item => item.name === value.format);
  if (format) value.size = format.size;
  else if (value.format !== 'custom' || !config.sizes.includes(value.size)) Object.assign(value, {format: defaults(config).format, size: defaults(config).size});
  value.count = Math.min(Math.max(1, Number(value.count) || 1), config.max_count);
  value.improve = value.improve === true;
  if (!config.strengths.some(strength => strength.id === value.strength)) value.strength = config.default_strength;
  if (value.edit !== 'transformer') value.edit = 'retouche';
  if (!config.qualities.some(quality => quality.id === value.quality)) value.quality = config.default_quality;
  return value;
}

/** Images tab: creates images into the library, with a style, a size and a number of images. */
export function ImageStudio({userId, library, loadConfig, improvePrompt, createImage, uploadImage, styles, onLoad, onOpen, onDelete, onStartChat, removed}: {
  userId: string; library: Library | null; loadConfig: () => Promise<CreationConfig>;
  improvePrompt: (prompt: string, style: string, signal?: AbortSignal, source?: string, retouch?: boolean) => Promise<string>;
  createImage: (body: CreateBody, signal?: AbortSignal) => Promise<LibraryItem>;
  uploadImage: (file: File) => Promise<AttachmentRef>;
  styles: StyleApi;
  onLoad: () => void; onOpen: (image: AttachmentRef) => void; onDelete: (id: string) => void;
  onStartChat: (image: AttachmentRef) => void; removed: ReadonlySet<string>;
}) {
  const storageKey = `observatoire-creation:${userId}`;
  const [config, setConfig] = useState<CreationConfig | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [prompt, setPrompt] = useState('');
  const [beforeImprove, setBeforeImprove] = useState<string | null>(null);
  const [improved, setImproved] = useState<string | null>(null);
  const [improving, setImproving] = useState(false);
  const [error, setError] = useState('');
  const [created, setCreated] = useState<LibraryItem[]>([]);
  const [waiting, setWaiting] = useState<Waiting[]>([]);
  const [progress, setProgress] = useState('');
  const [menu, setMenu] = useState<'style' | 'count' | null>(null);
  const [editing, setEditing] = useState<{style: MyStyle | null} | null>(null);
  const [making, setMaking] = useState<ReadonlySet<string>>(new Set());
  // Phone: the settings fold under the description (always shown on a computer).
  const [advanced, setAdvanced] = useState(false);
  // "Image → image": the starting image, retouched by an instruction or redrawn with a strength.
  const [source, setSource] = useState<AttachmentRef | null>(null);
  const [picking, setPicking] = useState(false);
  // "Retoucher" a painted zone only (forgotten when the starting image changes).
  const [zone, setZone] = useState<Zone | null>(null);
  const [painting, setPainting] = useState(false);
  const running = useRef<AbortController | null>(null);
  const menus = useRef<HTMLDivElement>(null);

  useEffect(() => {
    onLoad();
    loadConfig().then(value => {
      let saved: Partial<Settings> | null = null;
      try { saved = JSON.parse(localStorage.getItem(storageKey) || 'null'); } catch {}
      setConfig(value); setSettings(restore(value, saved));
    }).catch(failure => setError(errorMessage(failure)));
    return () => running.current?.abort();
  }, []);
  useEffect(() => {
    if (!menu) return;
    const outside = (event: MouseEvent) => {if (!menus.current?.contains(event.target as Node)) setMenu(null);};
    const escape = (event: KeyboardEvent) => {if (event.key === 'Escape') setMenu(null);};
    document.addEventListener('click', outside); document.addEventListener('keydown', escape);
    return () => {document.removeEventListener('click', outside); document.removeEventListener('keydown', escape);};
  }, [menu]);

  function change(update: Partial<Settings>) {
    setSettings(value => {
      const next = {...value!, ...update};
      try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch {}
      return next;
    });
  }

  function keepStyle(style: MyStyle) {
    setConfig(value => value && {...value, my_styles: value.my_styles.some(other => other.id === style.id)
      ? value.my_styles.map(other => other.id === style.id ? style : other) : [...value.my_styles, style]});
  }

  /** The example takes as long as an image: made in the background, the tile waits meanwhile. */
  async function makeExample(id: string) {
    setMaking(value => new Set(value).add(id));
    try { keepStyle(await styles.example(id)); }
    catch (failure) { setError(`L’exemple du style n’a pas pu être créé : ${errorMessage(failure)}`); }
    finally { setMaking(value => {const next = new Set(value); next.delete(id); return next;}); }
  }

  function saved(style: MyStyle, created: boolean) {
    keepStyle(style);
    if (created) change({style: style.id});
    if (!style.example) void makeExample(style.id);
  }

  function deleted(id: string) {
    setConfig(value => value && {...value, my_styles: value.my_styles.filter(style => style.id !== id)});
    if (settings?.style === id) change({style: config!.default_style});
  }

  // Images created here first, then those of the library (the same image once).
  const seen = new Set<string>();
  const images = [...created, ...(library?.items.filter(item => item.generation) ?? [])]
    .filter(item => !removed.has(item.id) && !seen.has(item.id) && seen.add(item.id));
  const busy = running.current !== null;
  const retouch = source !== null && settings?.edit === 'retouche';
  // The starting image deleted from the library: back to creating from the description alone.
  useEffect(() => {if (source && removed.has(source.id)) setSource(null);}, [removed, source]);
  useEffect(() => setZone(null), [source?.id]);

  function startFrom(image: AttachmentRef) {
    setSource(image);
    if (config) {
      const size = sizeFor(config, image.width, image.height);
      change({size, format: config.formats.find(format => format.size === size)?.name ?? 'custom'});
    }
    document.getElementById('studio-prompt')?.focus();
  }

  async function improveNow() {
    if (!settings || !prompt.trim() || busy || improving) return;
    setError(''); setImproving(true);
    try {
      const text = await improvePrompt(prompt.trim(), settings.style, undefined, source?.id, retouch);
      // Improved twice: "Revenir à mon texte" still goes back to the user's own text.
      setBeforeImprove(value => value ?? prompt); setPrompt(text); setImproved(null);
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setImproving(false); }
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!settings || !config || running.current) return;
    const idea = prompt.trim();
    if (!idea) return;
    // Text written by the Améliorer button (perhaps retouched): kept as the improved version, with the idea it came from.
    // Kept after creating, so that creating again keeps it too; forgotten once the text is cleared.
    const original = !settings.improve && beforeImprove?.trim() ? beforeImprove.trim() : null;
    setError('');
    const controller = new AbortController(); running.current = controller;
    const batch = Date.now().toString(36);
    const count = settings.count, size = settings.size;
    const start = source ? {source: source.id, ...(retouch ? {retouch: true, ...(zone ? {mask: zone.mask} : {})} : {strength: settings.strength})} : {quality: settings.quality};
    // The tiles that wait have the proportions of the image to come (HD changes the size, a starting image keeps its own).
    const shown = source ? size : finalSize(size, settings.quality);
    setWaiting(Array.from({length: count}, (_, index) => ({key: `${batch}-${index}`, size: shown, label: `Image ${index + 1} / ${count}`})));
    const label = (index: number, text: string) => setWaiting(list => list.map(item => item.key === `${batch}-${index}` ? {...item, label: text} : item));
    const started = performance.now();
    let done = 0;
    try {
      let rewritten: string | null = original ? idea : null;
      // From a starting image, always: the image model redraws it from the text alone, so Qwen looks at the
      // image and describes all of it (unless the text already comes from Améliorer).
      if (settings.improve || (source && !original)) {
        // One rewriting for the whole series: the images share the same improved prompt.
        setWaiting(list => list.map(item => ({...item, label: 'Amélioration de la description…'})));
        setImproved(null);
        rewritten = await improvePrompt(idea, settings.style, controller.signal, source?.id, retouch);
        setImproved(rewritten);
      }
      for (let index = 0; index < count; index++) {
        label(index, `Création ${index + 1} / ${count}…`);
        try {
          const item = await createImage({prompt: original ?? idea, style: settings.style, size, improved: rewritten, ...start}, controller.signal);
          done++;
          setCreated(list => [item, ...list.filter(other => other.id !== item.id)]);
          setWaiting(list => list.filter(other => other.key !== `${batch}-${index}`));
          setProgress(`${done} / ${count} · ${((performance.now() - started) / 1000).toFixed(1)} s`);
        } catch (failure) {
          if (failure instanceof Error && failure.name === 'AbortError') throw failure;
          setWaiting(list => list.map(item => item.key === `${batch}-${index}` ? {...item, error: errorMessage(failure)} : item));
        }
      }
    } catch (failure) {
      if (!(failure instanceof Error && failure.name === 'AbortError')) setError(errorMessage(failure));
    } finally {
      running.current = null;
      setWaiting(list => list.filter(item => item.error));
      if (done) onLoad();
    }
  }

  function reuse(item: LibraryItem) {
    if (!config || !item.generation) return;
    const format = config.formats.find(value => value.size === item.generation!.size);
    change({style: allStyles(config).some(style => style.id === item.generation!.style) ? item.generation.style : config.default_style,
      ...(config.sizes.includes(item.generation.size) ? {size: item.generation.size, format: format ? format.name : 'custom'} : {}), count: 1,
      ...(item.generation.strength && config.strengths.some(value => value.id === item.generation!.strength!.id) ? {strength: item.generation.strength.id, edit: 'transformer' as const} : {}),
      ...(item.generation.retouch ? {edit: 'retouche' as const} : {}),
      ...(!item.generation.source ? {quality: item.generation.quality && config.qualities.some(value => value.id === item.generation!.quality!.id) ? item.generation.quality.id : config.default_quality} : {})});
    // The same starting image, if it is still in the library.
    const start = item.generation.source ? library?.items.find(value => value.id === item.generation!.source && !removed.has(value.id)) : undefined;
    setSource(start ? toRef(start) : null);
    setPrompt(item.generation.prompt); setBeforeImprove(null);
    document.getElementById('studio-prompt')?.focus();
  }

  if (!config || !settings) return <section className="studio" id="studio" aria-label="Images">
    {error ? <p className="studio-error" role="alert">{error}</p> : <p className="library-empty" role="status">Chargement…</p>}
  </section>;

  const style = allStyles(config).find(value => value.id === settings.style) ?? config.styles[0];
  const preview = (item: CreationStyle | MyStyle, lazy = false) => {
    const src = example(item);
    if (src) return <img src={src} alt="" loading={lazy ? 'lazy' : undefined} width={256} height={256}/>;
    return <span className="studio-noexample" aria-hidden="true"><Icon name="create"/>{making.has(item.id) && <small>Exemple…</small>}</span>;
  };
  const more = [6, 8, 10, 12].filter(value => value <= config.max_count);
  const disabled = !config.configured;
  return <section className="studio" id="studio" aria-label="Images">
    <div className="studio-body">
      <button type="button" id="studio-advanced" className="studio-advanced" aria-expanded={advanced} aria-controls="studio-settings" onClick={() => setAdvanced(value => !value)}>
        <Icon name="settings"/><span>Paramètres avancés<small>{style.name} · {settings.format === 'custom' ? times(settings.size) : settings.format}{!source && settings.quality !== config.default_quality ? ` · ${config.qualities.find(item => item.id === settings.quality)?.name}` : ''} · {settings.count} image{settings.count > 1 ? 's' : ''}</small></span><Icon name="chevron"/>
      </button>
      <div className={`studio-settings${advanced ? ' open' : ''}`} id="studio-settings" ref={menus}>
        <div className="studio-style">
          <button type="button" id="studio-style" className="studio-style-button" aria-haspopup="listbox" aria-expanded={menu === 'style'} onClick={() => setMenu(value => value === 'style' ? null : 'style')}>
            {preview(style)}<span><small>Style</small>{style.name}</span><Icon name="chevron"/>
          </button>
          {menu === 'style' && <ul className="studio-styles" role="listbox" aria-label="Styles">{config.styles.map(item =>
            <li key={item.id}><button type="button" role="option" aria-selected={item.id === settings.style} title={item.words ? `Ajouté à la description : ${item.words}` : 'La description est envoyée telle quelle'}
              onClick={() => {change({style: item.id}); setMenu(null);}}>{preview(item, true)}<span>{item.name}</span></button></li>)}
            <li className="studio-styles-title" role="presentation">Mes styles</li>
            {config.my_styles.map(item => <li key={item.id} className="studio-mine">
              <button type="button" role="option" aria-selected={item.id === settings.style} title={`Ajouté à la description : ${item.words}`}
                onClick={() => {change({style: item.id}); setMenu(null);}}>{preview(item, true)}<span>{item.name}</span></button>
              <button type="button" className="studio-style-edit" aria-label={`Modifier le style ${item.name}`} title="Modifier ou supprimer"
                onClick={() => {setMenu(null); setEditing({style: item});}}><Icon name="edit"/></button></li>)}
            {config.my_styles.length < config.max_styles
              ? <li><button type="button" id="studio-new-style" className="studio-new-style" onClick={() => {setMenu(null); setEditing({style: null});}}>
                <Icon name="plus"/><span>Créer un style</span></button></li>
              : <li className="studio-styles-title" role="presentation">{config.max_styles} styles au maximum : supprimez-en un pour en créer un autre.</li>}
          </ul>}
        </div>

        <h3>Dimensions <span className="studio-help" tabIndex={0} title="Le service n’accepte que certaines tailles : chaque format prend la taille possible la plus proche. « Personnalisé » les montre toutes.">?</span></h3>
        <div className="studio-formats">
          {config.formats.map(format => {
            const [w, h] = format.size.split('x').map(Number), k = 26 / Math.max(w, h);
            return <button key={format.name} type="button" aria-pressed={settings.format === format.name} title={times(format.size)} onClick={() => change({format: format.name, size: format.size})}>
              <span className="studio-shape" style={{width: Math.round(w * k), height: Math.round(h * k)}}/>{format.name}</button>;
          })}
          <button type="button" aria-pressed={settings.format === 'custom'} onClick={() => change({format: 'custom'})}><span className="studio-shape custom"/>Personnalisé</button>
        </div>
        <div className="studio-sizes">{settings.format === 'custom'
          ? config.sizes.map(size => <button key={size} type="button" aria-pressed={size === settings.size} onClick={() => change({size})}>{times(size)}</button>)
          : <span className="studio-size">{times(settings.size)}</span>}</div>

        {config.qualities.length > 1 && <>
        <h3>Qualité <span className="studio-help" tabIndex={0} title="HD et Très HD : l’image est créée, agrandie puis repassée pour ajouter des détails (peau, tissus, feuillages…). HD : 1,5 fois plus grande, environ 3 fois plus long. Très HD : jusqu’à 2 048 pixels de côté, environ 4 fois plus long. Une image de départ garde sa taille.">?</span></h3>
        <div className="studio-counts studio-qualities" role="group" aria-label="Qualité">
          {config.qualities.map(item => <button key={item.id} type="button" id={`studio-quality-${item.id}`} aria-pressed={settings.quality === item.id} disabled={source !== null}
            title={source ? 'Une image de départ garde sa taille' : times(finalSize(settings.size, item.id))} onClick={() => change({quality: item.id})}>{item.name}</button>)}
        </div>
        {!source && settings.quality !== config.default_quality && <span className="studio-size" id="studio-final-size">Image finale : {times(finalSize(settings.size, settings.quality))}</span>}
        </>}

        <h3>Nombre d’images <span className="studio-help" tabIndex={0} title="Les images sont créées l’une après l’autre, chacune un peu différente.">?</span></h3>
        <div className="studio-counts">
          {[1, 2, 3, 4].filter(value => value <= config.max_count).map(value =>
            <button key={value} type="button" aria-pressed={settings.count === value} onClick={() => change({count: value})}>{value}</button>)}
          {more.length > 0 && <div className="studio-more">
            <button type="button" aria-label="Plus d’images" aria-pressed={settings.count > 4} aria-expanded={menu === 'count'} onClick={() => setMenu(value => value === 'count' ? null : 'count')}>
              {settings.count > 4 ? settings.count : ''}<Icon name="chevron"/></button>
            {menu === 'count' && <ul>{more.map(value => <li key={value}><button type="button" onClick={() => {change({count: value}); setMenu(null);}}>{value} images</button></li>)}</ul>}
          </div>}
        </div>

        <label className="studio-switch">
          <span>Améliorer la description <span className="studio-help" tabIndex={0} title="Activé : avant chaque création, Qwen réécrit votre idée en description détaillée (en anglais, que le modèle d’images suit mieux). Désactivé : le bouton « Améliorer » le fait à la demande, et vous pouvez retoucher le résultat.">?</span></span>
          <input type="checkbox" id="studio-improve" checked={settings.improve} onChange={event => change({improve: event.target.checked})}/><span className="studio-toggle" aria-hidden="true"/>
        </label>

        <button type="button" className="studio-reset" onClick={() => change(defaults(config))}><Icon name="retry"/>Rétablir les réglages par défaut</button>
      </div>

      <div className="studio-main">
        <form className="studio-prompt" onSubmit={create}>
          {source && <div className="studio-source" id="studio-source">
            <button type="button" className="studio-source-image" aria-label="Changer l’image de départ" title="Changer l’image de départ" onClick={() => setPicking(true)}>
              <img src={thumbnailURL(source.id)} alt=""/>{retouch && zone && <img className="studio-source-zone" src={zone.strokes} alt=""/>}</button>
            <div className="studio-source-text">
              <span>Image de départ <span className="studio-help" tabIndex={0} title={retouch
                ? 'Retoucher : seul ce que vous demandez change (retirer un objet, changer une couleur, ajouter un détail…), tout le reste de l’image est gardé. Écrivez simplement le changement : Qwen regarde l’image et en fait une consigne précise, en anglais. « Améliorer » vous la montre d’abord.'
                : 'Transformer : toute l’image est redessinée selon votre description (pour changer de style, par exemple), plus ou moins librement. Qwen regarde l’image et écrit lui-même la description complète. « Améliorer » vous la montre d’abord.'}>?</span></span>
              <div className="studio-strengths studio-modes" role="group" aria-label="Que faire de l’image de départ">
                <button type="button" id="studio-mode-retouch" aria-pressed={retouch} title="Seul ce que vous demandez change" onClick={() => change({edit: 'retouche'})}>Retoucher</button>
                <button type="button" id="studio-mode-transform" aria-pressed={!retouch} title="Toute l’image est redessinée" onClick={() => change({edit: 'transformer'})}>Transformer</button>
              </div>
              {retouch && <div className="studio-zone">
                <button type="button" id="studio-paint" className="studio-link studio-source-pick" onClick={() => setPainting(true)}>
                  <Icon name="edit"/>{zone ? 'Zone peinte : la modifier' : 'Peindre la zone à changer'}</button>
                {zone && <button type="button" className="studio-link" id="studio-zone-remove" onClick={() => setZone(null)}>Toute l’image</button>}
              </div>}
              {!retouch && <div className="studio-strengths" role="group" aria-label="Liberté prise avec l’image de départ">
                {config.strengths.map(item => <button key={item.id} type="button" aria-pressed={settings.strength === item.id}
                  title={{fidele: 'Retouche légère : l’image change peu', equilibre: 'L’image change nettement, sa composition reste', libre: 'Redessinée librement, en gardant la composition'}[item.id] ?? ''}
                  onClick={() => change({strength: item.id})}>{item.name}</button>)}
              </div>}
            </div>
            <button type="button" className="icon-button" id="studio-source-remove" aria-label="Ne plus partir de cette image" title="Ne plus partir de cette image" onClick={() => setSource(null)}><Icon name="close"/></button>
          </div>}
          <textarea id="studio-prompt" rows={3} maxLength={config.max_prompt} value={prompt}
            placeholder={!source ? 'Décrivez l’image à créer…' : retouch ? 'Dites ce qui doit changer, par exemple : retire-lui son chapeau…' : 'Dites ce que devient l’image, par exemple : en aquarelle…'} aria-label="Description de l’image"
            onChange={event => {setPrompt(event.target.value); if (!event.target.value.trim()) setBeforeImprove(null);}}
            onKeyDown={event => {if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {event.preventDefault(); event.currentTarget.form?.requestSubmit();}}}/>
          <div className="studio-actions">
            {!source && <button type="button" id="studio-source-pick" className="studio-link studio-source-pick" disabled={busy} onClick={() => setPicking(true)}>
              <Icon name="image"/>Partir d’une image</button>}
            <span className="studio-progress" role="status">{progress}</span>
            {beforeImprove !== null && <button type="button" className="studio-link" onClick={() => {setPrompt(beforeImprove); setBeforeImprove(null);}}>Revenir à mon texte</button>}
            {!settings.improve && <button type="button" id="studio-improve-now" className="studio-secondary" disabled={disabled || busy || improving || !prompt.trim()} onClick={() => {void improveNow();}}>
              <Icon name="news"/>{improving ? 'Amélioration…' : 'Améliorer'}</button>}
            {busy && <button type="button" className="studio-secondary" onClick={() => running.current?.abort()}>Arrêter</button>}
            <button type="submit" id="studio-create" className="auth-submit" disabled={disabled || busy || improving || !prompt.trim()} title="Ctrl / Cmd + Entrée">{!source ? 'Créer' : retouch ? 'Retoucher' : 'Transformer'}</button>
          </div>
        </form>
        {disabled && <p className="studio-error" role="alert">La création d’images n’est pas configurée sur ce site.</p>}
        {error && <p className="studio-error" role="alert">{error}</p>}
        {improved && <div className="studio-improved" id="studio-improved">
          <span>{retouch ? 'Consigne écrite par Qwen' : 'Description améliorée par Qwen'}</span><p>{improved}</p>
          <button type="button" className="studio-link" onClick={() => {setPrompt(improved); setImproved(null);}}>La reprendre pour la retoucher</button>
        </div>}

        {!waiting.length && !images.length ? <p className="library-empty">{library ? 'Les images que vous créez apparaîtront ici, et dans votre bibliothèque.' : 'Chargement…'}</p>
          : <ul className="studio-grid">
            {waiting.map(item => {
              const [w, h] = item.size.split('x');
              return <li key={item.key} className={`studio-waiting${item.error ? ' failed' : ''}`} style={{aspectRatio: `${w} / ${h}`}} role="status">{item.error || item.label}
                {item.error && <button type="button" className="icon-button" aria-label="Retirer" title="Retirer" onClick={() => setWaiting(list => list.filter(other => other.key !== item.key))}><Icon name="close"/></button>}</li>;
            })}
            {images.map(item => <li key={item.id} className="studio-item">
              <button type="button" className="studio-thumb" style={{aspectRatio: `${item.width} / ${item.height}`}} aria-label={`Agrandir ${item.name}`} onClick={() => onOpen(toRef(item))}>
                <img src={thumbnailURL(item.id)} alt="" loading="lazy"/>
                {item.generation && <span className="studio-caption">{item.generation.prompt}</span>}
              </button>
              <div className="studio-item-actions">
                <button type="button" className="icon-button" aria-label={`Nouvelle conversation avec ${item.name}`} title="Nouvelle conversation avec cette image" onClick={() => onStartChat(toRef(item))}><Icon name="ask"/></button>
                <button type="button" className="icon-button" aria-label={`Partir de ${item.name}`} title="Partir de cette image pour en créer une autre" onClick={() => startFrom(toRef(item))}><Icon name="image"/></button>
                <button type="button" className="icon-button" aria-label={`Reprendre les réglages de ${item.name}`} title="Reprendre la description et les réglages" onClick={() => reuse(item)}><Icon name="retry"/></button>
                <a className="icon-button" href={`${imageURL(item.id)}?download=1`} download={item.name} aria-label={`Télécharger ${item.name}`} title="Télécharger"><Icon name="download"/></a>
                <button type="button" className="icon-button library-delete" aria-label={`Supprimer ${item.name}`} title="Supprimer" onClick={() => onDelete(item.id)}><Icon name="trash"/></button>
              </div>
            </li>)}
          </ul>}
      </div>
    </div>
    <StyleDialog open={editing !== null} style={editing?.style ?? null} limits={{name: config.max_style_name, words: config.max_style_words}} api={styles}
      onSaved={saved} onDeleted={deleted} onClose={() => setEditing(null)}/>
    <MaskPainter image={painting ? source : null} zone={zone} onDone={setZone} onClose={() => setPainting(false)}/>
    <SourcePicker open={picking} library={library} removed={removed} upload={async file => {const ref = await uploadImage(file); onLoad(); return ref;}}
      onChoose={startFrom} onClose={() => setPicking(false)}/>
  </section>;
}
