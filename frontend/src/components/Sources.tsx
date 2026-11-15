export type Source = {url: string; titre: string; icone?: string};

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

export const siteName = (url: string) => {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return url; }
};

/** A steady colour per site, for the initial shown when the site has no icon. */
function hue(text: string) {
  let value = 0;
  for (const char of text) value = (value * 31 + char.charCodeAt(0)) % 360;
  return value;
}

/** Cited sources as cards: icon of the site (or its initial), site, page title and citation number. */
export function SourceList({numbers, sources}: {numbers: number[]; sources: ReadonlyMap<number, Source>}) {
  return <div className="sources-block">
    <div className="sources-heading">Sources</div>
    <ol className="source-list">
      {numbers.map(number => {
        const source = sources.get(number);
        if (!source) return null;
        const site = siteName(source.url);
        return <li key={number}><a href={source.url} target="_blank" rel="noopener noreferrer nofollow" title={source.url}>
          {source.icone ? <img className="source-icon" src={source.icone} alt="" width={16} height={16}/>
            : <span className="source-icon source-initial" style={{background: `hsl(${hue(site)} 40% 32%)`}} aria-hidden="true">{site.charAt(0).toUpperCase()}</span>}
          <span className="source-text"><span className="source-site">{site}</span><span className="source-title">{source.titre}</span></span>
          <span className="source-number">{number}</span>
        </a></li>;
      })}
    </ol>
  </div>;
}
