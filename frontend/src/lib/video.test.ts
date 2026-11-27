import {describe, expect, it} from 'vitest';
import {estimateSeconds, formatDuration, orientationFor, progressOf, statusLabel} from './video';
import type {Video} from '../types';

const video = (over: Partial<Video>): Video => ({
  id: 'v', status: 'waiting', service_status: null, prompt: 'p', improved: null, sent: 'p', negative: '', source: null, attachment: null, error: null,
  created_at: '2026-11-27T10:00:00Z', submitted_at: null, started_at: null, finished_at: null, position: 0,
  settings: {resolution: '480p', orientation: 'portrait', size: '480x832', duration: 2, frames: 33, steps: 20, smooth: false, fps: 16, seed: 1, camera: null, estimate_seconds: 100},
  ...over,
});

describe('video', () => {
  it('estimates like the server, from the measures', () => {
    expect(estimateSeconds(81, 40, false, false)).toBe(491);
    expect(estimateSeconds(33, 20, false, false)).toBe(91);
    expect(estimateSeconds(33, 20, false, true)).toBe(94);
    expect(estimateSeconds(81, 40, true, false)).toBe(1474);
    expect(estimateSeconds(1, 1, false, false)).toBe(30);
  });
  it('chooses the orientation from the image', () => {
    expect(orientationFor(1376, 768)).toBe('paysage');
    expect(orientationFor(832, 1248)).toBe('portrait');
    expect(orientationFor(1024, 1024)).toBe('portrait');
  });
  it('writes durations in plain words', () => {
    expect(formatDuration(45)).toBe('45 s');
    expect(formatDuration(91)).toBe('1 min 31 s');
    expect(formatDuration(480)).toBe('8 min');
    expect(formatDuration(3900)).toBe('1 h 05');
  });
  it('follows a video from the queue to the library', () => {
    const now = Date.parse('2026-11-27T10:01:40Z');
    expect(statusLabel(video({position: 1}), now)).toBe('En file d’attente : 1 vidéo avant la vôtre');
    expect(statusLabel(video({position: 0}), now)).toBe('Envoi au serveur IA…');
    expect(statusLabel(video({status: 'running', service_status: 'queued'}), now)).toMatch(/en attente de son tour/);
    const running = video({status: 'running', service_status: 'in_progress', started_at: '2026-11-27T10:00:50Z'});
    expect(progressOf(running, now)).toBe(50);
    expect(statusLabel(running, now)).toBe('Création… environ 50 % (encore 50 s environ)');
    expect(progressOf(video({status: 'running', started_at: '2026-11-27T09:00:00Z'}), now)).toBe(99);
    expect(statusLabel(video({status: 'running', started_at: '2026-11-27T09:00:00Z'}), now)).toBe('Création… presque finie');
    expect(statusLabel(video({status: 'lost', error: 'Perdue.'}), now)).toBe('Perdue.');
    expect(statusLabel(video({status: 'ready'}), now)).toMatch(/bibliothèque/);
  });
});
