import {useSyncExternalStore} from 'react';

/** Install prompt offered by Chrome and Edge (Android, computer) once the site meets the conditions of an installable
 *  application: manifest, icons and service worker. Not offered by Safari, nor when the application is already
 *  installed. */
type InstallPrompt = Event & {prompt: () => Promise<void>; userChoice: Promise<{outcome: 'accepted' | 'dismissed'}>};

let pending: InstallPrompt | null = null;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach(listener => listener());

/** Registers the service worker (production only: in development it would serve stale pages) and keeps the install
 *  prompt, which arrives before React shows the sidebar. Called once, before the first render. */
export function startInstall() {
  if (import.meta.env.PROD && 'serviceWorker' in navigator) {
    window.addEventListener('load', () => {navigator.serviceWorker.register('/sw.js').catch(() => undefined);});
  }
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault(); // the menu of the account offers it instead of a banner over the conversation
    pending = event as InstallPrompt;
    notify();
  });
  window.addEventListener('appinstalled', () => {pending = null; notify();});
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {listeners.delete(listener);};
}

/** True while the browser offers to install the application. */
export function useInstallPrompt(): boolean {
  return useSyncExternalStore(subscribe, () => pending !== null, () => false);
}

/** Shows the browser's install window. A prompt can be shown only once: the next one comes with a new event. */
export async function install() {
  const prompt = pending;
  if (!prompt) return;
  pending = null;
  notify();
  await prompt.prompt().catch(() => undefined);
}
