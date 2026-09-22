import type { AutoSaveState } from '../hooks/useAutoSaveProject';
import type { VlxPayload } from '../utils/vlxFile';

export class WorkspaceConflict extends Error {}
export type SaveProject = (project: VlxPayload, revision: string) => Promise<string>;

/** Export timestamps describe an export, not a student edit. */
export function projectKey(project: VlxPayload): string {
  return JSON.stringify({ ...project, exportedAt: '' });
}

/** Serializes optimistic writes and keeps edits made during a request. */
export class ProjectSaver {
  project: VlxPayload;
  revision: string;
  state: AutoSaveState = { status: 'saved', lastSavedAt: null, errorMessage: null };
  conflict = false;
  private savedKey: string;
  private save: SaveProject;
  private emit: () => void;
  private pending: Promise<void> | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;

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

  markConflict(): void {
    this.conflict = true;
    this.setState(
      'error',
      'This workspace changed in another tab. Saving is blocked. Export your local project, then reload to review the saved version.',
    );
  }

  update(project: VlxPayload): void {
    this.project = project;
    if (this.conflict || this.pending) return;
    this.setState(this.dirty ? 'dirty' : 'saved');
    if (this.timer) clearTimeout(this.timer);
    if (this.dirty)
      this.timer = setTimeout(() => {
        void this.flush().catch(() => {});
      }, 400);
  }

  flush(): Promise<void> {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.conflict)
      return Promise.reject(new WorkspaceConflict(this.state.errorMessage ?? 'Save conflict.'));
    if (this.pending) return this.pending;
    this.pending = this.drain().finally(() => {
      this.pending = null;
    });
    return this.pending;
  }

  private setState(status: AutoSaveState['status'], errorMessage: string | null = null): void {
    this.state = {
      status,
      errorMessage,
      lastSavedAt: status === 'saved' ? Date.now() : this.state.lastSavedAt,
    };
    this.emit();
  }

  private async drain(): Promise<void> {
    try {
      while (this.dirty) {
        const snapshot = this.project;
        const key = projectKey(snapshot);
        this.setState('saving');
        this.revision = await this.save(snapshot, this.revision);
        this.savedKey = key;
      }
      this.setState('saved');
    } catch (error) {
      this.conflict = error instanceof WorkspaceConflict;
      if (this.conflict) this.markConflict();
      else
        this.setState(
          'error',
          `Changes have not been saved. ${error instanceof Error ? error.message : String(error)} Use Save now to retry.`,
        );
      throw error;
    }
  }
}
