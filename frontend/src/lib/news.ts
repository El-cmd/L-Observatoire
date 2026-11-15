/** What changed for users, newest first. Each user-visible feature or fix adds an entry here
 * (see CLAUDE.md): plain words, no technical terms. */
import type {User} from '../types';

export type NewsLevel = 'major' | 'improvement' | 'fix';
/** reserve: shown only to accounts that have this right (a feature not open to everyone yet). */
export type NewsItem = {id: string; date: string; level: NewsLevel; title: string; text: string; reserve?: 'recherche_web'};

export const NEWS_LEVELS: Record<NewsLevel, {label: string; hint: string}> = {
  major: {label: 'Nouveauté', hint: 'Une nouvelle possibilité'},
  improvement: {label: 'Amélioration', hint: 'Quelque chose qui marche mieux'},
  fix: {label: 'Correction', hint: 'Un petit souci réglé'},
};

export const NEWS: NewsItem[] = [
  {id: '2026-11-15-application', date: '2026-11-15', level: 'major', title: 'L’Observatoire comme une application',
    text: 'Vous pouvez installer L’Observatoire sur votre ordinateur ou votre téléphone Android : ouvrez le menu de votre compte, en bas à gauche, et choisissez « Installer l’application ». Il s’ouvre ensuite dans sa propre fenêtre, avec son icône. Sur iPhone, touchez le bouton Partager de Safari, puis « Sur l’écran d’accueil ».'},
  {id: '2026-11-15-arret', date: '2026-11-15', level: 'fix', title: 'Arrêter une réponse, tout de suite',
    text: 'Le bouton d’arrêt coupe maintenant la réponse immédiatement : vous pouvez écrire votre message suivant sans attendre ni recharger la page.'},
  {id: '2026-11-15-sources-icones', date: '2026-11-15', level: 'improvement', title: 'Des sources plus lisibles', reserve: 'recherche_web',
    text: 'Après une recherche sur Internet, chaque citation s’affiche dans le texte avec le logo et le nom du site ; passez dessus pour voir toutes ses sources. Sous la réponse, les sources sont rassemblées en petites cartes. Cliquez pour ouvrir la page.'},
  {id: '2026-11-12-recherche-web', date: '2026-11-12', level: 'major', title: 'Chercher sur Internet', reserve: 'recherche_web',
    text: 'Le bouton Web, à gauche du champ de saisie, permet à L’Observatoire de chercher sur Internet avant de répondre : il lit les pages, puis répond en citant ses sources, [1], [2]… sur lesquelles vous pouvez cliquer. La petite flèche à côté choisit comment chercher : Automatique (L’Observatoire décide s’il faut chercher, et jusqu’où), Rapide (une recherche, environ 30 secondes), Approfondie (plusieurs sources croisées, environ une minute) ou Très approfondie (un dossier complet sur une question large ou une comparaison, quelques minutes). Le déroulé de la recherche se déplie au-dessus de la réponse. Si la réflexion est activée dans les réglages, L’Observatoire réfléchit aussi pendant la recherche : c’est plus long, parfois plus juste.'},
  {id: '2026-11-01-documents', date: '2026-11-01', level: 'major', title: 'Envoyez des documents',
    text: 'Le bouton + accepte maintenant les PDF, les documents Word (.docx) et les fichiers texte (notes, CSV, code…), en plus des images. L’Observatoire lit chaque document une fois, page par page, y compris les pages scannées et l’écriture à la main ; la lecture d’un long PDF peut prendre une minute. Le texte lu est visible en cliquant sur le document : « [?] » signale un passage incertain, à vérifier sur l’original. Excel et PowerPoint arriveront plus tard : enregistrez-les en PDF en attendant.'},
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

/** The entries this account sees: reserved ones only with the matching right. */
export function newsFor(user: User): NewsItem[] {
  return NEWS.filter(item => !item.reserve || user[item.reserve] === true);
}

/** The newest entry already read on this browser; storage may be unavailable. */
export function hasUnreadNews(user: User): boolean {
  const news = newsFor(user);
  try { return !!news.length && localStorage.getItem(seenKey(user.id)) !== news[0].id; } catch { return false; }
}

export function markNewsRead(user: User) {
  const news = newsFor(user);
  try { if (news.length) localStorage.setItem(seenKey(user.id), news[0].id); } catch { /* not remembered */ }
}
