import hljs from 'highlight.js/lib/common';
import katex from 'katex';

const escape = (text: string) => text.replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]!));

export function highlightCode(source: string, hint: string) {
  const language = hint.toLowerCase().split(/\s+/)[0];
  if (['text', 'plaintext', 'txt', 'output', 'console'].includes(language)) return {html: escape(source), language};
  try {
    const result = hljs.getLanguage(language) ? hljs.highlight(source, {language, ignoreIllegals: true}) : hljs.highlightAuto(source);
    return {html: result.value, language: result.language || language || 'code'};
  } catch { return {html: escape(source), language: language || 'code'}; }
}

/** Every model string is escaped. Only library-generated math markup is inserted. */
export function formatProse(text: string): string {
  const fragments: string[] = [];
  const prefix = 'OBSMATH' + Math.random().toString(36).slice(2).toUpperCase() + 'TOKEN';
  const protectedText = text.replace(/`[^`\n]+`|\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|(?<!\\)\$(?!\$)[^\n$]+?(?<!\\)\$/g, raw => {
    let html: string;
    if (raw.startsWith('`')) html = `<code>${escape(raw.slice(1, -1))}</code>`;
    else {
      const display = raw.startsWith('$$') || raw.startsWith('\\[');
      const width = raw.startsWith('$') && !display ? 1 : 2;
      try {
        html = katex.renderToString(raw.slice(width, -width), {displayMode: display, throwOnError: false,
          trust: false, strict: 'ignore', output: 'htmlAndMathml', maxExpand: 1000, maxSize: 20, errorColor: '#e6a09a'});
      } catch { html = escape(raw); }
    }
    return prefix + (fragments.push(html) - 1) + 'END';
  });
  const inline = (value: string) => escape(value).replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  let html = protectedText.split(/\n\s*\n/).filter(Boolean).map(paragraph => {
    if (/^#{1,6} /.test(paragraph)) return `<h3>${inline(paragraph.replace(/^#{1,6} /, ''))}</h3>`;
    const lines = paragraph.split('\n');
    if (lines.every(line => /^[-*•] /.test(line))) return `<ul>${lines.map(line => `<li>${inline(line.slice(2))}</li>`).join('')}</ul>`;
    if (lines.every(line => /^\d+\. /.test(line))) return `<ol>${lines.map(line => `<li>${inline(line.replace(/^\d+\. /, ''))}</li>`).join('')}</ol>`;
    return `<p>${inline(paragraph)}</p>`;
  }).join('');
  fragments.forEach((fragment, index) => { html = html.split(prefix + index + 'END').join(fragment); });
  return html;
}
