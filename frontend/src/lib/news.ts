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
  {id: '2026-11-24-boutons-retouche', date: '2026-11-24', level: 'improvement', title: 'Retoucher : de vrais boutons',
    text: 'Sous « Retoucher », « Peindre la zone à changer » et « Ajouter une image » sont maintenant de vrais boutons. L’image de départ a sa propre croix, même quand elle est seule : touchez-la pour la retirer.'},
  {id: '2026-11-24-images-empilees', date: '2026-11-24', level: 'improvement', title: 'Plusieurs images : plus faciles à suivre',
    text: 'Quand vous retouchez avec plusieurs images, elles s’affichent l’une sous l’autre avec leur numéro (Image 1, Image 2, Image 3), et chacune a sa croix pour la retirer. Si vous retirez l’image 1, l’image 2 prend sa place.'},
  {id: '2026-11-24-plusieurs-images', date: '2026-11-24', level: 'major', title: 'Retoucher avec plusieurs images',
    text: 'Dans l’onglet Images, partez d’une image, choisissez « Retoucher » puis touchez « Ajouter une image » (deux de plus au maximum) : les images sont numérotées 1, 2 et 3. Écrivez ce que vous voulez en les désignant par leur numéro, par exemple « mets la personne de l’image 1 dans la rue de l’image 2 » ou « ajoute le chat de l’image 2 à ses pieds ». Le visage, les vêtements et le décor sont repris fidèlement. Cela marche aussi avec une zone peinte.'},
  {id: '2026-11-23-icone-image-depart', date: '2026-11-23', level: 'improvement', title: 'Partir d’une image : une simple icône',
    text: 'Dans l’onglet Images, le lien « Partir d’une image » est remplacé par une icône d’image, en haut à gauche de la zone où vous décrivez l’image. Touchez-la pour choisir une image de départ.'},
  {id: '2026-11-23-qualite-hd-retiree', date: '2026-11-23', level: 'fix', title: 'Qualité HD mise de côté',
    text: 'Le réglage « Qualité » (HD et Très HD) ajouté aujourd’hui dans l’onglet Images est retiré le temps de l’améliorer : il rendait les images moins belles (peau granuleuse, traits tremblés). Les images sont de nouveau créées en qualité standard.'},
  {id: '2026-11-23-zone-peinte', date: '2026-11-23', level: 'major', title: 'Peindre la zone à retoucher',
    text: 'En mode « Retoucher », touchez « Peindre la zone à changer » : peignez sur l’image, au doigt ou à la souris, ce qui doit changer (pinceau en trois tailles, gomme, défaire), puis validez. Seule cette zone est redessinée selon votre demande ; le reste de l’image ne bouge pas, au pixel près. Pratique pour changer un seul objet quand l’image en contient plusieurs semblables.'},
  {id: '2026-11-23-retoucher', date: '2026-11-23', level: 'major', title: 'Retoucher une image : seul ce que vous demandez change',
    text: 'Dans l’onglet Images, partez d’une image puis choisissez « Retoucher » (choisi d’office) : écrivez simplement le changement, par exemple « retire-lui son chapeau » ou « mets sa voiture en rouge », et touchez Retoucher. Le reste de l’image (visage, pose, vêtements, décor) est gardé tel quel. « Transformer » redessine toute l’image, pour changer de style par exemple, avec Fidèle, Équilibré ou Libre.'},
  {id: '2026-11-23-image-vers-image-auto', date: '2026-11-23', level: 'improvement', title: 'Image à partir d’une autre : plus besoin d’améliorer',
    text: 'Quand vous partez d’une image, écrivez simplement ce qui doit changer (par exemple « retire-lui son chapeau ») et touchez Transformer : L’Observatoire regarde l’image et écrit tout seul la description complète. Il reconnaît aussi les personnages connus (de dessin animé, de manga, de jeu vidéo…) et les nomme, pour qu’ils restent fidèles. Pour retirer un objet, choisissez plutôt Équilibré ou Libre : Fidèle change très peu l’image.'},
  {id: '2026-11-23-image-vers-image', date: '2026-11-23', level: 'major', title: 'Créer une image à partir d’une autre',
    text: 'Dans l’onglet Images, touchez « Partir d’une image » sous la description, puis choisissez une image de votre bibliothèque ou de votre appareil (ou touchez l’icône image sous une image déjà créée). Elle est redessinée selon votre description : décrivez toute l’image voulue, par exemple « le même chat, en aquarelle », ou touchez Améliorer, qui regarde l’image pour vous. Choisissez ensuite combien elle peut changer : Fidèle, Équilibré ou Libre. Les formats 2:3 et 16:9 ont aussi maintenant leurs vraies proportions.'},
  {id: '2026-11-23-images-telephone', date: '2026-11-23', level: 'improvement', title: 'L’onglet Images plus simple sur téléphone',
    text: 'Sur téléphone, la zone où décrire l’image est tout en haut. Le style, le format, le nombre d’images et l’amélioration de la description sont rangés juste en dessous, dans « Paramètres avancés » : touchez-le pour les ouvrir. Le résumé des réglages choisis reste visible sous ce titre.'},
  {id: '2026-11-23-titre-en-haut', date: '2026-11-23', level: 'improvement', title: 'Le titre de la page reste en haut',
    text: 'Dans l’onglet Images et la bibliothèque, le titre de la page est tout en haut et y reste quand vous faites défiler. Dans la bibliothèque, la place utilisée s’affiche à côté, à droite.'},
  {id: '2026-11-23-pages-epurees', date: '2026-11-23', level: 'improvement', title: 'Images et bibliothèque épurées',
    text: 'L’onglet Images et la bibliothèque n’ont plus de croix de fermeture ni de bouton de chat éphémère en haut à droite : pour revenir à une conversation, touchez Nouveau chat ou une conversation dans la barre de gauche.'},
  {id: '2026-11-23-pleine-largeur', date: '2026-11-23', level: 'improvement', title: 'Images et bibliothèque sur toute la largeur',
    text: 'Sur un ordinateur, l’onglet Images et la bibliothèque occupent maintenant toute la largeur de la fenêtre : plus d’images tiennent sur une ligne.'},
  {id: '2026-11-23-infos-image', date: '2026-11-23', level: 'improvement', title: 'Toutes les informations d’une image, à côté d’elle',
    text: 'Touchez une image pour l’agrandir : à droite (en dessous sur un téléphone), vous voyez votre description, la version améliorée par L’Observatoire et le texte exact reçu par le modèle d’images, chacun avec un bouton Copier, puis le style, la graine, la durée de création, les dimensions, le poids et la date. Cela marche dans l’onglet Images, la bibliothèque et les conversations.'},
  {id: '2026-11-22-styles-personnage', date: '2026-11-22', level: 'improvement', title: 'Des styles avec un personnage',
    text: 'Quand vous décrivez un style autour d’un personnage ou d’un univers (par exemple « Spider-Man »), « Proposer les mots » garde son nom en tête des mots, et l’image d’exemple du style le montre au lieu du renard habituel. Pour mettre à jour un style déjà créé, ouvrez-le avec le crayon, touchez de nouveau « Proposer les mots » puis Enregistrer.'},
  {id: '2026-11-22-mes-styles', date: '2026-11-22', level: 'major', title: 'Créez vos propres styles d’image',
    text: 'Dans l’onglet Images, ouvrez la liste des styles puis touchez « Créer un style », tout en bas. Donnez-lui un nom et écrivez les mots qui décrivent son rendu, ou décrivez simplement le style voulu en français et touchez « Proposer les mots » : L’Observatoire les écrit pour vous. Une image d’exemple est créée pour le reconnaître. Vos styles sont rangés sous « Mes styles », visibles par vous seul ; le crayon sur un style permet de le modifier ou de le supprimer.'},
  {id: '2026-11-22-telecharger', date: '2026-11-22', level: 'fix', title: 'Le bouton Télécharger de la bibliothèque fonctionne',
    text: 'Dans la bibliothèque et dans l’onglet Images, le bouton Télécharger (la flèche vers le bas, au survol d’un fichier) enregistre de nouveau l’image ou le document sur votre appareil. Avant, il ne se passait rien.'},
  {id: '2026-11-22-creer-des-images', date: '2026-11-22', level: 'major', title: 'Créer des images',
    text: 'Touchez Images, dans la barre de gauche, puis décrivez l’image que vous voulez et touchez Créer. Vous pouvez choisir un style (photo, aquarelle, anime, pixel art…, avec un exemple pour chacun), le format (portrait, carré, paysage) et créer jusqu’à 8 images d’un coup. Activez « Améliorer la description » pour que L’Observatoire détaille votre idée avant de créer l’image, ou touchez Améliorer pour voir et retoucher sa proposition. Les images créées vont dans votre bibliothèque : vous pouvez les télécharger ou en parler dans une conversation.'},
  {id: '2026-11-17-chat-ephemere', date: '2026-11-17', level: 'major', title: 'Le chat éphémère',
    text: 'Touchez la bulle en pointillés, en haut à droite, pour ouvrir un chat qui n’est enregistré nulle part : il n’apparaît pas dans votre historique et disparaît dès que vous le quittez ou fermez la page. La recherche sur Internet y fonctionne ; les images et documents n’y sont pas acceptés, car ils seraient gardés dans votre bibliothèque. Touchez de nouveau la bulle pour revenir à vos conversations.'},
  {id: '2026-11-15-profondeur-respectee', date: '2026-11-15', level: 'fix', title: 'La profondeur de recherche choisie est respectée',
    text: 'Quand vous choisissez Approfondie ou Très approfondie dans le menu du bouton Web, la recherche se fait toujours à ce niveau. Avant, elle pouvait parfois se faire en mode Rapide.'},
  {id: '2026-11-15-lire-une-page', date: '2026-11-15', level: 'major', title: 'Lire une page dont vous donnez le lien',
    text: 'Activez le bouton Web, collez l’adresse d’une page dans votre message et demandez, par exemple, « résume cette page » ou « que dit cet article sur les délais ? ». L’Observatoire lit la page puis vous répond en la citant ; elle apparaît dans les sources sous la réponse.'},
  {id: '2026-11-15-recherche-plus-rapide', date: '2026-11-15', level: 'improvement', title: 'Une recherche sur Internet plus rapide',
    text: 'L’Observatoire lit maintenant la plupart des pages bien plus vite : une recherche avec le bouton Web prend moins de temps, surtout en mode Approfondie ou Très approfondie.'},
  {id: '2026-11-15-recherche-web-pour-tous', date: '2026-11-15', level: 'major', title: 'Chercher sur Internet',
    text: 'L’Observatoire peut maintenant chercher sur Internet pour vous répondre. Touchez le bouton Web, à côté de la zone de message, puis choisissez : Automatique (il décide seul), Rapide, Approfondie ou Très approfondie. La réponse cite ses sources : touchez une citation pour ouvrir la page. Si quelqu’un d’autre cherche au même moment, votre recherche attend son tour quelques instants.'},
  {id: '2026-11-15-tableaux-telephone', date: '2026-11-15', level: 'improvement', title: 'Des tableaux lisibles sur téléphone',
    text: 'Sur un petit écran, les tableaux ne coupent plus les mots lettre par lettre : faites glisser le tableau sur le côté pour voir toutes ses colonnes, la première reste affichée.'},
  {id: '2026-11-15-sources-repliees', date: '2026-11-15', level: 'improvement', title: 'Sources repliées', reserve: 'recherche_web',
    text: 'Sous une réponse trouvée sur Internet, les sources sont rangées derrière un petit bouton avec les logos des sites. Touchez-le pour les afficher.'},
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
