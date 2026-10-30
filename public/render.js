'use strict';
(() => {
  globalThis.chatIcons = Object.freeze({
    copy: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></svg>',
    check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>'
  });
  const escape = text => String(text).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
  const codeCache = new Map();

  function renderCode(source, hint) {
    const language = hint.toLowerCase().split(/\s+/)[0];
    const key = language + '\n' + source;
    if (codeCache.has(key)) return codeCache.get(key);
    let html = escape(source), label = language || 'code';
    if (globalThis.hljs && !['text', 'plaintext', 'txt', 'output', 'console'].includes(language)) {
      try {
        const result = hljs.getLanguage(language)
          ? hljs.highlight(source, {language, ignoreIllegals: true})
          : hljs.highlightAuto(source);
        html = result.value;
        label = result.language || label;
      } catch { /* Preserve readable, escaped code if a grammar cannot be applied. */ }
    }
    const numbers = source.split('\n').map((_, i) => `<span>${i + 1}</span>`).join('');
    const result = `<pre><div class="code-header"><span>${escape(label)}</span><button type="button" class="copy-code" aria-label="Copier le code" title="Copier le code">${chatIcons.copy}</button></div><div class="code-scroll"><div class="line-numbers" aria-hidden="true">${numbers}</div><code class="hljs">${html}</code></div></pre>`;
    if (codeCache.size >= 64) codeCache.delete(codeCache.keys().next().value);
    codeCache.set(key, result);
    return result;
  }

  function renderProse(text) {
    const fragments = [];
    const prefix = 'OBSMATH' + Math.random().toString(36).slice(2).toUpperCase() + 'TOKEN';
    // Protect inline code and complete math expressions before Markdown formatting.
    // Fenced code never reaches this function. Incomplete delimiters remain readable during streaming.
    const protectedText = text.replace(/`[^`\n]+`|\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|(?<!\\)\$(?!\$)[^\n$]+?(?<!\\)\$/g, raw => {
      let html;
      if (raw.startsWith('`')) html = `<code>${escape(raw.slice(1, -1))}</code>`;
      else {
        const display = raw.startsWith('$$') || raw.startsWith('\\[');
        const width = raw.startsWith('$') && !display ? 1 : 2;
        try {
          html = katex.renderToString(raw.slice(width, -width), {
            displayMode: display, throwOnError: false, trust: false, strict: 'ignore',
            output: 'htmlAndMathml', maxExpand: 1000, maxSize: 20, errorColor: '#e6a09a'
          });
        } catch { html = escape(raw); }
      }
      return prefix + (fragments.push(html) - 1) + 'END';
    });
    const inline = value => escape(value).replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
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

  globalThis.renderMarkdown = text => String(text).split('```').map((block, index) => {
    if (!(index % 2)) return renderProse(block);
    const newline = block.indexOf('\n');
    const language = newline >= 0 ? block.slice(0, newline).trim() : '';
    const code = newline >= 0 ? block.slice(newline + 1).replace(/\n$/, '') : block;
    return renderCode(code, language);
  }).join('');
})();
