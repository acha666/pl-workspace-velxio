import { describe, it, expect } from 'vitest';
import { ProjectSaver, WorkspaceConflict } from '../ProjectSaver';
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
});
