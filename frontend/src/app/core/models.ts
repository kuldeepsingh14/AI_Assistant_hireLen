/** Mirrors backend/app/models/schemas.py. Keep the two in sync. */

export type Mode = 'visitor' | 'hr';

export type ChunkSource = 'resume' | 'notes';

export interface Citation {
  chunk_id: string;
  section: string;
  snippet: string;
  score: number;
  source: ChunkSource;
}

export interface Turn {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatRequest {
  message: string;
  mode: Mode;
  history: Turn[];
  session_id?: string | null;
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
  grounded: boolean;
  mode: Mode;
  session_id: string;
  suggestions: string[];
}

export interface ProfileStatus {
  ready: boolean;
  chunks: number;
  sections: string[];
  note_sections: string[];
  has_notes: boolean;
  resume_downloadable: boolean;
  embedder: string;
  llm_enabled: boolean;
  owner_name: string;
  indexed_at: string | null;
}

export interface IngestResponse {
  filename: string;
  characters: number;
  chunks: number;
  sections: string[];
  embedder: string;
}

export type ReqStatus = 'match' | 'transferable' | 'partial' | 'learning' | 'missing';

export interface RequirementVerdict {
  requirement: string;
  category: 'must_have' | 'nice_to_have';
  status: ReqStatus;
  evidence: string;
  comment: string;
}

export interface SkillAxis {
  axis: string;
  required: number;
  candidate: number;
}

export interface MatchResponse {
  score: number;
  verdict: string;
  summary: string;
  pitch: string;
  ramp_up: string;
  requirements: RequirementVerdict[];
  radar: SkillAxis[];
  strengths: string[];
  gaps: string[];
  screening_questions: string[];
  cover_letter: string;
  job_title: string | null;
  company: string | null;
}

export interface ScreeningAnswer {
  question: string;
  answer: string;
  citations: Citation[];
}

export interface ScreeningPackResponse {
  owner_name: string;
  answers: ScreeningAnswer[];
}

export interface QuestionStat {
  question: string;
  mode: string;
  asked_at: string;
  grounded: boolean;
}

export interface LeadPayload {
  name: string;
  company?: string | null;
  email?: string | null;
  phone?: string | null;
  role?: string | null;
  note?: string | null;
  session_id?: string | null;
}

export interface Lead {
  id: number;
  name: string;
  company: string | null;
  email: string | null;
  phone: string | null;
  role: string | null;
  note: string | null;
  created_at: string;
  questions: string[];
}

export interface AnalyticsResponse {
  total_questions: number;
  hr_questions: number;
  visitor_questions: number;
  ungrounded_questions: number;
  total_sessions: number;
  total_jd_matches: number;
  total_leads: number;
  top_jd_titles: string[];
  recent: QuestionStat[];
}

/** A rendered chat bubble. */
export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  grounded?: boolean;
  error?: boolean;
  pending?: boolean;
}
