import {useEffect, useRef, useState} from 'react';
import type {AttachmentRef} from '../types';
import {imageURL} from '../lib/images';
import {Icon} from './Icon';

/** The painted zone: the mask sent to the image model (PNG, white where the image may change) and
 * the strokes as drawn, to show them on the thumbnail and to paint again from them. */
export interface Zone { mask: string; strokes: string }

/** Side of the mask at most: the image service resizes it to the image anyway. */
const MAX_SIDE = 1024;
const SIZES = [{name: 'Petit', share: 0.02}, {name: 'Moyen', share: 0.045}, {name: 'Grand', share: 0.09}];

/** "Retoucher" a zone only: the user paints over the starting image what may change; the rest is kept. */
export function MaskPainter({image, zone, onDone, onClose}: {
  image: AttachmentRef | null; zone: Zone | null; onDone: (zone: Zone | null) => void; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const last = useRef<{x: number; y: number} | null>(null);
  const history = useRef<ImageData[]>([]);
  const [size, setSize] = useState(1);
  const [erase, setErase] = useState(false);
  const [painted, setPainted] = useState(false);
  const [steps, setSteps] = useState(0);
  const scale = image ? Math.min(1, MAX_SIDE / Math.max(image.width, image.height)) : 1;
  const width = image ? Math.max(8, Math.round(image.width * scale)) : 8, height = image ? Math.max(8, Math.round(image.height * scale)) : 8;

  useEffect(() => {
    const element = dialog.current; if (!element) return;
    if (image && !element.open) {
      element.showModal(); history.current = []; setSteps(0); setErase(false);
      const context = canvas.current?.getContext('2d');
      if (!context) return;
      context.clearRect(0, 0, width, height);
      setPainted(false);
      if (zone) {
        const previous = new Image();
        previous.onload = () => {context.drawImage(previous, 0, 0, width, height); setPainted(true);};
        previous.src = zone.strokes;
      }
    }
    if (!image && element.open) element.close();
  }, [image]);

  const point = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    return {x: (event.clientX - box.left) / box.width * width, y: (event.clientY - box.top) / box.height * height};
  };
  function stroke(from: {x: number; y: number}, to: {x: number; y: number}) {
    const context = canvas.current!.getContext('2d')!;
    context.globalCompositeOperation = erase ? 'destination-out' : 'source-over';
    context.strokeStyle = context.fillStyle = '#ff3b3b';
    context.lineCap = context.lineJoin = 'round';
    context.lineWidth = SIZES[size].share * Math.max(width, height) * 2;
    context.beginPath(); context.moveTo(from.x, from.y); context.lineTo(to.x, to.y); context.stroke();
  }
  function down(event: React.PointerEvent<HTMLCanvasElement>) {
    event.currentTarget.setPointerCapture(event.pointerId);
    const context = canvas.current!.getContext('2d')!;
    history.current = [...history.current.slice(-19), context.getImageData(0, 0, width, height)]; setSteps(history.current.length);
    last.current = point(event); stroke(last.current, last.current);
    if (!erase) setPainted(true);
  }
  function move(event: React.PointerEvent<HTMLCanvasElement>) {
    if (!last.current) return;
    const next = point(event); stroke(last.current, next); last.current = next;
  }
  function up() {
    if (!last.current) return;
    last.current = null;
    if (erase) setPainted(hasPaint());
  }
  function hasPaint() {
    const data = canvas.current!.getContext('2d')!.getImageData(0, 0, width, height).data;
    for (let i = 3; i < data.length; i += 4) if (data[i] > 127) return true;
    return false;
  }
  function undo() {
    const previous = history.current.pop(); setSteps(history.current.length);
    if (previous) { canvas.current!.getContext('2d')!.putImageData(previous, 0, 0); setPainted(hasPaint()); }
  }
  function clear() {
    const context = canvas.current!.getContext('2d')!;
    history.current = [...history.current.slice(-19), context.getImageData(0, 0, width, height)]; setSteps(history.current.length);
    context.clearRect(0, 0, width, height); setPainted(false);
  }
  function done() {
    if (!painted) { onDone(null); onClose(); return; }
    const source = canvas.current!.getContext('2d')!.getImageData(0, 0, width, height);
    const out = document.createElement('canvas'); out.width = width; out.height = height;
    const context = out.getContext('2d')!;
    const mask = context.createImageData(width, height);
    for (let i = 0; i < source.data.length; i += 4) {
      const value = source.data[i + 3] > 127 ? 255 : 0;
      mask.data[i] = mask.data[i + 1] = mask.data[i + 2] = value; mask.data[i + 3] = 255;
    }
    context.putImageData(mask, 0, 0);
    onDone({mask: out.toDataURL('image/png'), strokes: canvas.current!.toDataURL('image/png')}); onClose();
  }

  return <dialog ref={dialog} id="mask-painter" className="mask-painter" aria-labelledby="mask-painter-title" onCancel={onClose} onClose={onClose}>
    {image && <>
      <header className="mask-painter-head">
        <h2 id="mask-painter-title">Peindre la zone à changer</h2>
        <button type="button" className="icon-button" aria-label="Fermer" title="Fermer" onClick={onClose}><Icon name="close"/></button>
      </header>
      <p className="password-hint">Peignez ce qui doit changer : seule cette zone est redessinée, le reste de l’image ne bouge pas. Débordez un peu autour de l’objet.</p>
      <div className="mask-painter-tools" role="toolbar" aria-label="Outils">
        <div className="studio-strengths" role="group" aria-label="Outil">
          <button type="button" id="mask-brush" aria-pressed={!erase} onClick={() => setErase(false)}>Pinceau</button>
          <button type="button" id="mask-eraser" aria-pressed={erase} onClick={() => setErase(true)}>Gomme</button>
        </div>
        <div className="studio-strengths" role="group" aria-label="Taille">
          {SIZES.map((item, index) => <button key={item.name} type="button" aria-pressed={size === index} title={`Taille : ${item.name.toLowerCase()}`} onClick={() => setSize(index)}>
            <span className="mask-dot" style={{width: 6 + index * 5, height: 6 + index * 5}} aria-hidden="true"/>{item.name}</button>)}
        </div>
        <button type="button" className="studio-link" disabled={!steps} onClick={undo}>Défaire</button>
        <button type="button" className="studio-link" disabled={!painted} onClick={clear}>Tout effacer</button>
      </div>
      <div className="mask-painter-stage" style={{aspectRatio: `${width} / ${height}`, width: `min(100%, calc(min(66dvh, 720px) * ${(width / height).toFixed(4)}))`}}>
        <img src={imageURL(image.id)} alt="" draggable={false}/>
        <canvas ref={canvas} id="mask-canvas" width={width} height={height} className={erase ? 'erasing' : ''}
          onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} aria-label="Zone à peindre sur l’image"/>
      </div>
      <div className="password-actions">
        <button type="button" onClick={onClose}>Annuler</button>
        <button type="button" id="mask-done" className="auth-submit" onClick={done}>{painted ? 'Valider la zone' : zone ? 'Retirer la zone' : 'Fermer'}</button>
      </div>
    </>}
  </dialog>;
}
