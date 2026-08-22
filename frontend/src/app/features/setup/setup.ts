import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../../core/api.service';
import { AnalyticsResponse, IngestResponse, Lead, ProfileStatus } from '../../core/models';

@Component({
  selector: 'app-setup',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './setup.html',
  styleUrl: './setup.css',
})
export class Setup implements OnInit {
  private readonly api = inject(ApiService);

  readonly profile = signal<ProfileStatus | null>(null);
  readonly token = signal('');
  readonly unlocked = signal(false);
  readonly checking = signal(false);

  readonly file = signal<File | null>(null);
  readonly uploading = signal(false);
  readonly result = signal<IngestResponse | null>(null);
  readonly error = signal('');
  readonly confirmingReset = signal(false);

  // context notes
  readonly notes = signal('');
  readonly savedNotes = signal('');
  readonly savingNotes = signal(false);
  readonly notesSaved = signal(false);
  readonly notesError = signal('');

  readonly analytics = signal<AnalyticsResponse | null>(null);
  readonly analyticsError = signal('');
  readonly confirmingClearLog = signal(false);

  // leads
  readonly leads = signal<Lead[]>([]);
  readonly leadsError = signal('');
  readonly openLead = signal<number | null>(null);
  readonly confirmingClearLeads = signal(false);

  ngOnInit(): void {
    this.refresh();
    const saved = this.api.adminToken;
    if (saved) {
      this.token.set(saved);
      this.unlock();
    }
  }

  private refresh(): void {
    this.api.getProfile().subscribe({
      next: (p) => this.profile.set(p),
      error: (e: Error) => this.error.set(e.message),
    });
  }

  unlock(): void {
    const value = this.token().trim();
    if (!value) return;
    this.checking.set(true);
    this.error.set('');
    this.api.adminToken = value;
    this.api.verifyToken().subscribe({
      next: () => {
        this.unlocked.set(true);
        this.checking.set(false);
        this.loadAnalytics();
        this.loadNotes();
        this.loadLeads();
      },
      error: (e: Error) => {
        this.unlocked.set(false);
        this.checking.set(false);
        this.api.adminToken = '';
        this.error.set(e.message);
      },
    });
  }

  lock(): void {
    this.api.adminToken = '';
    this.unlocked.set(false);
    this.token.set('');
    this.analytics.set(null);
    this.result.set(null);
  }

  onFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.file.set(input.files?.[0] ?? null);
    this.error.set('');
    this.result.set(null);
  }

  upload(): void {
    const chosen = this.file();
    if (!chosen || this.uploading()) return;
    this.uploading.set(true);
    this.error.set('');
    this.api.uploadResume(chosen).subscribe({
      next: (res) => {
        this.result.set(res);
        this.uploading.set(false);
        this.file.set(null);
        this.refresh();
      },
      error: (e: Error) => {
        this.error.set(e.message);
        this.uploading.set(false);
      },
    });
  }

  reset(): void {
    if (!this.confirmingReset()) {
      this.confirmingReset.set(true);
      return;
    }
    this.api.resetProfile().subscribe({
      next: () => {
        this.confirmingReset.set(false);
        this.result.set(null);
        this.refresh();
      },
      error: (e: Error) => {
        this.error.set(e.message);
        this.confirmingReset.set(false);
      },
    });
  }

  cancelReset(): void {
    this.confirmingReset.set(false);
  }

  // ---------- context notes ----------
  loadNotes(): void {
    this.api.getNotes().subscribe({
      next: (r) => {
        this.notes.set(r.notes);
        this.savedNotes.set(r.notes);
      },
      error: (e: Error) => this.notesError.set(e.message),
    });
  }

  get notesDirty(): boolean {
    return this.notes() !== this.savedNotes();
  }

  saveNotes(): void {
    if (this.savingNotes()) return;
    this.savingNotes.set(true);
    this.notesError.set('');
    this.api.saveNotes(this.notes()).subscribe({
      next: (p) => {
        this.profile.set(p);
        this.savedNotes.set(this.notes());
        this.savingNotes.set(false);
        this.notesSaved.set(true);
        setTimeout(() => this.notesSaved.set(false), 2500);
      },
      error: (e: Error) => {
        this.notesError.set(e.message);
        this.savingNotes.set(false);
      },
    });
  }

  insertTemplate(): void {
    const template = [
      '## Job search',
      'Actively looking for a new role and open to interviewing now.',
      '',
      '## Currently learning',
      'LLMs, RAG pipelines, LangChain and LangGraph for agentic workflows.',
      '',
      '## What I want next',
      'Describe the kind of role, team, and problems you want.',
      '',
      '## Availability',
      'Notice period, preferred locations, remote or hybrid.',
    ].join('\n');
    // Append rather than replace, so an accidental click never destroys work.
    const current = this.notes().trim();
    this.notes.set(current ? `${current}\n\n${template}` : template);
  }

  resumeUrl(): string {
    return this.api.resumeUrl();
  }

  loadAnalytics(): void {
    this.analyticsError.set('');
    this.api.analytics().subscribe({
      next: (a) => this.analytics.set(a),
      error: (e: Error) => this.analyticsError.set(e.message),
    });
  }

  // ---------- clearing the activity log ----------
  clearLog(): void {
    if (!this.confirmingClearLog()) {
      this.confirmingClearLog.set(true);
      return;
    }
    this.api.clearAnalytics().subscribe({
      next: () => {
        this.confirmingClearLog.set(false);
        this.loadAnalytics();
      },
      error: (e: Error) => {
        this.analyticsError.set(e.message);
        this.confirmingClearLog.set(false);
      },
    });
  }

  cancelClearLog(): void {
    this.confirmingClearLog.set(false);
  }

  // ---------- leads ----------
  loadLeads(): void {
    this.leadsError.set('');
    this.api.leads().subscribe({
      next: (l) => this.leads.set(l),
      error: (e: Error) => this.leadsError.set(e.message),
    });
  }

  toggleLead(id: number): void {
    this.openLead.set(this.openLead() === id ? null : id);
  }

  removeLead(id: number): void {
    this.api.deleteLead(id).subscribe({
      next: () => {
        this.leads.update((list) => list.filter((l) => l.id !== id));
        this.loadAnalytics();
      },
      error: (e: Error) => this.leadsError.set(e.message),
    });
  }

  clearAllLeads(): void {
    if (!this.confirmingClearLeads()) {
      this.confirmingClearLeads.set(true);
      return;
    }
    this.api.clearLeads().subscribe({
      next: () => {
        this.confirmingClearLeads.set(false);
        this.leads.set([]);
        this.loadAnalytics();
      },
      error: (e: Error) => {
        this.leadsError.set(e.message);
        this.confirmingClearLeads.set(false);
      },
    });
  }

  cancelClearLeads(): void {
    this.confirmingClearLeads.set(false);
  }

  /** Comma-separated contact line for a lead. */
  contactLine(lead: Lead): string {
    return [lead.email, lead.phone].filter(Boolean).join(' · ');
  }

  /** "2026-08-22T09:14:00+00:00" -> "22 Aug, 09:14" */
  when(iso: string): string {
    const d = new Date(iso);
    return isNaN(d.getTime())
      ? iso
      : d.toLocaleString(undefined, {
          day: 'numeric',
          month: 'short',
          hour: '2-digit',
          minute: '2-digit',
        });
  }

  embedderLabel(embedder: string): string {
    return embedder.startsWith('fastembed')
      ? 'Semantic (fastembed)'
      : 'Keyword (BM25 + synonyms)';
  }
}
