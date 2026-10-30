import {useEffect, useRef, useState} from 'react';
import {Icon} from './Icon';

export function CopyButton({text, label, className = 'message-action copy-response', onError}: {
  text: string; label: string; className?: string; onError: (message: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {setCopied(false); return () => clearTimeout(timer.current);}, [text]);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text); clearTimeout(timer.current); setCopied(true);
      timer.current = setTimeout(() => setCopied(false), 1800);
    } catch { onError('La copie nécessite un navigateur autorisant le presse-papiers. Tu peux sélectionner le texte directement.'); }
  }
  return <button type="button" className={className} aria-label={copied ? 'Copié !' : label} title={copied ? 'Copié !' : label} onClick={copy}>
    <Icon name={copied ? 'check' : 'copy'}/>
  </button>;
}
