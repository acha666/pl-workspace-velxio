import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { VlxPayload } from '../../utils/vlxFile';

const stores = vi.hoisted(() => ({
  project: {} as VlxPayload,
  changed: () => {},
  stop: vi.fn(),
  setState: vi.fn(),
}));
vi.mock('../../lib/apiBase', () => ({ getApiBase: () => '/workspace/test/api' }));
vi.mock('../../lib/proSaveAction', () => ({ installSaveActionImpl: vi.fn() }));
vi.mock('../../hooks/useAutoSaveProject', () => ({ installAutoSaveImpl: vi.fn() }));
vi.mock('../../store/useEditorStore', () => ({
  useEditorStore: {
    subscribe: (listener: () => void) => {
      stores.changed = listener;
    },
  },
}));
vi.mock('../../store/useSimulatorStore', () => ({
  useSimulatorStore: {
    subscribe: vi.fn(),
    getState: () => ({ stopSimulation: stores.stop }),
    setState: stores.setState,
  },
}));
vi.mock('../../utils/vlxFile', () => ({
  importVlxFile: vi.fn(),
  buildVlxPayload: () => stores.project,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((accept) => {
    resolve = accept;
  });
  return { promise, resolve };
}

const fetchMock = vi.fn<typeof fetch>();
let revision: string;

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
  vi.clearAllMocks();
  vi.stubGlobal('window', { addEventListener: vi.fn() });
  vi.stubGlobal('document', { addEventListener: vi.fn(), visibilityState: 'visible' });
  vi.stubGlobal('fetch', fetchMock);
  revision = 'r0';
  stores.project = {
    format: 'velxio-project',
    version: 1,
    exportedAt: '',
    boards: [{ id: 'uno', boardKind: 'arduino-uno', x: 0, y: 0, activeFileGroupId: 'uno' }],
    activeBoardId: 'uno',
    components: [],
    wires: [],
    fileGroups: { uno: [{ name: 'sketch.ino', content: 'void setup() {} void loop() {}' }] },
  };
  fetchMock.mockImplementation(async (_url, options) => {
    if (options?.method === 'PUT') revision = 'r1';
    return Response.json({ project: stores.project, revision });
  });
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('workspace lifecycle', () => {
  it('imports once without overwriting the seed on mount', async () => {
    const workspace = await import('../workspace');
    await Promise.all([workspace.initializeWorkspace(), workspace.initializeWorkspace()]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/workspace/test/api/pl-workspace');
    expect(workspace.workspaceState().status).toBe('saved');
  });

  it('saves immediately when the student leaves the workspace', async () => {
    const workspace = await import('../workspace');
    await workspace.initializeWorkspace();
    stores.project = { ...stores.project, name: 'Edited just before leaving' };
    stores.changed();
    const [, blur] = vi.mocked(window.addEventListener).mock.calls.find(([type]) => type === 'blur')!;
    (blur as () => void)();
    expect(fetchMock.mock.calls.map(([, options]) => options?.method)).toEqual(['GET', 'PUT']);
    await workspace.flushWorkspace();
    expect(workspace.workspaceState().lastSavedAt).not.toBeNull();
  });

  it('saves an edit made while checking the remote revision before continuing', async () => {
    const workspace = await import('../workspace');
    await workspace.initializeWorkspace();
    const started = deferred<void>();
    const response = deferred<Response>();
    fetchMock.mockImplementationOnce(() => {
      started.resolve();
      return response.promise;
    });
    const verification = workspace.verifyWorkspace();
    await started.promise;
    stores.project = { ...stores.project, name: 'Circuit edited during the check' };
    stores.changed();
    response.resolve(Response.json({ revision: 'r0' }));
    await verification;
    expect(fetchMock.mock.calls.map(([, options]) => options?.method)).toEqual([
      'GET',
      'GET',
      'PUT',
      'GET',
    ]);
    expect(workspace.workspaceState().status).toBe('saved');
  });

  it('rejects a stale tab before compilation and preserves its local snapshot', async () => {
    const workspace = await import('../workspace');
    await workspace.initializeWorkspace();
    revision = 'another-tab';
    await expect(workspace.prepareWorkspaceCompile(stores.project.fileGroups.uno)).rejects.toThrow(
      'another tab',
    );
    expect(workspace.workspaceHasConflict()).toBe(true);
    expect(stores.stop).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls.every(([, options]) => options?.method === 'GET')).toBe(true);
  });

  it('invalidates a compile result after the source changes', async () => {
    const workspace = await import('../workspace');
    await workspace.initializeWorkspace();
    const stillCurrent = await workspace.prepareWorkspaceCompile(stores.project.fileGroups.uno);
    expect(stillCurrent()).toBe(true);
    stores.project = {
      ...stores.project,
      fileGroups: { uno: [{ name: 'sketch.ino', content: '// edited during compilation' }] },
    };
    stores.changed();
    expect(stillCurrent()).toBe(false);
    expect(stores.stop).toHaveBeenCalledOnce();
    expect(stores.setState).toHaveBeenCalledOnce();
  });
});
