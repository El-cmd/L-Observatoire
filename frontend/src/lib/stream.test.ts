import {describe, expect, it} from 'vitest';
import {consumeCompletion} from './stream';

function response(text: string, chunkSize = 1) {
  const bytes = new TextEncoder().encode(text);
  return new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      for (let i = 0; i < bytes.length; i += chunkSize) controller.enqueue(bytes.slice(i, i + chunkSize));
      controller.close();
    },
  }));
}
describe('Qwen streaming', () => {
  it('preserves UTF-8 and CRLF boundaries, reasoning and truncation across one-byte chunks', async () => {
    const text = ': heartbeat\r\n\r\ndata: {"choices":[{"delta":{"reasoning_content":"Réflexion"}}]}\r\n\r\n'
      + 'data: {"choices":[{"delta":{"content":"Bonjour, été 🌍 !"},"finish_reason":"length"}]}\r\n\r\ndata: [DONE]\r\n\r\n';
    const result = await consumeCompletion(response(text), () => {});
    expect(result).toEqual({content:'Bonjour, été 🌍 !', reasoning:'Réflexion', limited:true});
  });
  it('reports a prematurely closed stream while delivering its partial text', async () => {
    let partial = '';
    await expect(consumeCompletion(response('data: {"choices":[{"delta":{"content":"Partiel"}}]}\n\n'), value => {partial = value.content;})).rejects.toThrow('interrompue');
    expect(partial).toBe('Partiel');
  });
  it('propagates an API error event', async () => {
    await expect(consumeCompletion(response('data: {"error":{"message":"Indisponible"}}\n\n'), () => {})).rejects.toThrow('Indisponible');
  });
});
