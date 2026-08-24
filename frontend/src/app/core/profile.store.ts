import { Injectable, computed, inject, signal } from '@angular/core';

import { ApiService } from './api.service';
import { ProfileStatus } from './models';

/** After this long without a response, say why it is taking a while. */
const SLOW_AFTER_MS = 3500;

/**
 * One shared copy of the profile.
 *
 * Every component used to fetch this for itself on init, which meant the shell
 * held whatever was true when the page first loaded while the chat held a later
 * snapshot. Uploading a resume mid-session left the header naming "the
 * candidate" and the conversation naming the real person, on the same screen.
 *
 * A single store with an explicit refresh keeps them in step: whoever changes
 * the profile calls `refresh()`, and every reader updates at once.
 */
@Injectable({ providedIn: 'root' })
export class ProfileStore {
  private readonly api = inject(ApiService);

  readonly profile = signal<ProfileStatus | null>(null);

  /** False until the first response lands, so the UI can hold back placeholders. */
  readonly loaded = signal(false);

  /** True while a first load is taking long enough to need explaining. */
  readonly slow = signal(false);

  readonly failed = signal('');

  /** The name to display. Empty until loaded, so nothing guesses a wrong one. */
  readonly ownerName = computed(() => this.profile()?.owner_name?.trim() || '');

  readonly ready = computed(() => this.profile()?.ready ?? false);

  private slowTimer: ReturnType<typeof setTimeout> | null = null;

  refresh(): void {
    // Only the *first* load gets a loading state. A refresh after an upload
    // should not blank out a screen that already has content on it.
    const first = !this.loaded();
    if (first) {
      this.failed.set('');
      this.slowTimer = setTimeout(() => this.slow.set(true), SLOW_AFTER_MS);
    }

    this.api.getProfile().subscribe({
      next: (p) => {
        this.settle();
        this.profile.set(p);
      },
      error: (e: Error) => {
        this.settle();
        this.failed.set(e.message);
      },
    });
  }

  private settle(): void {
    if (this.slowTimer) {
      clearTimeout(this.slowTimer);
      this.slowTimer = null;
    }
    this.slow.set(false);
    this.loaded.set(true);
  }

  /** Adopt a status returned by a mutating call, avoiding a second round trip. */
  set(status: ProfileStatus): void {
    this.settle();
    this.profile.set(status);
  }
}
