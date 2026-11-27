import {useEffect, useRef, useState} from 'react';
import type {Video, VideoConfig} from '../types';
import {isOpen} from '../lib/video';
import {errorMessage} from '../lib/api';

/** How often the page reads where the videos stand (the server follows them on its own). */
const EVERY = 5000;
const TITLE = 'L’Observatoire';

export const notifyKey = (userId: string) => `observatoire-video-notify:${userId}`;

export function wantsNotification(userId: string): boolean {
  try { return localStorage.getItem(notifyKey(userId)) === '1' && 'Notification' in window && Notification.permission === 'granted'; }
  catch { return false; }
}

/** Tells that a video is finished: in the title of the tab while the page is hidden, and by a notification if
 * the user asked for one. */
function announce(video: Video, userId: string) {
  const ready = video.status === 'ready';
  const text = ready ? 'Votre vidéo est prête, dans votre bibliothèque.' : 'Votre vidéo n’a pas pu être créée.';
  if (document.hidden) {
    document.title = `${ready ? '✓ Vidéo prête' : '✗ Vidéo non créée'} · ${TITLE}`;
    const back = () => { if (!document.hidden) { document.title = TITLE; document.removeEventListener('visibilitychange', back); } };
    document.addEventListener('visibilitychange', back);
  }
  if (!wantsNotification(userId)) return;
  const options = {body: text, icon: '/icons/icon-192.png', tag: `video-${video.id}`};
  // On a phone, only the service worker of the installed application may show a notification.
  void navigator.serviceWorker?.getRegistration().then(registration => {
    if (registration) return registration.showNotification('L’Observatoire', options);
    new Notification('L’Observatoire', options);
  }).catch(() => { try { new Notification('L’Observatoire', options); } catch {} });
}

/** The videos of the account, read again every few seconds while one is waiting or being made, wherever the user
 * is in the site: the end is announced even from a conversation. */
export function useVideos(api: {config: () => Promise<VideoConfig>}, userId: string | undefined, onFinished: () => void) {
  const [config, setConfig] = useState<VideoConfig | null>(null);
  const [error, setError] = useState('');
  const seen = useRef(new Map<string, Video['status']>());
  const finished = useRef(onFinished); finished.current = onFinished;
  const account = useRef(userId); account.current = userId;

  async function load() {
    const user = account.current;
    if (!user) return;
    try {
      const value = await api.config();
      if (account.current !== user) return;
      let done = false;
      for (const video of value.videos) {
        const before = seen.current.get(video.id);
        if (before && (before === 'waiting' || before === 'running') && !isOpen(video)) { announce(video, user); done = true; }
        seen.current.set(video.id, video.status);
      }
      setConfig(value); setError('');
      if (done) finished.current();
    } catch (failure) { if (account.current === user) setError(errorMessage(failure)); }
  }

  useEffect(() => { seen.current = new Map(); setConfig(null); setError(''); if (userId) void load(); }, [userId]);
  const following = config?.videos.some(isOpen) ?? false;
  useEffect(() => {
    if (!following) return;
    const timer = setInterval(() => { void load(); }, EVERY);
    return () => clearInterval(timer);
  }, [following, userId]);
  return {config, error, reload: load, setConfig};
}
