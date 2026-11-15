import {memo, useMemo} from 'react';
import {formatProse, highlightCode, linkCitations} from '../lib/format';
import type {Source} from '../lib/sites';
import {CopyButton} from './CopyButton';

const CodeBlock = memo(function CodeBlock({source, language, onError}: {source: string; language: string; onError: (message: string) => void}) {
  const result = useMemo(() => highlightCode(source, language), [source, language]);
  return <pre><div className="code-header"><span>{result.language}</span><CopyButton text={source} label="Copier le code" className="copy-code" onError={onError}/></div>
    <div className="code-scroll"><div className="line-numbers" aria-hidden="true">{source.split('\n').map((_, index) => <span key={index}>{index + 1}</span>)}</div>
      <code className="hljs" dangerouslySetInnerHTML={{__html: result.html}}/>
    </div>
  </pre>;
});

type Sources = ReadonlyMap<number, Source>;
const NONE: Sources = new Map();

const Prose = memo(function Prose({text, sources}: {text: string; sources: Sources}) {
  const html = useMemo(() => linkCitations(formatProse(text), sources), [text, sources]);
  return <div className="prose" dangerouslySetInnerHTML={{__html: html}}/>;
});

/** sources: those of a web search, to make its citations [n] clickable. */
export const Markdown = memo(function Markdown({content, onError, sources = NONE}: {content: string; onError: (message: string) => void; sources?: Sources}) {
  return <>{content.split('```').map((block, index) => {
    if (!(index % 2)) return <Prose key={index} text={block} sources={sources}/>;
    const newline = block.indexOf('\n');
    const language = newline >= 0 ? block.slice(0, newline).trim() : '';
    const code = newline >= 0 ? block.slice(newline + 1).replace(/\n$/, '') : block;
    return <CodeBlock key={index} source={code} language={language} onError={onError}/>;
  })}</>;
});
