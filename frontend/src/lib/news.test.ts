import {describe, expect, it} from 'vitest';
import {NEWS, NEWS_LEVELS} from './news';

describe('news', () => {
  it('lists valid, unique entries from newest to oldest', () => {
    expect(new Set(NEWS.map(item => item.id)).size).toBe(NEWS.length);
    for (const [index, item] of NEWS.entries()) {
      expect(item.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(Number.isNaN(Date.parse(item.date))).toBe(false);
      expect(NEWS_LEVELS[item.level]).toBeDefined();
      expect(item.title.trim()).not.toBe(''); expect(item.text.trim()).not.toBe('');
      if (index) expect(item.date <= NEWS[index - 1].date).toBe(true);
    }
  });
});
