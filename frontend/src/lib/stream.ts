export interface Completion { content: string; reasoning: string; limited: boolean }
interface Packet {
  error?: {message?: string};
  choices?: {delta?: {content?: string; reasoning_content?: string; reasoning?: string;
    provider_specific_fields?: {reasoning?: string}}; finish_reason?: string}[];
}

/** Handles UTF-8 characters and SSE events split across arbitrary HTTP chunks. */
export async function consumeCompletion(response: Response, onUpdate: (value: Completion) => void): Promise<Completion> {
  if (!response.body) throw new Error('Le serveur n’a pas renvoyé de flux de réponse.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '', complete = false;
  const result: Completion = {content: '', reasoning: '', limited: false};
  function event(value: string) {
    const raw = value.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
    if (!raw) return;
    if (raw.trim() === '[DONE]') { complete = true; return; }
    const packet = JSON.parse(raw) as Packet;
    if (packet.error) throw new Error(packet.error.message || 'Le flux Qwen a rencontré une erreur.');
    const choice = packet.choices?.[0]; const delta = choice?.delta;
    if (typeof delta?.content === 'string') result.content += delta.content;
    const reasoning = delta?.reasoning_content ?? delta?.reasoning ?? delta?.provider_specific_fields?.reasoning;
    if (typeof reasoning === 'string') result.reasoning += reasoning;
    if (choice?.finish_reason === 'length') result.limited = true;
  }
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer = (buffer + decoder.decode(value || new Uint8Array(), {stream: !done})).replace(/\r\n/g, '\n');
      let split: number;
      while ((split = buffer.indexOf('\n\n')) >= 0) { event(buffer.slice(0, split)); buffer = buffer.slice(split + 2); }
      onUpdate({...result});
      if (done) { if (buffer.trim()) event(buffer); break; }
    }
    if (!complete) throw new Error('La connexion a été interrompue avant la fin de la réponse.');
    return result;
  } finally {
    if (!complete) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
