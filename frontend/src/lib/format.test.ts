import {describe, expect, it} from 'vitest';
import {formatProse, highlightCode} from './format';

describe('safe message formatting', () => {
  it('renders the four LaTeX delimiters without applying Markdown to the formula', () => {
    for (const text of ['$E=mc^2$', '$$\\frac{1}{3}$$', '\\(x_1+x_2\\)', '\\[\\sqrt{x}\\]']) {
      const result = formatProse(text);
      expect(result).toContain('class="katex"'); expect(result).not.toContain('katex-error');
    }
  });
  it('escapes model HTML and blocks trusted KaTeX commands', () => {
    const result = formatProse('<img src=x onerror="alert(1)">\n\n$\\href{javascript:alert(1)}{test}$');
    expect(result).not.toContain('<img'); expect(result).not.toContain('<a ');
    expect(result).toContain('&lt;img');
  });
  it('keeps math delimiters literal inside inline code', () => {
    const result = formatProse('Du code : `$x$`.');
    expect(result).toContain('<code>$x$</code>'); expect(result).not.toContain('class="katex"');
  });
  it('highlights explicit languages and escapes untrusted code', () => {
    expect(highlightCode('const answer = 42;', 'javascript').html).toContain('hljs-keyword');
    expect(highlightCode('<img src=x onerror=alert(1)>', 'text').html).toContain('&lt;img');
    expect(highlightCode('a\n\nb', 'text').html).toBe('a\n\nb');
  });
});
