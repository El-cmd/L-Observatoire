export class APIError extends Error {
  constructor(message: string, public status: number) { super(message); this.name = 'APIError'; }
}

type Options = { method?: string; body?: unknown; signal?: AbortSignal };

/** The session lives in its HttpOnly cookie; the CSRF token exists only in memory. */
export class APIClient {
  private csrf = '';
  setCSRF(token: string) { this.csrf = token; }

  async response(path: string, options: Options = {}): Promise<Response> {
    const method = options.method ?? 'GET';
    const headers: Record<string, string> = {};
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (!['GET', 'HEAD'].includes(method) && this.csrf) headers['X-CSRF-Token'] = this.csrf;
    let response: Response;
    try {
      response = await fetch(path, {method, headers, credentials: 'same-origin', signal: options.signal,
        body: options.body === undefined ? undefined : JSON.stringify(options.body)});
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') throw error;
      throw new APIError('Impossible de joindre le serveur.', 0);
    }
    if (!response.ok) {
      const detail = await response.json().catch(() => ({})) as {error?: string};
      throw new APIError(detail.error || `Erreur HTTP ${response.status}`, response.status);
    }
    return response;
  }

  async json<T>(path: string, options: Options = {}): Promise<T> {
    const response = await this.response(path, options);
    return response.status === 204 ? undefined as T : response.json() as Promise<T>;
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Une erreur inattendue est survenue.';
}
