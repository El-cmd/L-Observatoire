import hljs from 'highlight.js/lib/common';
import katex from 'katex';
import MarkdownIt from 'markdown-it';
import {type Source, hue, siteLabel} from './sites';

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

const attribute = (text: string) => text.replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]!));

const safeURL = (url: string) => /^https?:\/\//i.test(url);

function siteIcon(source: Source): string {
  if (source.icone?.startsWith('data:image/png;base64,')) return `<img class="cite-icon" src="${attribute(source.icone)}" alt="" width="14" height="14">`;
  const label = siteLabel(source);
  return `<span class="cite-icon cite-initial" style="background:hsl(${hue(label)} 40% 32%)" aria-hidden="true">${escape(label.charAt(0).toUpperCase())}</span>`;
}

/** One chip for a group of citations: icon and name of the first site, "+n" for the others; on hover or focus, a
 *  small window lists every source of the group (site, page title, number), each one clickable. */
function citationChip(list: [number, Source][]): string {
  const [, first] = list[0];
  const names = list.map(([, source]) => siteLabel(source));
  const items = list.map(([number, source]) => `<a href="${attribute(source.url)}" target="_blank" rel="noopener noreferrer nofollow">`
    + `${siteIcon(source)}<span class="cite-pop-text"><span class="cite-pop-site">${escape(siteLabel(source))}</span>`
    + `<span class="cite-pop-title">${escape(source.titre)}</span></span><span class="cite-pop-number">${number}</span></a>`).join('');
  return `<span class="cite"><a class="cite-chip" href="${attribute(first.url)}" target="_blank" rel="noopener noreferrer nofollow" `
    + `aria-label="${attribute(`Source${list.length > 1 ? 's' : ''} : ${names.join(', ')}`)}">${siteIcon(first)}`
    + `<span class="cite-name">${escape(names[0])}</span>${list.length > 1 ? `<span class="cite-more">+${list.length - 1}</span>` : ''}</a>`
    + `<span class="cite-pop"><span class="cite-pop-box">${items}</span></span></span>`;
}

/** Citations of a web search answer ([1], [1][3]…) become chips with the icon and name of their site, linking to
 *  the page (only http and https pages). Tags, links and inline code are left alone, and so is a bracket glued to a
 *  word (tableau[0]). A number without a known source stays as written. */
export function linkCitations(html: string, sources: ReadonlyMap<number, Source>): string {
  if (!sources.size) return html;
  return html.split(/(<code[\s\S]*?<\/code>|<a\s[\s\S]*?<\/a>|<[^>]+>)/).map((part, index) => index % 2 ? part
    : part.replace(/(?<!\w)((?:\[\d{1,3}\])+)/g, group => {
      const numbers = [...group.matchAll(/\d+/g)].map(match => Number(match[0]));
      const known = [...new Set(numbers)].filter(number => {const source = sources.get(number); return source && safeURL(source.url);});
      if (!known.length) return group;
      const rest = numbers.filter(number => !known.includes(number)).map(number => `[${number}]`).join('');
      return citationChip(known.map(number => [number, sources.get(number)!])) + rest;
    })).join('');
}
