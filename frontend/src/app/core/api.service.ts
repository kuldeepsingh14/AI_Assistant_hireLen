import { HttpClient, HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { environment } from '../../environments/environment';
import {
  AnalyticsResponse,
  ChatRequest,
  ChatResponse,
  IngestResponse,
  Lead,
  LeadPayload,
  MatchResponse,
  Mode,
  ProfileStatus,
  ScreeningPackResponse,
} from './models';

const TOKEN_KEY = 'hirelens.adminToken';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiUrl.replace(/\/$/, '');

  // ---- owner token (kept in localStorage so a refresh doesn't log the owner out) ----
  get adminToken(): string {
    try {
      return localStorage.getItem(TOKEN_KEY) ?? '';
    } catch {
      return '';
    }
  }

  set adminToken(value: string) {
    try {
      value ? localStorage.setItem(TOKEN_KEY, value) : localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* private browsing - the token just won't persist */
    }
  }

  private ownerHeaders(): HttpHeaders {
    return new HttpHeaders({ 'X-Admin-Token': this.adminToken });
  }

  // ---- profile ----
  getProfile(): Observable<ProfileStatus> {
    return this.http.get<ProfileStatus>(`${this.base}/api/profile`).pipe(catchError(toError));
  }

  uploadResume(file: File): Observable<IngestResponse> {
    const form = new FormData();
    form.append('file', file);
    return this.http
      .post<IngestResponse>(`${this.base}/api/profile/upload`, form, {
        headers: this.ownerHeaders(),
      })
      .pipe(catchError(toError));
  }

  getNotes(): Observable<{ notes: string }> {
    return this.http
      .get<{ notes: string }>(`${this.base}/api/profile/notes`, { headers: this.ownerHeaders() })
      .pipe(catchError(toError));
  }

  saveNotes(notes: string): Observable<ProfileStatus> {
    return this.http
      .put<ProfileStatus>(
        `${this.base}/api/profile/notes`,
        { notes },
        { headers: this.ownerHeaders() },
      )
      .pipe(catchError(toError));
  }

  /** Public URL of the original resume file, for a direct browser download. */
  resumeUrl(): string {
    return `${this.base}/api/profile/resume`;
  }

  resetProfile(): Observable<void> {
    return this.http
      .delete<void>(`${this.base}/api/profile`, { headers: this.ownerHeaders() })
      .pipe(catchError(toError));
  }

  // ---- chat ----
  chat(payload: ChatRequest): Observable<ChatResponse> {
    return this.http.post<ChatResponse>(`${this.base}/api/chat`, payload).pipe(catchError(toError));
  }

  suggestions(mode: Mode): Observable<string[]> {
    return this.http
      .get<string[]>(`${this.base}/api/chat/suggestions`, { params: { mode } })
      .pipe(catchError(toError));
  }

  screeningPack(): Observable<ScreeningPackResponse> {
    return this.http
      .post<ScreeningPackResponse>(`${this.base}/api/chat/screening-pack`, {})
      .pipe(catchError(toError));
  }

  // ---- jd matching ----
  match(jobDescription: string, jobTitle?: string, company?: string): Observable<MatchResponse> {
    return this.http
      .post<MatchResponse>(`${this.base}/api/match`, {
        job_description: jobDescription,
        job_title: jobTitle || null,
        company: company || null,
      })
      .pipe(catchError(toError));
  }

  matchFile(file: File, jobTitle?: string, company?: string): Observable<MatchResponse> {
    const form = new FormData();
    form.append('file', file);
    if (jobTitle) form.append('job_title', jobTitle);
    if (company) form.append('company', company);
    return this.http
      .post<MatchResponse>(`${this.base}/api/match/upload`, form)
      .pipe(catchError(toError));
  }

  // ---- admin ----
  verifyToken(): Observable<{ ok: boolean }> {
    return this.http
      .get<{ ok: boolean }>(`${this.base}/api/admin/verify`, { headers: this.ownerHeaders() })
      .pipe(catchError(toError));
  }

  submitLead(lead: LeadPayload): Observable<{ ok: boolean; id: number }> {
    return this.http
      .post<{ ok: boolean; id: number }>(`${this.base}/api/leads`, lead)
      .pipe(catchError(toError));
  }

  leads(): Observable<Lead[]> {
    return this.http
      .get<Lead[]>(`${this.base}/api/admin/leads`, { headers: this.ownerHeaders() })
      .pipe(catchError(toError));
  }

  deleteLead(id: number): Observable<void> {
    return this.http
      .delete<void>(`${this.base}/api/admin/leads/${id}`, { headers: this.ownerHeaders() })
      .pipe(catchError(toError));
  }

  clearLeads(): Observable<void> {
    return this.http
      .delete<void>(`${this.base}/api/admin/leads`, { headers: this.ownerHeaders() })
      .pipe(catchError(toError));
  }

  clearAnalytics(): Observable<void> {
    return this.http
      .delete<void>(`${this.base}/api/admin/analytics`, { headers: this.ownerHeaders() })
      .pipe(catchError(toError));
  }

  analytics(): Observable<AnalyticsResponse> {
    return this.http
      .get<AnalyticsResponse>(`${this.base}/api/admin/analytics`, { headers: this.ownerHeaders() })
      .pipe(catchError(toError));
  }
}

/** FastAPI puts the human-readable reason in `detail`; surface that instead of a status code. */
function toError(err: HttpErrorResponse) {
  let message = 'Something went wrong.';
  if (err.status === 0) {
    // The browser reports a blocked-by-CORS response identically to a dead
    // server, so name both causes rather than guessing the wrong one.
    message =
      `No response from the API at ${environment.apiUrl}. Either the backend ` +
      `isn't running, or it rejected this page's origin (${location.origin}) — ` +
      `add that origin to ALLOWED_ORIGINS in backend/.env and restart it.`;
  } else if (typeof err.error?.detail === 'string') {
    message = err.error.detail;
  } else if (Array.isArray(err.error?.detail)) {
    message = err.error.detail.map((d: any) => d.msg ?? String(d)).join('; ');
  } else if (err.message) {
    message = err.message;
  }
  return throwError(() => new Error(message));
}
