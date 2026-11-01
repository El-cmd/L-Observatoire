/** What changed for users, newest first. Each user-visible feature or fix adds an entry here
 * (see CLAUDE.md): plain words, no technical terms. */
export type NewsLevel = 'major' | 'improvement' | 'fix';
export type NewsItem = {id: string; date: string; level: NewsLevel; title: string; text: string};

export const NEWS_LEVELS: Record<NewsLevel, {label: string; hint: string}> = {
  major: {label: 'Nouveauté', hint: 'Une nouvelle possibilité'},
  improvement: {label: 'Amélioration', hint: 'Quelque chose qui marche mieux'},
  fix: {label: 'Correction', hint: 'Un petit souci réglé'},
};

export const NEWS: NewsItem[] = [
  {id: '2026-11-01-nouveautes', date: '2026-11-01', level: 'improvement', title: 'Cette page Nouveautés',
    text: 'Retrouvez ici tout ce qui change sur L’Observatoire. Un point apparaît à côté de « Nouveautés » quand il y a du nouveau.'},
  {id: '2026-10-31-logo-accueil', date: '2026-10-31', level: 'fix', title: 'Le logo ramène à l’accueil',
    text: 'Cliquer sur « L’Observatoire » en haut à gauche ouvre un nouveau chat.'},
  {id: '2026-10-31-menu-surligne', date: '2026-10-31', level: 'fix', title: 'Menu plus clair',
    text: 'Dans la barre de gauche, seule la page ouverte est surlignée.'},
  {id: '2026-10-31-question-image', date: '2026-10-31', level: 'improvement', title: 'Poser une question sur une image',
    text: 'Les images s’affichent en entier dans la conversation. Le bouton bulle sur une image permet de reposer une question dessus, et la Bibliothèque permet de démarrer un nouveau chat à partir d’une image ou de la télécharger.'},
  {id: '2026-10-31-images', date: '2026-10-31', level: 'major', title: 'Envoyer des images',
    text: 'Le bouton + à côté du champ de saisie permet d’envoyer jusqu’à 5 images par message : photo, capture d’écran, schéma… Vous pouvez aussi les glisser ou les coller. Qwen les regarde et répond dessus. Toutes vos images sont rangées dans la Bibliothèque.'},
  {id: '2026-10-31-titres', date: '2026-10-31', level: 'improvement', title: 'Des titres de conversation lisibles',
    text: 'Chaque conversation reçoit un titre court qui résume le sujet. Pour le changer, cliquez sur le crayon à côté du titre.'},
  {id: '2026-10-31-plusieurs-conversations', date: '2026-10-31', level: 'major', title: 'Plusieurs conversations en même temps',
    text: 'Vous pouvez lancer une question, passer à une autre conversation et en démarrer une nouvelle pendant que Qwen répond. Un point clignotant indique les réponses en cours.'},
  {id: '2026-10-31-reponses-longues', date: '2026-10-31', level: 'major', title: 'Des réponses beaucoup plus longues',
    text: 'Qwen peut écrire des réponses bien plus longues. Si une réponse est coupée, le bouton « Continuer » la fait reprendre là où elle s’est arrêtée, même après avoir rechargé la page.'},
  {id: '2026-10-31-mise-en-forme', date: '2026-10-31', level: 'improvement', title: 'Réponses mieux mises en forme',
    text: 'Titres, listes, tableaux, code et formules s’affichent proprement, avec une taille de texte plus confortable.'},
  {id: '2026-10-31-telephone', date: '2026-10-31', level: 'improvement', title: 'Plus agréable sur téléphone',
    text: 'Le champ de saisie prend moins de place et le titre d’accueil tient sur une ligne.'},
  {id: '2026-10-31-memoire', date: '2026-10-31', level: 'major', title: 'La jauge de mémoire',
    text: 'Le petit cercle près du champ de saisie montre quelle part de la mémoire de Qwen la conversation occupe. Quand elle est pleine, les anciens échanges sont résumés pour que vous puissiez continuer.'},
  {id: '2026-10-30-comptes', date: '2026-10-30', level: 'major', title: 'Votre compte personnel',
    text: 'Chacun a son compte : vos conversations sont gardées et vous les retrouvez depuis n’importe quel ordinateur ou téléphone. Le mot de passe se change depuis le menu de votre profil, en bas à gauche.'},
];

const seenKey = (user: string) => `observatoire:news-seen:${user}`;

/** The newest entry already read on this browser; storage may be unavailable. */
export function hasUnreadNews(user: string): boolean {
  try { return !!NEWS.length && localStorage.getItem(seenKey(user)) !== NEWS[0].id; } catch { return false; }
}

export function markNewsRead(user: string) {
  try { if (NEWS.length) localStorage.setItem(seenKey(user), NEWS[0].id); } catch { /* not remembered */ }
}
