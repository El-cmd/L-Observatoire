export type Effort = 'none' | 'low' | 'medium' | 'xhigh';
export interface Settings { effort: Effort; temperature: number; maxTokens: number }
export interface User { id: string; username: string; is_admin: boolean }
export interface Auth { user: User; csrf_token: string; configured: boolean }
export interface Message {
  role: 'user' | 'assistant'; content: string; reasoning?: string; interrupted?: boolean;
}
export interface Conversation {
  id: string; title: string; version: number; messages: Message[];
  message_count: number; updated_at: string;
}
export type ConversationSummary = Omit<Conversation, 'messages'>;
export interface Notice { message: string; retry?: boolean }
export interface Legacy { chats?: { messages?: Message[] }[]; settings?: Partial<Settings> }
