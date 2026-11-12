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
    expect(result).toEqual({content:'Bonjour, été 🌍 !', reasoning:'Réflexion', limited:true, outils:[]});
  });
  it('reads the conversation title sent by the API between Qwen chunks', async () => {
    const text = 'data: {"choices":[{"delta":{"content":"Bon"}}]}\n\ndata: {"observatoire":{"title":"Salutations"}}\n\n'
      + 'data: {"choices":[{"delta":{"content":"jour"}}]}\n\ndata: [DONE]\n\n';
    const titles: (string | undefined)[] = [];
    const result = await consumeCompletion(response(text, 7), value => titles.push(value.title));
    expect(result).toEqual({content:'Bonjour', reasoning:'', limited:false, title:'Salutations', outils:[]});
    expect(titles.at(-1)).toBe('Salutations');
  });
  it('collects tool steps and lets the checked final text replace the streamed one', async () => {
    const text = 'data: {"observatoire":{"recherche_web":{"type":"appel","arguments":{"question":"Q"}}}}\n\n'
      + 'data: {"choices":[{"index":0,"delta":{"content":"Brouillon [9]"}}]}\n\n'
      + 'data: {"observatoire":{"recherche_web":{"type":"fin","pages_lues":5}}}\n\n'
      + 'data: {"observatoire":{"contenu":"Réponse vérifiée [1]."}}\n\ndata: [DONE]\n\n';
    const seen: number[] = [];
    const result = await consumeCompletion(response(text, 11), value => seen.push(value.outils.length));
    expect(result.content).toBe('Réponse vérifiée [1].');
    expect(result.outils).toEqual([{outil:'recherche_web', type:'appel', arguments:{question:'Q'}}, {outil:'recherche_web', type:'fin', pages_lues:5}]);
    expect(seen.at(-1)).toBe(2);
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
