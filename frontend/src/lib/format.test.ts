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
  it('renders a heading followed by a list without a blank line', () => {
    const result = formatProse('#### 📝 Rédaction\n- **Rédiger** des emails\n- *Corriger* le style\n  1. imbriqué');
    expect(result).toContain('<h4>📝 Rédaction</h4>');
    expect(result).toContain('<li><strong>Rédiger</strong> des emails</li>');
    expect(result).toContain('<em>Corriger</em>'); expect(result).toContain('<ol>');
  });
  it('renders italics around quotes, tables, quotes and math inside lists', () => {
    expect(formatProse('- *"Aide-moi à rédiger un email."*')).toContain('<em>&quot;Aide-moi à rédiger un email.&quot;</em>');
    expect(formatProse('| A | B |\n|---|---|\n| 1 | 2 |')).toContain('<td>2</td>');
    expect(formatProse('> citation')).toContain('<blockquote>');
    expect(formatProse('- aire : $\\pi r^2$')).toContain('class="katex"');
  });
  it('opens safe links in a new tab and drops unsafe links and images', () => {
    const link = formatProse('[doc](https://example.org)');
    expect(link).toContain('href="https://example.org"'); expect(link).toContain('rel="noopener noreferrer nofollow"');
    expect(formatProse('[x](javascript:alert(1))')).not.toContain('<a ');
    expect(formatProse('![x](https://example.org/a.png)')).not.toContain('<img');
  });
  it('highlights explicit languages and escapes untrusted code', () => {
    expect(highlightCode('const answer = 42;', 'javascript').html).toContain('hljs-keyword');
    expect(highlightCode('<img src=x onerror=alert(1)>', 'text').html).toContain('&lt;img');
    expect(highlightCode('a\n\nb', 'text').html).toBe('a\n\nb');
  });
});
