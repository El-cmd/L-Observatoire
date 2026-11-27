/** Video tab: estimates and labels, the same rules as the server (backend/src/video.rs). */
import type {Orientation, Video} from '../types';

/** Seconds of computation on the AI server, from the measures of 27/11/2026 in 480p (491 s for 5 s and 40 steps,
 * 91 s for 2 s and 20 steps); 720p: about 3 times longer, never measured. */
export function estimateSeconds(frames: number, steps: number, hd: boolean, smooth: boolean): number {
  const seconds = (0.155 * frames * steps - 11) * (hd ? 3 : 1) * (smooth ? 1.03 : 1);
  return Math.max(30, Math.round(seconds));
}

/** Portrait for an upright or square image, landscape for a wide one. */
export const orientationFor = (width: number, height: number): Orientation => width > height ? 'paysage' : 'portrait';

/** « 45 s », « 1 min 30 s », « 8 min », « 1 h 05 ». */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} s`;
  if (total < 3600) { const minutes = Math.floor(total / 60), rest = total % 60; return rest ? `${minutes} min ${String(rest).padStart(2, '0')} s` : `${minutes} min`; }
  const hours = Math.floor(total / 3600), minutes = Math.round((total % 3600) / 60);
  return `${hours} h ${String(minutes).padStart(2, '0')}`;
}

/** Estimated share done (0 to 99) of a video being computed, from when the AI server started it. */
export function progressOf(video: Video, now: number): number | null {
  if (video.status !== 'running' || !video.started_at) return null;
  const elapsed = (now - Date.parse(video.started_at)) / 1000;
  return Math.max(0, Math.min(99, Math.floor(elapsed / video.settings.estimate_seconds * 100)));
}

/** Where a video stands, in plain words. */
export function statusLabel(video: Video, now: number): string {
  switch (video.status) {
    case 'waiting':
      return video.position > 0 ? `En file d’attente : ${video.position} vidéo${video.position > 1 ? 's' : ''} avant la vôtre` : 'Envoi au serveur IA…';
    case 'running': {
      const done = progressOf(video, now);
      if (done === null) return 'Envoyée : en attente de son tour sur le serveur IA';
      const left = video.settings.estimate_seconds - (now - Date.parse(video.started_at!)) / 1000;
      return left > 0 ? `Création… environ ${done} % (encore ${formatDuration(left)} environ)` : 'Création… presque finie';
    }
    case 'ready': return 'Prête, rangée dans votre bibliothèque';
    case 'lost': return video.error || 'Vidéo perdue par le serveur IA.';
    default: return video.error || 'La vidéo n’a pas pu être créée.';
  }
}

export const isOpen = (video: Video) => video.status === 'waiting' || video.status === 'running';
