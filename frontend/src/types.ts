export type Effort = 'none' | 'low' | 'medium' | 'xhigh';
export type Activity = 'generating' | 'compacting';
export interface Settings { effort: Effort; temperature: number }
export interface User { id: string; username: string; is_admin: boolean }
export interface Auth { user: User; csrf_token: string; configured: boolean }
export interface Message {
  role: 'user' | 'assistant'; content: string; reasoning?: string; interrupted?: boolean;
  /** Cut by the length limit: the answer can be continued. */
  truncated?: boolean;
  /** Images and documents of the user's library shown with a question. */
  attachments?: AttachmentRef[];
}
/** Width and height are 0 for documents; pages is 0 for Word and text files. */
export interface AttachmentRef { id: string; name: string; width: number; height: number; kind?: 'document'; pages?: number; tokens?: number }
/** A document is read once when added: `progress` of `pages` done, then ready or failed. */
export interface LibraryItem {
  id: string; name: string; kind: 'image' | 'document'; mime: string; width: number; height: number; size: number; created_at: string;
  status: 'reading' | 'ready' | 'failed'; pages: number; progress: number; scanned: number; doubts: number; tokens: number; error: string | null;
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
