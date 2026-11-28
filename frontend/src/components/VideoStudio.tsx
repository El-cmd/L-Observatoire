import {useEffect, useRef, useState} from 'react';
import type {AttachmentRef, Library, Orientation, Video, VideoBody, VideoConfig} from '../types';
import {imageURL, thumbnailURL} from '../lib/images';
import {errorMessage} from '../lib/api';
import {estimateSeconds, formatDuration, isOpen, orientationFor, progressOf, statusLabel} from '../lib/video';
import {notifyKey, wantsNotification} from '../hooks/useVideos';
import {Icon} from './Icon';
import {SourcePicker} from './SourcePicker';

/** Settings kept in the browser, per account. `seed`: empty for a new one each time. */
interface Settings { resolution: string; orientation: Orientation; duration: number; steps: number; smooth: boolean; seed: string; negative: string; camera: string | null }

export interface VideoApi {
  create: (body: VideoBody) => Promise<Video>;
  remove: (id: string) => Promise<void>;
  improve: (prompt: string, source: string, signal?: AbortSignal) => Promise<string>;
  export: (attachment: string, format: 'gif' | 'webp') => Promise<Blob>;
}

/** "Essai rapide": 480p, 2 s, 20 steps (about 1 min 30); "Refaire en qualité": 5 s, 40 steps, same seed. */
const QUICK = {resolution: '480p', duration: 2, steps: 20};
const QUALITY = {duration: 5, steps: 40};

function defaults(config: VideoConfig): Settings {
  return {resolution: '480p', orientation: 'portrait', duration: 5, steps: 40, smooth: false, seed: '', negative: config.default_negative, camera: null};
}

function restore(config: VideoConfig, saved: Partial<Settings> | null): Settings {
  const value = {...defaults(config), ...saved};
  if (!config.resolutions.some(item => item.id === value.resolution)) value.resolution = '480p';
  if (value.orientation !== 'paysage') value.orientation = 'portrait';
  if (!config.durations.some(item => item.seconds === value.duration)) value.duration = 5;
  if (!config.steps.includes(value.steps)) value.steps = 40;
  value.smooth = value.smooth === true;
  value.seed = /^\d{1,10}$/.test(String(value.seed ?? '')) ? String(value.seed) : '';
  if (typeof value.negative !== 'string') value.negative = config.default_negative;
  if (!config.cameras.some(item => item.id === value.camera)) value.camera = null;
  return value;
}

/** The last image of a video of the library, drawn by the browser (same site: the canvas can be read). */
async function lastFrame(url: string): Promise<Blob> {
  const video = document.createElement('video');
  video.muted = true; video.playsInline = true; video.preload = 'auto';
  const wait = (event: 'loadeddata' | 'seeked') => new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('La vidéo met trop de temps à se charger.')), 30000);
    video.addEventListener(event, () => {clearTimeout(timer); resolve();}, {once: true});
    video.addEventListener('error', () => {clearTimeout(timer); reject(new Error('La vidéo n’a pas pu être lue par ce navigateur.'));}, {once: true});
  });
  const loaded = wait('loadeddata');
  video.src = url;
  await loaded;
  const seeked = wait('seeked');
  video.currentTime = Math.max(0, video.duration - 0.05);
  await seeked;
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth; canvas.height = video.videoHeight;
  const context = canvas.getContext('2d');
  if (!context || !canvas.width) throw new Error('La dernière image n’a pas pu être prise.');
  context.drawImage(video, 0, 0);
  video.removeAttribute('src'); video.load();
  const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/png'));
  if (!blob) throw new Error('La dernière image n’a pas pu être prise.');
  return blob;
}

function save(blob: Blob, name: string) {
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob); link.download = name;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 60000);
}

const stem = (name: string) => name.replace(/\.[^.]+$/, '') || 'video';

/** Video tab: an image of the library becomes a short video, made on the AI server one at a time, then kept in
 * the library. The server keeps the queue and follows the videos: the page can be closed meanwhile. */
