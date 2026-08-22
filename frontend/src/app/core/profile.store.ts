import { Injectable, computed, inject, signal } from '@angular/core';

import { ApiService } from './api.service';
import { ProfileStatus } from './models';

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
  readonly loaded = signal(false);

  /** The name to display, with a fallback so the UI is never blank. */
  readonly ownerName = computed(() => this.profile()?.owner_name?.trim() || '');

  readonly ready = computed(() => this.profile()?.ready ?? false);

  refresh(): void {
    this.api.getProfile().subscribe({
      next: (p) => {
        this.profile.set(p);
        this.loaded.set(true);
      },
      error: () => this.loaded.set(true),
    });
  }

  /** Adopt a status returned by a mutating call, avoiding a second round trip. */
  set(status: ProfileStatus): void {
    this.profile.set(status);
    this.loaded.set(true);
  }
}
