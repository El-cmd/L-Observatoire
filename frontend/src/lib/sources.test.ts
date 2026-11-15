import {describe, expect, it} from 'vitest';
import {siteName, splitSources} from '../components/Sources';

describe('sources of a web search answer', () => {
  it('separates the answer from the list written by the server', () => {
    const content = 'Réponse [1][3].\n\n**Sources**\n\n- [1] [Doc Rust](<https://doc.rust-lang.org/x>)\n- [3] [Blog](<https://blog.fr/a (b)>)';
    expect(splitSources(content)).toEqual({body: 'Réponse [1][3].', cited: [1, 3]});
  });
  it('leaves any other text alone', () => {
    expect(splitSources('Pas de sources.')).toBeNull();
    expect(splitSources('Texte.\n\n**Sources**\n\nUne phrase libre de Qwen.')).toBeNull();
  });
  it('names the site without www', () => {
    expect(siteName('https://www.france24.com/fr/x')).toBe('france24.com');
    expect(siteName('pas une adresse')).toBe('pas une adresse');
  });
});
