export type Effort = 'none' | 'low' | 'medium' | 'xhigh';
export type Activity = 'generating' | 'compacting';
/** Web search depth chosen in the menu of the Web button: auto lets L'Observatoire decide whether and how deep. */
export type WebMode = 'auto' | 'web' | 'approfondie' | 'tres_approfondie';
export interface Settings { effort: Effort; temperature: number; web: boolean; webMode: WebMode }
/** recherche_web: the account may use the web search (Web button). */
export interface User { id: string; username: string; is_admin: boolean; recherche_web?: boolean }
/** One step of a tool used for an answer (web search…), as sent by the server; `outil` names the tool. */
export interface ToolEvent { outil: string; type: string; [key: string]: unknown }
export interface Auth { user: User; csrf_token: string; configured: boolean }
export interface Message {
  role: 'user' | 'assistant'; content: string; reasoning?: string; interrupted?: boolean;
  /** Cut by the length limit: the answer can be continued. */
  truncated?: boolean;
  /** Images and documents of the user's library shown with a question. */
  attachments?: AttachmentRef[];
  /** Steps of the tools used for this answer (web search), shown above it. */
  outils?: ToolEvent[];
}
/** Width and height are 0 for documents; pages is 0 for Word and text files. */
export interface AttachmentRef { id: string; name: string; width: number; height: number; kind?: 'document'; pages?: number; tokens?: number }
/** A document is read once when added: `progress` of `pages` done, then ready or failed. */
export interface LibraryItem {
  id: string; name: string; kind: 'image' | 'document'; mime: string; width: number; height: number; size: number; created_at: string;
  status: 'reading' | 'ready' | 'failed'; pages: number; progress: number; scanned: number; doubts: number; tokens: number; error: string | null;
  /** Images created in the Images tab: how they were made. */
  generation?: Generation | null;
}
/** `prompt`: the user's idea; `improved`: rewritten by Qwen (absent on images made before 22/11);
 * `sent`: the prompt the image model received (improved, with the style). */
export interface Generation { prompt: string; improved?: string | null; sent: string; style: string; style_name?: string; size: string; seed: number; seconds: number }
export interface CreationStyle { id: string; name: string; words: string }
/** A style written by the user: `example` once its example image exists, `version` changes with it. */
export interface MyStyle extends CreationStyle { example: boolean; version: number }
export interface CreationConfig {
  configured: boolean; styles: CreationStyle[]; default_style: string; formats: {name: string; size: string}[];
  sizes: string[]; default_size: string; max_count: number; max_prompt: number;
  my_styles: MyStyle[]; max_styles: number; max_style_name: number; max_style_words: number;
}
export interface Library { items: LibraryItem[]; used_bytes: number; quota_bytes: number }
/** A file chosen for the next message: uploading, being read (documents), ready (in the library) or refused. */
export interface PendingImage {
  key: string; name: string; preview?: string; document?: boolean; status: 'uploading' | 'reading' | 'ready' | 'error';
  ref?: AttachmentRef; error?: string; progress?: string;
}
export interface Conversation {
  id: string; title: string; version: number; messages: Message[];
  message_count: number; updated_at: string;
  context_summary: string; compacted_through: number; compaction_count: number;
}
export type ConversationSummary = Omit<Conversation, 'messages'>;
export interface Notice { message: string; retry?: boolean; resume?: boolean }
export interface Legacy { chats?: { messages?: Message[] }[]; settings?: Partial<Settings> }

export interface ContextUsage {
  conversation_id: string; version: number; used_tokens: number; measured_tokens: number; limit_tokens: number; max_output_tokens: number;
  reserved_tokens: number; safety_tokens: number; auto_compact_at: number;
  estimated: boolean; source: string; can_compact: boolean; summarized_messages: number;
}