export function VideoStudio({userId, config, loadError, reload, api, library, onLoad, uploadImage, start, onStarted, onOpen}: {
  userId: string; config: VideoConfig | null; loadError: string; reload: () => Promise<void>; api: VideoApi;
  library: Library | null; onLoad: () => void; uploadImage: (file: File) => Promise<AttachmentRef>;
  /** An image to animate, chosen in the Images tab ("Animer"). */
  start: AttachmentRef | null; onStarted: () => void;
  onOpen: (file: AttachmentRef) => void;
}) {
  const storageKey = `observatoire-video:${userId}`;
  const [settings, setSettings] = useState<Settings | null>(null);
  const [source, setSource] = useState<AttachmentRef | null>(null);
  const [prompt, setPrompt] = useState('');
  // The user's own text, while the description comes from "Améliorer".
  const [beforeImprove, setBeforeImprove] = useState<string | null>(null);
  const [improving, setImproving] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [picking, setPicking] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [working, setWorking] = useState<string | null>(null);
  const [notify, setNotify] = useState(() => wantsNotification(userId));
  const [now, setNow] = useState(() => Date.now());
  const improveRun = useRef<AbortController | null>(null);
  // The camera movements, in a menu of the bar like "Retoucher" in the Images tab.
  const [cameraOpen, setCameraOpen] = useState(false);
  const cameraMenu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!cameraOpen) return;
    function outside(event: MouseEvent) {if (!cameraMenu.current?.contains(event.target as Node)) setCameraOpen(false);}
    function escape(event: KeyboardEvent) {if (event.key === 'Escape') setCameraOpen(false);}
    document.addEventListener('mousedown', outside); document.addEventListener('keydown', escape);
    return () => {document.removeEventListener('mousedown', outside); document.removeEventListener('keydown', escape);};
  }, [cameraOpen]);

  useEffect(() => {
    onLoad();
    return () => improveRun.current?.abort();
  }, []);
  useEffect(() => {
    if (!config || settings) return;
    let saved: Partial<Settings> | null = null;
    try { saved = JSON.parse(localStorage.getItem(storageKey) || 'null'); } catch {}
    setSettings(restore(config, saved));
  }, [config]);
  useEffect(() => {
    if (start && settings) { startFrom(start); onStarted(); }
  }, [start, settings !== null]);
  // The estimated progress moves every second while a video is being made.
  const running = config?.videos.some(video => video.status === 'running') ?? false;
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);

  function change(update: Partial<Settings>) {
    setSettings(value => {
      const next = {...value!, ...update};
      try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch {}
      return next;
    });
  }

  function startFrom(image: AttachmentRef) {
    setSource(image);
    change({orientation: orientationFor(image.width, image.height)});
    document.getElementById('video-prompt')?.focus();
  }

  async function improveNow() {
    if (!source || improving) return;
    setError(''); setImproving(true);
    const controller = new AbortController(); improveRun.current = controller;
    try {
      const text = await api.improve(prompt.trim(), source.id, controller.signal);
      setBeforeImprove(value => value ?? prompt); setPrompt(text);
    } catch (failure) { if (!(failure instanceof Error && failure.name === 'AbortError')) setError(errorMessage(failure)); }
    finally { setImproving(false); improveRun.current = null; }
  }

  async function send(body: VideoBody) {
    setError(''); setSending(true);
    try { await api.create(body); await reload(); }
    catch (failure) { setError(errorMessage(failure)); }
    finally { setSending(false); }
  }

  function launch(quick: boolean) {
    if (!settings || !source) return;
    // Text written by "Améliorer" (perhaps retouched): kept as the improved version, with the user's own text.
    const own = beforeImprove !== null ? beforeImprove.trim() : prompt.trim();
    const improved = beforeImprove !== null ? prompt.trim() : null;
    void send({source: source.id, prompt: own, improved, resolution: quick ? QUICK.resolution : settings.resolution, orientation: settings.orientation,
      duration: quick ? QUICK.duration : settings.duration, steps: quick ? QUICK.steps : settings.steps, smooth: settings.smooth,
      ...(settings.seed ? {seed: Number(settings.seed)} : {}), negative: settings.negative, camera: settings.camera});
  }

  /** The same video again (same image, texts, seed and camera), perhaps longer and with more steps. */
  function again(video: Video, quality: boolean) {
    if (!video.source || !library?.items.some(item => item.id === video.source)) {
      setError('L’image de départ de cette vidéo n’est plus dans votre bibliothèque.'); return;
    }
    const s = video.settings;
    void send({source: video.source, prompt: video.prompt, improved: video.improved, resolution: s.resolution, orientation: s.orientation,
      duration: quality ? QUALITY.duration : s.duration, steps: quality ? QUALITY.steps : s.steps, smooth: s.smooth, seed: s.seed, negative: video.negative, camera: s.camera});
  }

  function reuse(video: Video) {
    const image = library?.items.find(item => item.id === video.source);
    if (image) setSource({id: image.id, name: image.name, width: image.width, height: image.height});
    const s = video.settings;
    change({resolution: s.resolution, orientation: s.orientation, duration: s.duration, steps: s.steps, smooth: s.smooth, seed: String(s.seed), negative: video.negative, camera: s.camera});
    if (video.improved) { setPrompt(video.improved); setBeforeImprove(video.prompt); } else { setPrompt(video.prompt); setBeforeImprove(null); }
    document.getElementById('video-prompt')?.focus();
  }

  /** "Continuer la vidéo": its last image becomes the starting image of the next one. */
  async function continueFrom(video: Video, name: string) {
    if (!video.attachment) return;
    setError(''); setWorking(`${video.id}:continue`);
    try {
      const blob = await lastFrame(imageURL(video.attachment));
      const image = await uploadImage(new File([blob], `${stem(name)} - dernière image.png`, {type: 'image/png'}));
      onLoad(); startFrom(image); setPrompt(''); setBeforeImprove(null);
      document.getElementById('video-studio')?.scrollTo({top: 0, behavior: 'smooth'});
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setWorking(null); }
  }

  async function exportAs(video: Video, name: string, format: 'gif' | 'webp') {
    if (!video.attachment) return;
    setError(''); setWorking(`${video.id}:${format}`);
    try { save(await api.export(video.attachment, format), `${stem(name)}.${format}`); }
    catch (failure) { setError(errorMessage(failure)); }
    finally { setWorking(null); }
  }

  async function remove(video: Video) {
    if (video.status === 'waiting' && !confirm('Retirer cette vidéo de la file d’attente ?')) return;
    setError('');
    try { await api.remove(video.id); await reload(); }
    catch (failure) { setError(errorMessage(failure)); await reload(); }
  }

  async function toggleNotify() {
    if (notify) { try { localStorage.setItem(notifyKey(userId), '0'); } catch {} setNotify(false); return; }
    if (!('Notification' in window)) { setError('Ce navigateur ne sait pas afficher de notification.'); return; }
    const permission = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission;
    if (permission !== 'granted') { setError('Les notifications sont bloquées pour ce site dans votre navigateur.'); return; }
    try { localStorage.setItem(notifyKey(userId), '1'); } catch {}
    setNotify(true);
  }

  if (!config || !settings) return <section className="studio" id="video-studio" aria-label="Vidéo">
    {loadError ? <p className="studio-error" role="alert">{loadError}</p> : <p className="library-empty" role="status">Chargement…</p>}
  </section>;

  const resolution = config.resolutions.find(item => item.id === settings.resolution) ?? config.resolutions[0];
  const frames = (seconds: number) => config.durations.find(item => item.seconds === seconds)?.frames ?? 81;
  const estimate = estimateSeconds(frames(settings.duration), settings.steps, settings.resolution !== '480p', settings.smooth);
  const quick = estimateSeconds(frames(QUICK.duration), QUICK.steps, false, settings.smooth);
  const mine = config.videos.some(isOpen);
  const full = config.open >= config.max_total;
  const blocked = !config.configured || !source || sending || improving || mine || full;
  const why = !config.configured ? '' : mine ? 'Une vidéo à la fois par compte : attendez la fin de celle en cours.'
    : full ? 'La file des vidéos est pleine : réessayez dans quelques minutes.' : '';
  const size = settings.orientation === 'portrait' ? resolution.portrait : resolution.paysage;
  const files = new Map(library?.items.map(item => [item.id, item]) ?? []);

  return <section className="studio video-studio" id="video-studio" aria-label="Vidéo">
    <div className="studio-body">
      <button type="button" id="video-advanced" className="studio-advanced" aria-expanded={advanced} aria-controls="video-settings" onClick={() => setAdvanced(value => !value)}>
        <Icon name="settings"/><span>Paramètres avancés<small>{settings.resolution} · {settings.orientation} · {settings.duration} s · {settings.steps} étapes{settings.smooth ? ' · 32 i/s' : ''}</small></span><Icon name="chevron"/>
      </button>
      <div className={`studio-settings${advanced ? ' open' : ''}`} id="video-settings">
        <h3>Résolution <span className="studio-help" tabIndex={0} title="480p : la durée est mesurée. 720p : plus net, environ 3 fois plus long ; jamais mesuré sur le serveur, la durée annoncée est une estimation.">?</span></h3>
        <div className="studio-counts video-choices" role="group" aria-label="Résolution">
          {config.resolutions.map(item => <button key={item.id} type="button" id={`video-resolution-${item.id}`} aria-pressed={settings.resolution === item.id}
            title={item.measured ? `${item.portrait.replace('x', '×')} ou ${item.paysage.replace('x', '×')}` : 'Jamais mesuré : durée estimée'} onClick={() => change({resolution: item.id})}>
            {item.id}{!item.measured && <small>estimé</small>}</button>)}
        </div>
        <h3>Format <span className="studio-help" tabIndex={0} title="Choisi d’après l’image de départ : portrait pour une image en hauteur ou carrée, paysage pour une image en largeur. L’image est recadrée à ce format.">?</span></h3>
        <div className="studio-formats">
          {(['portrait', 'paysage'] as const).map(value => {
            const [w, h] = (value === 'portrait' ? resolution.portrait : resolution.paysage).split('x').map(Number), k = 26 / Math.max(w, h);
            return <button key={value} type="button" id={`video-orientation-${value}`} aria-pressed={settings.orientation === value} onClick={() => change({orientation: value})}>
              <span className="studio-shape" style={{width: Math.round(w * k), height: Math.round(h * k)}}/>{value === 'portrait' ? 'Portrait' : 'Paysage'}</button>;
          })}
        </div>
        <h3>Durée</h3>
        <div className="studio-counts video-choices" role="group" aria-label="Durée">
          {config.durations.map(item => <button key={item.seconds} type="button" id={`video-duration-${item.seconds}`} aria-pressed={settings.duration === item.seconds}
            title={`${item.frames} images`} onClick={() => change({duration: item.seconds})}>{item.seconds} s</button>)}
        </div>
        <h3>Étapes <span className="studio-help" tabIndex={0} title="40 : le réglage officiel, le plus net. Moins d’étapes : plus rapide, un peu moins net.">?</span></h3>
        <div className="studio-counts video-choices" role="group" aria-label="Étapes">
          {config.steps.map(value => <button key={value} type="button" id={`video-steps-${value}`} aria-pressed={settings.steps === value} onClick={() => change({steps: value})}>{value}</button>)}
        </div>
        <label className="studio-switch">
          <span>Fluidité 32 images/s <span className="studio-help" tabIndex={0} title="Une image intermédiaire est ajoutée entre chaque image : le mouvement est plus doux, pour la même durée et quelques secondes de calcul en plus.">?</span></span>
          <input type="checkbox" id="video-smooth" checked={settings.smooth} onChange={event => change({smooth: event.target.checked})}/><span className="studio-toggle" aria-hidden="true"/>
        </label>
        <h3>Graine <span className="studio-help" tabIndex={0} title="Vide : une nouvelle à chaque vidéo. La même graine avec les mêmes réglages redonne la même vidéo.">?</span></h3>
        <input id="video-seed" className="video-input" inputMode="numeric" placeholder="Au hasard" value={settings.seed} maxLength={10}
          onChange={event => change({seed: event.target.value.replace(/\D/g, '').slice(0, 10)})}/>
        <h3>À éviter <span className="studio-help" tabIndex={0} title="Ce que la vidéo ne doit pas montrer (en anglais) : flou, déformations, texte…">?</span></h3>
        <textarea id="video-negative" className="video-input" rows={3} maxLength={config.max_negative} value={settings.negative} onChange={event => change({negative: event.target.value})}/>
        <button type="button" className="studio-reset" onClick={() => change(defaults(config))}><Icon name="retry"/>Rétablir les réglages par défaut</button>
      </div>

      <div className="studio-main">
        <form className="studio-prompt" onSubmit={event => {event.preventDefault(); launch(false);}}>
          {source && <ol className="studio-strip" aria-label="Image de départ"><li>
            <button type="button" className="studio-source-image" aria-label="Changer l’image de départ" title="Changer l’image de départ" onClick={() => setPicking(true)}>
              <img src={thumbnailURL(source.id)} alt=""/></button>
            <button type="button" className="studio-thumb-remove" id="video-remove-source" aria-label="Retirer l’image de départ" title="Retirer l’image de départ" onClick={() => setSource(null)}><Icon name="close"/></button>
          </li></ol>}
          <textarea id="video-prompt" rows={3} maxLength={config.max_prompt} value={prompt} aria-label="Description du mouvement"
            placeholder={source ? 'Décrivez ce qui bouge, par exemple : elle tourne la tête et sourit, le vent agite ses cheveux… (ou laissez vide et touchez « Améliorer »)' : 'Choisissez d’abord une image de départ avec le bouton d’image ci-dessous.'}
            onChange={event => {setPrompt(event.target.value); if (!event.target.value.trim()) setBeforeImprove(null);}}
            onKeyDown={event => {if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {event.preventDefault(); event.currentTarget.form?.requestSubmit();}}}/>
          {/* Every option in one bar, like the Images tab: the image, the camera, a notification at the end, then the actions. */}
          <div className="studio-actions">
            <div className="studio-options">
              {!source && <button type="button" id="video-source-pick" className="icon-button studio-add-image" aria-label="Choisir l’image de départ" title="Choisir l’image de départ" onClick={() => setPicking(true)}><Icon name="imageAdd"/></button>}
              <div className="studio-strengths studio-modes" role="group" aria-label="Mouvement de caméra">
                <div className={`studio-retouch video-camera${settings.camera ? ' on' : ''}`} ref={cameraMenu}>
                  <button type="button" id="video-camera" aria-pressed={settings.camera !== null} aria-haspopup="menu" aria-expanded={cameraOpen}
                    title={settings.camera ? `Caméra : ${config.cameras.find(item => item.id === settings.camera)?.sentence}` : 'Mouvement de caméra : laissé au modèle'}
                    onClick={() => setCameraOpen(value => !value)}><Icon name="video"/>{settings.camera ? config.cameras.find(item => item.id === settings.camera)?.name : 'Caméra'}</button>
                  <button type="button" id="video-camera-more" className="studio-retouch-more" aria-label="Choisir le mouvement de caméra" title="Choisir le mouvement de caméra"
                    aria-haspopup="menu" aria-expanded={cameraOpen} onClick={() => setCameraOpen(value => !value)}><Icon name="chevron"/></button>
                  {cameraOpen && <div className="studio-menu video-camera-menu" role="menu" aria-label="Mouvement de caméra">
                    <button type="button" role="menuitemradio" id="video-camera-aucun" aria-checked={settings.camera === null} onClick={() => {change({camera: null}); setCameraOpen(false);}}>
                      <span><span className="web-menu-title">Libre</span><span className="web-menu-hint">Le modèle choisit, ou suit ce que dit la description.</span></span></button>
                    {config.cameras.map(item => <button key={item.id} type="button" role="menuitemradio" id={`video-camera-${item.id}`} aria-checked={settings.camera === item.id}
                      onClick={() => {change({camera: item.id}); setCameraOpen(false);}}>
                      <span><span className="web-menu-title">{item.name}</span><span className="web-menu-hint">{item.sentence}</span></span></button>)}
                  </div>}
                </div>
              </div>
              <button type="button" id="video-notify" className="icon-button studio-add-image" aria-pressed={notify} onClick={() => {void toggleNotify();}}
                aria-label={notify ? 'Ne plus me prévenir à la fin' : 'Me prévenir à la fin'}
                title={notify ? 'Prévenu à la fin : touchez pour arrêter' : 'Me prévenir à la fin : une notification quand la vidéo est prête, même si vous êtes ailleurs sur le site'}><Icon name="bell"/></button>
              <span className="studio-help" tabIndex={0} title="Choisissez une image, décrivez ce qui bouge (ou touchez « Améliorer » : Qwen regarde l’image et écrit la description), puis « Essai rapide » pour voir le mouvement en environ 1 min 30, ou « Créer la vidéo » avec vos réglages. Les vidéos se font une à la fois sur le serveur : vous pouvez fermer la page pendant ce temps.">?</span>
            </div>
            <span className="studio-progress" id="video-estimate">{source ? `≈ ${formatDuration(estimate)}${resolution.measured ? '' : ' (estimé)'}` : ''}</span>
            {beforeImprove !== null && <button type="button" className="studio-link" onClick={() => {setPrompt(beforeImprove); setBeforeImprove(null);}}>Revenir à mon texte</button>}
            <button type="button" id="video-improve" className="studio-secondary" disabled={!config.configured || !source || improving} onClick={() => {void improveNow();}}
              title="Qwen regarde l’image et écrit la description en anglais, à partir de votre idée"><Icon name="news"/>{improving ? 'Amélioration…' : 'Améliorer'}</button>
            <button type="button" id="video-quick" className="studio-secondary" disabled={blocked} onClick={() => launch(true)}
              title={`480p, 2 s, 20 étapes : environ ${formatDuration(quick)}, pour voir le mouvement avant la version soignée`}>Essai rapide</button>
            <button type="submit" id="video-create" className="auth-submit" disabled={blocked} title={`${size.replace('x', '×')}, calcul estimé : environ ${formatDuration(estimate)}${resolution.measured ? '' : ' (720p jamais mesuré)'} · Ctrl / Cmd + Entrée`}>{sending ? 'Envoi…' : 'Créer'}</button>
          </div>
        </form>
        {why && <p className="video-note" id="video-why">{why}</p>}
        {!config.configured && <p className="studio-error" role="alert">La création de vidéos n’est pas configurée sur ce site.</p>}
        {(error || loadError) && <p className="studio-error" role="alert">{error || loadError}</p>}
        {config.open > 0 && <p className="video-note" id="video-queue">{`${config.open} vidéo${config.open > 1 ? 's' : ''} dans la file du site (${config.max_total} au plus).`}</p>}
        {!config.videos.length ? <p className="library-empty">Les vidéos que vous créez apparaîtront ici, et dans votre bibliothèque. La première prend environ 1 min 30 en essai rapide, 8 min en qualité.</p>
          : <ul className="studio-grid">{config.videos.map(video => {
            const s = video.settings, [w, h] = s.size.split('x');
            const file = video.attachment ? files.get(video.attachment) : undefined;
            const name = file?.name ?? 'video.mp4';
            const done = progressOf(video, now);
            const busy = (what: string) => working === `${video.id}:${what}`;
            const canRedo = video.source !== null && (s.duration < QUALITY.duration || s.steps < QUALITY.steps);
            return <li key={video.id} className={`studio-item video-item is-${video.status}`} id={`video-${video.id}`}>
              {video.status === 'ready' && video.attachment
                ? <video className="video-player" controls loop playsInline preload="metadata" poster={`/api/video/${video.id}/thumbnail`} src={imageURL(video.attachment)} style={{aspectRatio: `${w} / ${h}`}}/>
                : <div className="video-wait" style={{aspectRatio: `${w} / ${h}`}}>
                  <img src={`/api/video/${video.id}/thumbnail`} alt=""/>
                  <div className="video-state" role={isOpen(video) ? 'status' : undefined}>
                    <span>{video.status === 'ready' ? 'Supprimée de votre bibliothèque.' : statusLabel(video, now)}</span>
                    {isOpen(video) && <span className="video-bar" aria-hidden="true"><span style={{width: `${done ?? 0}%`}} className={done === null ? 'idle' : ''}/></span>}
                  </div>
                </div>}
              <div className="video-meta">
                <p title={video.sent}>{video.prompt || video.improved || video.sent}</p>
                <small>{s.resolution} · {s.duration} s · {s.steps} étapes{s.smooth ? ' · 32 i/s' : ''} · graine {s.seed}{s.camera ? ` · caméra ${config.cameras.find(item => item.id === s.camera)?.name ?? s.camera}` : ''}
                  {video.status === 'ready' && video.started_at && video.finished_at ? ` · faite en ${formatDuration((Date.parse(video.finished_at) - Date.parse(video.started_at)) / 1000)}` : ''}</small>
                <div className="video-actions">
                  {video.status === 'ready' && video.attachment && <>
                    <a className="studio-secondary" href={`${imageURL(video.attachment)}?download=1`} download={name}><Icon name="download"/>MP4</a>
                    <button type="button" className="studio-secondary" disabled={working !== null} onClick={() => {void exportAs(video, name, 'gif');}}>{busy('gif') ? 'GIF…' : 'GIF'}</button>
                    <button type="button" className="studio-secondary" disabled={working !== null} onClick={() => {void exportAs(video, name, 'webp');}}>{busy('webp') ? 'WebP…' : 'WebP'}</button>
                    {canRedo && <button type="button" className="studio-secondary" disabled={!config.configured || sending || mine || full}
                      title="Même image, même texte, même graine : 5 s et 40 étapes" onClick={() => again(video, true)}>Refaire en qualité</button>}
                    <button type="button" className="studio-secondary" disabled={working !== null} title="La dernière image devient l’image de départ de la vidéo suivante"
                      onClick={() => {void continueFrom(video, name);}}>{busy('continue') ? 'Préparation…' : 'Continuer la vidéo'}</button>
                    {file && <button type="button" className="icon-button" aria-label={`Agrandir ${name}`} title="Agrandir" onClick={() => onOpen({id: file.id, name: file.name, width: file.width, height: file.height, kind: 'video'})}><Icon name="image"/></button>}
                  </>}
                  {(video.status === 'failed' || video.status === 'lost') && video.source && <button type="button" className="studio-secondary" disabled={sending || mine || full} onClick={() => again(video, false)}><Icon name="retry"/>Relancer</button>}
                  {!isOpen(video) && <button type="button" className="icon-button" aria-label="Reprendre les réglages" title="Reprendre l’image, la description et les réglages" onClick={() => reuse(video)}><Icon name="retry"/></button>}
                  {video.status !== 'running' && <button type="button" className="icon-button library-delete" aria-label={video.status === 'waiting' ? 'Retirer de la file' : 'Retirer de la liste'}
                    title={video.status === 'waiting' ? 'Retirer de la file d’attente' : video.status === 'ready' ? 'Retirer de la liste (la vidéo reste dans votre bibliothèque)' : 'Retirer de la liste'}
                    onClick={() => {void remove(video);}}><Icon name={video.status === 'waiting' ? 'close' : 'trash'}/></button>}
                </div>
              </div>
            </li>;
          })}</ul>}
      </div>
    </div>
    <SourcePicker open={picking} library={library} upload={async file => {const ref = await uploadImage(file); onLoad(); return ref;}}
      removed={new Set()} onChoose={startFrom} onClose={() => setPicking(false)}
      hint="L’image devient la première image de la vidéo : le mouvement part d’elle."/>
  </section>;
}
