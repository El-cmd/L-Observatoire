import {useState} from 'react';

export function Login({initializing, pending, error, onLogin}: {
  initializing: boolean; pending: boolean; error: string; onLogin: (username: string, password: string) => Promise<void>;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  return <section id="auth-screen" className="auth-screen" aria-label="Connexion"><div className="auth-card">
    <h1>L’Observatoire</h1>
    <p id="auth-loading" role="status" hidden={!initializing}>Vérification de la session…</p>
    <form id="login-form" hidden={initializing} onSubmit={async event => {
      event.preventDefault(); if (pending) return;
      await onLogin(username, password); setPassword('');
    }}>
      <label htmlFor="login-username">Identifiant</label><input id="login-username" name="username" autoComplete="username" maxLength={64} required value={username} onChange={event => setUsername(event.target.value)}/>
      <label htmlFor="login-password">Mot de passe</label><input id="login-password" name="password" type="password" autoComplete="current-password" maxLength={256} required value={password} onChange={event => setPassword(event.target.value)}/>
      <p id="login-error" className="auth-error" role="alert">{error}</p>
      <button id="login-submit" className="auth-submit" type="submit" disabled={pending}>Se connecter</button>
    </form>
  </div></section>;
}
