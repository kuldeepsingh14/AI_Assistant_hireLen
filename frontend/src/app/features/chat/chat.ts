import { CommonModule } from '@angular/common';
import {
  AfterViewChecked,
  Component,
  ElementRef,
  OnInit,
  ViewChild,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

import { ApiService } from '../../core/api.service';
import { renderMarkdown } from '../../core/markdown';
import { ChatMessage, LeadPayload, Mode, ProfileStatus, ScreeningAnswer } from '../../core/models';

@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './chat.html',
  styleUrl: './chat.css',
})
export class Chat implements OnInit, AfterViewChecked {
  private readonly api = inject(ApiService);
  private readonly sanitizer = inject(DomSanitizer);

  @ViewChild('scroller') private scroller?: ElementRef<HTMLElement>;

  readonly profile = signal<ProfileStatus | null>(null);
  readonly mode = signal<Mode>('visitor');
  readonly messages = signal<ChatMessage[]>([]);
  readonly suggestions = signal<string[]>([]);
  readonly draft = signal('');
  readonly busy = signal(false);
  readonly error = signal('');
  readonly openCitations = signal<Set<number>>(new Set());

  // screening pack
  readonly packOpen = signal(false);
  readonly packBusy = signal(false);
  readonly pack = signal<ScreeningAnswer[]>([]);

  // ---- recruiter contact capture ----
  readonly leadOpen = signal(false);
  readonly leadSent = signal(false);
  readonly leadBusy = signal(false);
  readonly leadError = signal('');
  readonly lead = signal<LeadPayload>({ name: '', company: '', email: '', phone: '', role: '' });

  private sessionId: string | null = null;
  private shouldScroll = false;

  ngOnInit(): void {
    this.api.getProfile().subscribe({
      next: (p) => {
        this.profile.set(p);
        this.greet(p);
      },
      error: (e: Error) => this.error.set(e.message),
    });
    this.loadSuggestions();
  }

  ngAfterViewChecked(): void {
    if (this.shouldScroll && this.scroller) {
      this.scroller.nativeElement.scrollTop = this.scroller.nativeElement.scrollHeight;
      this.shouldScroll = false;
    }
  }

  private greet(p: ProfileStatus): void {
    const who = p.owner_name;
    this.messages.set([
      {
        role: 'assistant',
        content: p.ready
          ? `Hi — I'm ${who}'s AI assistant. Everything I say comes from their résumé and the notes they keep about what they're working on now, and I'll show you the exact source behind each answer. Ask me anything, or switch to **HR mode** above for recruiter-style answers.`
          : `This assistant is being set up right now, so I can't answer questions about ${who} just yet. Please check back shortly.`,
      },
    ]);
  }

  setMode(mode: Mode): void {
    if (this.mode() === mode) return;
    this.mode.set(mode);
    this.loadSuggestions();
    // Offer the contact card on entering HR mode, but only once per visit and
    // never as a gate - a recruiter who has to fill a form before getting an
    // answer just closes the tab.
    if (mode === 'hr' && !this.leadSent() && !Chat.leadDismissed()) {
      this.leadOpen.set(true);
    }
    this.messages.update((m) => [
      ...m,
      {
        role: 'assistant',
        content:
          mode === 'hr'
            ? `**HR mode on.** I'll answer like a first-round screen: claim first, then the evidence from ${this.ownerName()}'s resume.`
            : `**Visitor mode on.** Back to the casual tour of ${this.ownerName()}'s work.`,
      },
    ]);
    this.shouldScroll = true;
  }

  private loadSuggestions(): void {
    this.api.suggestions(this.mode()).subscribe({
      next: (s) => this.suggestions.set(s),
      error: () => this.suggestions.set([]),
    });
  }

  ownerName(): string {
    return this.profile()?.owner_name ?? 'the candidate';
  }

