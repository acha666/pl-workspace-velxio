import type { AutoSaveState } from '../hooks/useAutoSaveProject';
import type { VlxPayload } from '../utils/vlxFile';

export class WorkspaceConflict extends Error {}
export type SaveProject = (project: VlxPayload, revision: string) => Promise<string>;

/** Save once edits pause, like an editor's short auto-save delay. */
export const SAVE_DELAY = 3_000;
/** Continuous editing is still saved at least this often. */
export const MAX_SAVE_DELAY = 30_000;
/**
 * Autosave normally completes well within this time after the last edit, so
 * the indicator only reports unsaved edits after it: it stays steady while
 * the student types, and changes only when a save is overdue.
 */
export const QUIET_PERIOD = SAVE_DELAY + 3_000;
export const RETRY_DELAYS = [5_000, 10_000, 30_000, 60_000];

/** Export timestamps describe an export, not a student edit. */
export function projectKey(project: VlxPayload): string {
  return JSON.stringify({ ...project, exportedAt: '' });
}

/** Serializes optimistic writes, keeps edits made during a request and schedules autosaves. */
export class ProjectSaver {
  project: VlxPayload;
  revision: string;
  /** What the save icon shows; replaced only when it changes. */
  state: AutoSaveState = { status: 'saved', lastSavedAt: null, errorMessage: null };
  conflict = false;
  private savedKey: string;
  private save: SaveProject;
  private emit: () => void;
  private pending: Promise<void> | null = null;
  private saveTimer: ReturnType<typeof setTimeout> | null = null;
  private quietTimer: ReturnType<typeof setTimeout> | null = null;
  private editing = false;
  private firstUnsavedEdit: number | null = null;
  private lastSavedAt: number | null = null;
  private error: string | null = null;
  private failures = 0;

  constructor(project: VlxPayload, revision: string, save: SaveProject, emit: () => void) {
    this.project = project;
    this.savedKey = projectKey(project);
    this.revision = revision;
    this.save = save;
    this.emit = emit;
  }

  get dirty(): boolean {
    return projectKey(this.project) !== this.savedKey;
  }

  /** Closing the page now could lose edits. */
  get unsaved(): boolean {
    return this.dirty || this.pending !== null;
  }

  markConflict(): void {
    this.conflict = true;
    this.error =
      'This workspace changed in another tab. Saving is blocked. Export your local project, then reload to review the saved version.';
    this.clearSaveTimer();
    this.refresh();
  }

  update(project: VlxPayload): void {
    this.project = project;
    if (this.conflict) return;
    this.editing = true;
    if (this.quietTimer) clearTimeout(this.quietTimer);
    this.quietTimer = setTimeout(() => {
      this.editing = false;
      this.refresh();
    }, QUIET_PERIOD);
    if (this.dirty) {
      this.firstUnsavedEdit ??= Date.now();
      // A running save drains later edits, and a failed one retries on its own schedule.
      if (!this.pending && !this.error) {
        const delay = Math.min(SAVE_DELAY, this.firstUnsavedEdit + MAX_SAVE_DELAY - Date.now());
        this.schedule(Math.max(0, delay));
      }
    }
    this.refresh();
  }

  flush(): Promise<void> {
    this.clearSaveTimer();
    if (this.conflict)
      return Promise.reject(new WorkspaceConflict(this.error ?? 'Save conflict.'));
    if (this.pending) return this.pending;
    this.pending = this.drain().finally(() => {
      this.pending = null;
      this.refresh();
    });
    this.refresh();
    return this.pending;
  }

  private schedule(delay: number): void {
    this.clearSaveTimer();
    this.saveTimer = setTimeout(() => {
      void this.flush().catch(() => {});
    }, delay);
  }

  private clearSaveTimer(): void {
    if (this.saveTimer) clearTimeout(this.saveTimer);
    this.saveTimer = null;
  }

  private refresh(): void {
    let status: AutoSaveState['status'];
    if (this.error) status = 'error';
    else if (this.editing || !this.unsaved) status = 'saved';
    else status = this.pending ? 'saving' : 'dirty';
    const { state } = this;
    if (
      status === state.status &&
      this.lastSavedAt === state.lastSavedAt &&
      this.error === state.errorMessage
    )
      return;
    this.state = { status, lastSavedAt: this.lastSavedAt, errorMessage: this.error };
    this.emit();
  }

  private async drain(): Promise<void> {
    try {
      while (this.dirty) {
        const snapshot = this.project;
        const key = projectKey(snapshot);
        this.revision = await this.save(snapshot, this.revision);
        this.savedKey = key;
        this.lastSavedAt = Date.now();
      }
      this.firstUnsavedEdit = null;
      this.failures = 0;
      this.error = null;
    } catch (error) {
      if (error instanceof WorkspaceConflict) this.markConflict();
      else {
        this.error = `Changes are not saved yet. ${error instanceof Error ? error.message : String(error)} Retrying automatically.`;
        this.schedule(RETRY_DELAYS[Math.min(this.failures++, RETRY_DELAYS.length - 1)]);
      }
      throw error;
    }
  }
}
