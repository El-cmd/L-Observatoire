import {useEffect, useRef, useState} from 'react';
import {errorMessage} from '../lib/api';

export function PasswordDialog({open, onClose, onChange}: {open: boolean; onClose: () => void; onChange: (current: string, password: string) => Promise<void>}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [current, setCurrent] = useState(''); const [password, setPassword] = useState(''); const [confirm, setConfirm] = useState('');
  const [error, setError] = useState(''); const [pending, setPending] = useState(false);
  useEffect(() => {
    if (open) {setCurrent(''); setPassword(''); setConfirm(''); setError(''); dialog.current?.showModal();}
    else dialog.current?.close();
  }, [open]);
  return <dialog id="password-dialog" className="password-dialog" ref={dialog} onCancel={onClose} onClose={onClose}>
    <form id="password-form" onSubmit={async event => {
      event.preventDefault(); if (pending) return; setError('');
      if (password !== confirm) {setError('Les nouveaux mots de passe ne correspondent pas.'); return;}
      setPending(true);
      try {await onChange(current, password); onClose();}
      catch (error) {setError(errorMessage(error));}
      finally {setPending(false); setCurrent('');}
    }}>
      <h2>Changer mon mot de passe</h2>
      <label htmlFor="current-password">Mot de passe actuel</label><input id="current-password" type="password" autoComplete="current-password" required maxLength={256} value={current} onChange={event => setCurrent(event.target.value)}/>
      <label htmlFor="new-password">Nouveau mot de passe</label><input id="new-password" type="password" autoComplete="new-password" minLength={12} maxLength={256} required value={password} onChange={event => setPassword(event.target.value)}/>
      <label htmlFor="confirm-password">Confirmer le nouveau mot de passe</label><input id="confirm-password" type="password" autoComplete="new-password" minLength={12} maxLength={256} required value={confirm} onChange={event => setConfirm(event.target.value)}/>
      <p className="password-hint">12 caractères minimum. Toutes tes sessions seront déconnectées.</p><p id="password-error" className="auth-error" role="alert">{error}</p>
      <div className="password-actions"><button id="password-cancel" type="button" onClick={onClose}>Annuler</button><button id="password-submit" className="auth-submit" type="submit" disabled={pending}>Enregistrer</button></div>
    </form>
  </dialog>;
}
