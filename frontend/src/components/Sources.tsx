import {type Source, hue, siteLabel, siteName} from '../lib/sites';
import {Icon} from './Icon';

export type {Source};
export {siteName};

const MARKER = '\n\n**Sources**\n\n';

/** The answer of a web search ends with its list of cited sources, written by the server ("- [n] [Title](<url>)"):
 *  the text before it, and the numbers listed. null when the content has no such list. */
export function splitSources(content: string): {body: string; cited: number[]} | null {
  const at = content.lastIndexOf(MARKER);
  if (at < 0) return null;
  const lines = content.slice(at + MARKER.length).split('\n').filter(line => line.trim());
  if (!lines.length || !lines.every(line => /^- \[\d+\] /.test(line))) return null;
  return {body: content.slice(0, at), cited: lines.map(line => Number(line.match(/^- \[(\d+)\]/)![1]))};
}

function SiteIcon({source}: {source: Source}) {
  const site = siteLabel(source);
  return source.icone ? <img className="source-icon" src={source.icone} alt="" width={16} height={16}/>
    : <span className="source-icon source-initial" style={{background: `hsl(${hue(site)} 40% 32%)`}} aria-hidden="true">{site.charAt(0).toUpperCase()}</span>;
}

/** Cited sources, folded under a button that shows the icons of the first sites and their number; opened, a card per
 *  source: icon of the site (or its initial), site, page title and citation number. */
export function SourceList({numbers, sources}: {numbers: number[]; sources: ReadonlyMap<number, Source>}) {
  const cited = numbers.flatMap(number => {const source = sources.get(number); return source ? [[number, source] as const] : [];});
  if (!cited.length) return null;
  return <details className="sources-block">
    <summary>
      <span className="sources-stack" aria-hidden="true">{cited.slice(0, 4).map(([number, source]) => <SiteIcon key={number} source={source}/>)}</span>
      <span>{cited.length} source{cited.length > 1 ? 's' : ''}</span>
      <Icon name="chevron"/>
    </summary>
    <ol className="source-list">
      {cited.map(([number, source]) => <li key={number}><a href={source.url} target="_blank" rel="noopener noreferrer nofollow" title={source.url}>
        <SiteIcon source={source}/>
        <span className="source-text"><span className="source-site">{siteLabel(source)}</span><span className="source-title">{source.titre}</span></span>
        <span className="source-number">{number}</span>
      </a></li>)}
    </ol>
  </details>;
}
