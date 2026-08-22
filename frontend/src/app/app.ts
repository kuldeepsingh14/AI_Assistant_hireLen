import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';

import { ApiService } from './core/api.service';
import { Chat } from './features/chat/chat';
import { Match } from './features/match/match';
import { Setup } from './features/setup/setup';

type Tab = 'chat' | 'match' | 'setup';

const THEME_KEY = 'hirelens.theme';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, Chat, Match, Setup],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnInit {
  private readonly api = inject(ApiService);

  readonly tab = signal<Tab>('chat');
  readonly ownerName = signal('');
  readonly ready = signal<boolean | null>(null);
  readonly theme = signal<'dark' | 'light'>('dark');

  readonly resumeDownloadable = signal(false);
  readonly introOpen = signal(false);

  /** Admin lives in the top-right, not in the public tab strip. */
  readonly publicTabs: { id: Tab; label: string; hint: string }[] = [
    { id: 'chat', label: 'Ask', hint: 'Chat about their background' },
    { id: 'match', label: 'Job match', hint: 'Score a job description' },
  ];

  /** "Kuldeep Singh" -> "KS"; falls back to the product mark before load. */
  readonly initials = computed(() => {
    const parts = this.ownerName().trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return 'HL';
    return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
  });

  resumeUrl(): string {
    return this.api.resumeUrl();
  }

  ngOnInit(): void {
    this.restoreTheme();
    this.restoreIntro();
    this.api.getProfile().subscribe({
      next: (p) => {
        this.ownerName.set(p.owner_name);
        this.ready.set(p.ready);
        this.resumeDownloadable.set(p.resume_downloadable);
        // Nothing to ask about yet - send the owner straight to setup.
        if (!p.ready) this.tab.set('setup');
      },
      error: () => this.ready.set(false),
    });
  }

  select(tab: Tab): void {
    this.tab.set(tab);
  }

  // ---------- welcome intro ----------
  private static readonly INTRO_KEY = 'hirelens.introSeen';

  private restoreIntro(): void {
    let seen = false;
    try {
      seen = localStorage.getItem(App.INTRO_KEY) === '1';
    } catch {
      /* private browsing - show it, dismissing just won't stick */
    }
    this.introOpen.set(!seen);
  }

  dismissIntro(): void {
    this.introOpen.set(false);
    try {
      localStorage.setItem(App.INTRO_KEY, '1');
    } catch {
      /* ignore */
    }
  }

  /** Re-openable from the footer, so it is discoverable after dismissal. */
  showIntro(): void {
    this.introOpen.set(true);
  }

  startIn(tab: Tab): void {
    this.dismissIntro();
    this.select(tab);
  }

  // ---------- theme ----------
  private restoreTheme(): void {
    let saved: string | null = null;
    try {
      saved = localStorage.getItem(THEME_KEY);
    } catch {
      /* private browsing */
    }
    this.applyTheme(saved === 'light' ? 'light' : 'dark');
  }

  toggleTheme(): void {
    this.applyTheme(this.theme() === 'dark' ? 'light' : 'dark');
  }

  private applyTheme(mode: 'dark' | 'light'): void {
    this.theme.set(mode);
    document.documentElement.setAttribute('data-theme', mode);
    try {
      localStorage.setItem(THEME_KEY, mode);
    } catch {
      /* ignore */
    }
  }
}
