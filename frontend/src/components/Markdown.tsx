import {memo, useMemo} from 'react';
import {formatProse, highlightCode} from '../lib/format';
import {CopyButton} from './CopyButton';

const CodeBlock = memo(function CodeBlock({source, language, onError}: {source: string; language: string; onError: (message: string) => void}) {
  const result = useMemo(() => highlightCode(source, language), [source, language]);
  return <pre><div className="code-header"><span>{result.language}</span><CopyButton text={source} label="Copier le code" className="copy-code" onError={onError}/></div>
    <div className="code-scroll"><div className="line-numbers" aria-hidden="true">{source.split('\n').map((_, index) => <span key={index}>{index + 1}</span>)}</div>
      <code className="hljs" dangerouslySetInnerHTML={{__html: result.html}}/>
    </div>
  </pre>;
});

const Prose = memo(function Prose({text}: {text: string}) {
  const html = useMemo(() => formatProse(text), [text]);
  return <div className="prose" dangerouslySetInnerHTML={{__html: html}}/>;
});

export const Markdown = memo(function Markdown({content, onError}: {content: string; onError: (message: string) => void}) {
  return <>{content.split('```').map((block, index) => {
    if (!(index % 2)) return <Prose key={index} text={block}/>;
    const newline = block.indexOf('\n');
    const language = newline >= 0 ? block.slice(0, newline).trim() : '';
    const code = newline >= 0 ? block.slice(newline + 1).replace(/\n$/, '') : block;
    return <CodeBlock key={index} source={code} language={language} onError={onError}/>;
  })}</>;
});
