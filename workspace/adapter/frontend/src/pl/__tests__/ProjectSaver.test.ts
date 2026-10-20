import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import {
  MAX_SAVE_DELAY,
  ProjectSaver,
  QUIET_PERIOD,
  RETRY_DELAYS,
  SAVE_DELAY,
  WorkspaceConflict,
} from '../ProjectSaver';
import type { VlxPayload } from '../../utils/vlxFile';

function project(code: string): VlxPayload {
  return {
    format: 'velxio-project',
    version: 1,
    exportedAt: '',
    boards: [],
    fileGroups: { group: [{ name: 'sketch.ino', content: code }] },
    components: [],
    wires: [],
    activeBoardId: null,
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((accept) => {
    resolve = accept;
  });
  return { promise, resolve };
}
beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe('PrairieLearn project persistence', () => {
  it('drains edits made during a write using the confirmed revision', async () => {
    const first = deferred<string>();
    const writes: Array<{ project: VlxPayload; revision: string }> = [];
    const saver = new ProjectSaver(
      project('old'),
      'r0',
      async (project, revision) => {
        writes.push({ project, revision });
        return writes.length === 1 ? first.promise : 'r2';
      },
      () => {},
    );
    saver.update(project('one'));
    const flush = saver.flush();
    saver.update(project('two'));
    expect(saver.flush()).toBe(flush);
    first.resolve('r1');
    await flush;
    expect(
      writes.map((write) => [write.project.fileGroups.group[0].content, write.revision]),
    ).toEqual([
      ['one', 'r0'],
      ['two', 'r1'],
    ]);
    expect(saver.state.status).toBe('saved');
  });
  it('blocks all later writes after conflict while retaining local edits', async () => {
    let writes = 0;
    const saver = new ProjectSaver(
      project('old'),
      'r0',
      async () => {
        writes++;
        throw new WorkspaceConflict('Conflict');
      },
      () => {},
    );
    saver.update(project('local'));
    await expect(saver.flush()).rejects.toThrow(WorkspaceConflict);
    saver.update(project('keep this too'));
    await expect(saver.flush()).rejects.toThrow(WorkspaceConflict);
    expect(writes).toBe(1);
    expect(saver.project.fileGroups.group[0].content).toBe('keep this too');
  });
  it('allows retry after a transient failure without losing the old revision', async () => {
    let writes = 0;
    const saver = new ProjectSaver(
      project('old'),
      'r0',
      async () => {
        if (++writes === 1) throw new Error('Offline');
        return 'r1';
      },
      () => {},
    );
    saver.update(project('new'));
    await expect(saver.flush()).rejects.toThrow('Offline');
    expect(saver.revision).toBe('r0');
    expect(saver.dirty).toBe(true);
    await saver.flush();
    expect(saver.dirty).toBe(false);
  });
  it('does not treat a new exportedAt value as an edit', async () => {
    let writes = 0;
    const saver = new ProjectSaver(
      project('same'),
      'r0',
      async () => {
        writes++;
        return 'r1';
      },
      () => {},
    );
    saver.update({ ...project('same'), exportedAt: new Date().toISOString() });
    await saver.flush();
    expect(writes).toBe(0);
  });
  it('autosaves after edits pause without changing the indicator', async () => {
    const writes: string[] = [];
    const statuses: string[] = [];
    const saver: ProjectSaver = new ProjectSaver(
      project('old'),
      'r0',
      async (project) => {
        writes.push(project.fileGroups.group[0].content);
        return `r${writes.length}`;
      },
      () => statuses.push(saver.state.status),
    );
    for (const code of ['v', 'vo', 'voi', 'void']) {
      saver.update(project(code));
      await vi.advanceTimersByTimeAsync(SAVE_DELAY - 1);
    }
    expect(writes).toEqual([]);
    await vi.advanceTimersByTimeAsync(1);
    expect(writes).toEqual(['void']);
    await vi.advanceTimersByTimeAsync(QUIET_PERIOD);
    expect(saver.dirty).toBe(false);
    expect(saver.state.lastSavedAt).not.toBeNull();
    expect(new Set(statuses)).toEqual(new Set(['saved']));
  });
  it('saves continuous editing at least every MAX_SAVE_DELAY', async () => {
    let writes = 0;
    const saver = new ProjectSaver(project('0'), 'r0', async () => `r${++writes}`, () => {});
    for (let elapsed = 0; elapsed < MAX_SAVE_DELAY; elapsed += SAVE_DELAY / 2) {
      saver.update(project(`${elapsed + 1}`));
      await vi.advanceTimersByTimeAsync(SAVE_DELAY / 2);
    }
    expect(writes).toBe(1);
    expect(saver.state.status).toBe('saved');
  });
  it('shows a save that is still running once edits stop', async () => {
    const write = deferred<string>();
    const saver = new ProjectSaver(project('old'), 'r0', () => write.promise, () => {});
    saver.update(project('new'));
    await vi.advanceTimersByTimeAsync(QUIET_PERIOD - 1);
    expect(saver.state.status).toBe('saved');
    await vi.advanceTimersByTimeAsync(1);
    expect(saver.state.status).toBe('saving');
    expect(saver.unsaved).toBe(true);
    write.resolve('r1');
    await saver.flush();
    expect(saver.state.status).toBe('saved');
    expect(saver.unsaved).toBe(false);
  });
  it('keeps reporting a failed save and retries until one succeeds', async () => {
    let writes = 0;
    const saver = new ProjectSaver(
      project('old'),
      'r0',
      async () => {
        if (++writes <= 2) throw new Error('Offline.');
        return 'r1';
      },
      () => {},
    );
    saver.update(project('new'));
    await vi.advanceTimersByTimeAsync(SAVE_DELAY);
    expect(writes).toBe(1);
    expect(saver.state.status).toBe('error');
    expect(saver.state.errorMessage).toContain('Offline.');
    // Later edits neither hide the failure nor bypass the retry schedule.
    saver.update(project('newer'));
    await vi.advanceTimersByTimeAsync(SAVE_DELAY);
    expect(writes).toBe(1);
    expect(saver.state.status).toBe('error');
    await vi.advanceTimersByTimeAsync(RETRY_DELAYS[0] - SAVE_DELAY);
    expect(writes).toBe(2);
    await vi.advanceTimersByTimeAsync(RETRY_DELAYS[1]);
    expect(writes).toBe(3);
    expect(saver.state).toMatchObject({ status: 'saved', errorMessage: null });
    expect(saver.dirty).toBe(false);
  });
});
