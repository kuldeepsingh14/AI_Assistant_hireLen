import { CommonModule } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

import { ApiService } from '../../core/api.service';
import { renderMarkdown } from '../../core/markdown';
import { MatchResponse, ReqStatus } from '../../core/models';
import { RadarChart } from '../../shared/radar-chart';

@Component({
  selector: 'app-match',
  standalone: true,
  imports: [CommonModule, FormsModule, RadarChart],
  templateUrl: './match.html',
  styleUrl: './match.css',
})
export class Match {
  private readonly api = inject(ApiService);
  private readonly sanitizer = inject(DomSanitizer);

  readonly jd = signal('');
  readonly jobTitle = signal('');
  readonly company = signal('');
  readonly file = signal<File | null>(null);
  readonly busy = signal(false);
  readonly error = signal('');
  readonly report = signal<MatchResponse | null>(null);
  readonly copied = signal(false);

  readonly canSubmit = computed(
    () => !this.busy() && (this.file() !== null || this.jd().trim().length >= 30),
  );

  readonly counts = computed(() => {
    const reqs = this.report()?.requirements ?? [];
    const by = (...s: ReqStatus[]) => reqs.filter((r) => s.includes(r.status)).length;
    return {
      // "Covered" folds in adjacent and in-progress evidence, which the graded
      // rubric treats as real signal rather than a blank.
      match: by('match'),
      covered: by('transferable', 'partial', 'learning'),
      missing: by('missing'),
      total: reqs.length,
    };
  });

  /** Circumference offset for the score ring (r = 52). */
  readonly ringDash = computed(() => {
    const circumference = 2 * Math.PI * 52;
    const score = this.report()?.score ?? 0;
    return `${(circumference * score) / 100} ${circumference}`;
  });

  onFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.file.set(input.files?.[0] ?? null);
    this.error.set('');
  }

  clearFile(): void {
    this.file.set(null);
  }

  run(): void {
    if (!this.canSubmit()) return;
    this.busy.set(true);
    this.error.set('');
    this.report.set(null);

    const title = this.jobTitle().trim() || undefined;
    const company = this.company().trim() || undefined;
    const chosen = this.file();

    const request$ = chosen
      ? this.api.matchFile(chosen, title, company)
      : this.api.match(this.jd().trim(), title, company);

    request$.subscribe({
      next: (res) => {
        this.report.set(res);
        this.busy.set(false);
      },
      error: (e: Error) => {
        this.error.set(e.message);
        this.busy.set(false);
      },
    });
  }

  reset(): void {
    this.report.set(null);
    this.error.set('');
    this.copied.set(false);
  }

  scoreClass(score: number): string {
    if (score >= 85) return 'strong';
    if (score >= 70) return 'good';
    if (score >= 55) return 'partial';
    return 'weak';
  }

  private static readonly LABELS: Record<ReqStatus, string> = {
    match: 'Met',
    transferable: 'Adjacent experience',
    partial: 'Partial',
    learning: 'Learning now',
    missing: 'Not yet',
  };

  private static readonly PILLS: Record<ReqStatus, string> = {
    match: 'ok',
    transferable: 'good',
    partial: 'warn',
    learning: 'good',
    missing: 'bad',
  };

  statusLabel(status: ReqStatus): string {
    return Match.LABELS[status] ?? status;
  }

  statusPill(status: ReqStatus): string {
    return Match.PILLS[status] ?? 'bad';
  }

  html(markdown: string): SafeHtml {
    return this.sanitizer.bypassSecurityTrustHtml(renderMarkdown(markdown));
  }

  async copyCoverLetter(): Promise<void> {
    const text = this.report()?.cover_letter;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 2000);
    } catch {
      this.error.set('Your browser blocked clipboard access — select the text and copy manually.');
    }
  }

  downloadReport(): void {
    const r = this.report();
    if (!r) return;

    const line = (v: { status: ReqStatus; category: string; requirement: string; comment: string; evidence: string }) =>
      `- [${this.statusLabel(v.status)}] (${v.category === 'must_have' ? 'must have' : 'nice to have'}) ${v.requirement}\n` +
      `  ${v.comment}${v.evidence ? `\n  Evidence: "${v.evidence}"` : ''}`;

    const md = [
      `# Fit report — ${r.job_title ?? 'Role'}${r.company ? ` @ ${r.company}` : ''}`,
      ``,
      `**Score: ${r.score}/100 — ${r.verdict}**`,
      ``,
      r.summary,
      ``,
      ...(r.pitch ? [`## Why they're worth an interview`, ``, r.pitch, ``] : []),
      ...(r.ramp_up ? [`**Ramp-up:** ${r.ramp_up}`, ``] : []),
      `## Requirements`,
      r.requirements.map(line).join('\n'),
      ``,
      `## Strengths`,
      r.strengths.map((s) => `- ${s}`).join('\n'),
      ``,
      `## Gaps`,
      r.gaps.map((s) => `- ${s}`).join('\n'),
      ``,
      `## Suggested screening questions`,
      r.screening_questions.map((s) => `- ${s}`).join('\n'),
      ``,
      `## Cover letter`,
      ``,
      r.cover_letter,
      ``,
      `---`,
      `Generated by HireLens. The score is computed from the verdicts above, not`,
      `estimated: must-haves are weighted 3x against nice-to-haves, and each verdict`,
      `earns credit — met 100%, adjacent experience 70%, partial 50%, actively`,
      `learning 35%, not yet 0%.`,
    ].join('\n');

    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `fit-report-${(r.job_title ?? 'role').toLowerCase().replace(/[^a-z0-9]+/g, '-')}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }
}
