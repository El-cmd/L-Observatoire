import hljs from 'highlight.js/lib/common';
import katex from 'katex';
import MarkdownIt from 'markdown-it';

const escape = (text: string) => text.replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]!));

// Model HTML stays escaped (html: false) and javascript: links are refused by markdown-it.
// Images are off (the CSP only allows same-origin ones), and so are indented code blocks:
// fenced code is split out before this renderer, indentation in answers is rarely code.
const markdown = new MarkdownIt({html: false, linkify: true, breaks: true}).disable(['image', 'code']);
markdown.renderer.rules.link_open = (tokens, index, options, _env, self) => {
  tokens[index].attrSet('target', '_blank');
  tokens[index].attrSet('rel', 'noopener noreferrer nofollow');
  return self.renderToken(tokens, index, options);
};

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
  let html = markdown.render(protectedText);
  fragments.forEach((fragment, index) => { html = html.split(prefix + index + 'END').join(fragment); });
  return html;
}
