/** A source of a web search answer: page, title, icon of the site (small PNG embedded by the server) and the name
 *  the site gives itself ("GitHub Docs"), when it declares one. */
export type Source = {url: string; titre: string; icone?: string; site?: string};

export const siteName = (url: string) => {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return url; }
};

/** Name shown for a source: the site's own name, or its domain. */
export const siteLabel = (source: Source) => source.site?.trim() || siteName(source.url);

/** A steady colour per site, for the initial shown when the site has no icon. */
export function hue(text: string) {
  let value = 0;
  for (const char of text) value = (value * 31 + char.charCodeAt(0)) % 360;
  return value;
}