  ask(text?: string): void {
    const message = (text ?? this.draft()).trim();
    if (!message || this.busy()) return;

    this.error.set('');
    this.draft.set('');
    this.busy.set(true);

    // Snapshot the history *before* appending, so the backend doesn't see the
    // question twice.
    const history = this.messages()
      .filter((m) => !m.error && !m.pending)
      .slice(-6)
      .map((m) => ({ role: m.role, content: m.content }));

    this.messages.update((m) => [
      ...m,
      { role: 'user', content: message },
      { role: 'assistant', content: '', pending: true },
    ]);
    this.shouldScroll = true;

    this.api
      .chat({ message, mode: this.mode(), history, session_id: this.sessionId })
      .subscribe({
        next: (res) => {
          this.sessionId = res.session_id;
          if (res.suggestions?.length) this.suggestions.set(res.suggestions);
          this.replacePending({
            role: 'assistant',
            content: res.answer,
            citations: res.citations,
            grounded: res.grounded,
          });
          this.busy.set(false);
          this.shouldScroll = true;
        },
        error: (e: Error) => {
          this.replacePending({ role: 'assistant', content: e.message, error: true });
          this.error.set(e.message);
          this.busy.set(false);
          this.shouldScroll = true;
        },
      });
  }

  private replacePending(msg: ChatMessage): void {
    this.messages.update((list) => {
      const next = [...list];
      const i = next.findIndex((m) => m.pending);
      if (i >= 0) next[i] = msg;
      else next.push(msg);
      return next;
    });
  }

  onKeydown(event: KeyboardEvent): void {
    // Enter sends; Shift+Enter makes a newline.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.ask();
    }
  }

  toggleCitations(i: number): void {
    this.openCitations.update((set) => {
      const next = new Set(set);
      next.has(i) ? next.delete(i) : next.add(i);
      return next;
    });
  }

  isOpen(i: number): boolean {
    return this.openCitations().has(i);
  }

  html(markdown: string): SafeHtml {
    // renderMarkdown escapes first and only re-adds a fixed tag whitelist.
    return this.sanitizer.bypassSecurityTrustHtml(renderMarkdown(markdown));
  }

  clear(): void {
    this.sessionId = null;
    this.openCitations.set(new Set());
    const p = this.profile();
    if (p) this.greet(p);
  }

  // ---------- recruiter contact ----------
  private static readonly LEAD_KEY = 'hirelens.leadDismissed';

  private static leadDismissed(): boolean {
    try {
      return localStorage.getItem(Chat.LEAD_KEY) === '1';
    } catch {
      return false;
    }
  }

  openLead(): void {
    this.leadError.set('');
    this.leadOpen.set(true);
  }

  dismissLead(): void {
    this.leadOpen.set(false);
    try {
      // Remember the "not now", so it is asked once rather than every toggle.
      localStorage.setItem(Chat.LEAD_KEY, '1');
    } catch {
      /* private browsing - it will simply ask again next visit */
    }
  }

  updateLead(field: keyof LeadPayload, value: string): void {
    this.lead.update((l) => ({ ...l, [field]: value }));
  }

  get leadValid(): boolean {
    const l = this.lead();
    return !!l.name?.trim() && !!(l.email?.trim() || l.phone?.trim());
  }

  submitLead(): void {
    if (!this.leadValid || this.leadBusy()) return;
    this.leadBusy.set(true);
    this.leadError.set('');
    this.api.submitLead({ ...this.lead(), session_id: this.sessionId }).subscribe({
      next: () => {
        this.leadBusy.set(false);
        this.leadSent.set(true);
        this.leadOpen.set(false);
        this.messages.update((m) => [
          ...m,
          {
            role: 'assistant',
            content: `Thanks — ${this.ownerName()} will see your details along with everything you asked here. Anything else you'd like to know?`,
          },
        ]);
        this.shouldScroll = true;
      },
      error: (e: Error) => {
        this.leadError.set(e.message);
        this.leadBusy.set(false);
      },
    });
  }

  // ---------- screening pack ----------
  openPack(): void {
    this.packOpen.set(true);
    if (this.pack().length || this.packBusy()) return;
    this.packBusy.set(true);
    this.api.screeningPack().subscribe({
      next: (res) => {
        this.pack.set(res.answers);
        this.packBusy.set(false);
      },
      error: (e: Error) => {
        this.error.set(e.message);
        this.packBusy.set(false);
        this.packOpen.set(false);
      },
    });
  }

  closePack(): void {
    this.packOpen.set(false);
  }

  downloadPack(): void {
    const owner = this.ownerName();
    const body = this.pack()
      .map((a) => `## ${a.question}\n\n${a.answer}\n`)
      .join('\n');
    const md = `# Screening pack — ${owner}\n\nGenerated by HireLens from ${owner}'s resume.\n\n${body}`;
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `screening-pack-${owner.toLowerCase().replace(/\s+/g, '-')}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }
}
