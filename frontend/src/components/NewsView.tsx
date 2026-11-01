import {NEWS, NEWS_LEVELS, type NewsLevel} from '../lib/news';
import {Icon} from './Icon';

const day = (date: string) => new Date(`${date}T12:00:00`).toLocaleDateString('fr-FR', {day: 'numeric', month: 'long', year: 'numeric'});

function Tag({level}: {level: NewsLevel}) {
  return <span className={`news-tag ${level}`} title={NEWS_LEVELS[level].hint}>{NEWS_LEVELS[level].label}</span>;
}

/** What changed on L'Observatoire, in plain words. */
export function NewsView({onClose}: {onClose: () => void}) {
  return <section className="news" id="news" aria-label="Nouveautés">
    <header className="library-header">
      <h2>Nouveautés</h2>
      <button type="button" className="icon-button" aria-label="Fermer les nouveautés" title="Fermer" onClick={onClose}><Icon name="close"/></button>
    </header>
    <ul className="news-legend" aria-label="Signification des étiquettes">
      {(Object.keys(NEWS_LEVELS) as NewsLevel[]).map(level => <li key={level}><Tag level={level}/>{NEWS_LEVELS[level].hint}</li>)}
    </ul>
    <ol className="news-list">
      {NEWS.map(item => <li key={item.id} className="news-item">
        <div className="news-meta"><Tag level={item.level}/><time dateTime={item.date}>{day(item.date)}</time></div>
        <h3>{item.title}</h3>
        <p>{item.text}</p>
      </li>)}
    </ol>
  </section>;
}
