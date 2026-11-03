import { getApiBase } from '../lib/apiBase';
import { installSaveActionImpl } from '../lib/proSaveAction';
import { installAutoSaveImpl, type AutoSaveState } from '../hooks/useAutoSaveProject';
import { useEditorStore } from '../store/useEditorStore';
import { useSimulatorStore } from '../store/useSimulatorStore';
import { buildVlxPayload, importVlxFile, type VlxPayload } from '../utils/vlxFile';
import { ProjectSaver, WorkspaceConflict, projectKey } from './ProjectSaver';

let saver: ProjectSaver | null = null;
let initialization: Promise<void> | null = null;
const listeners = new Set<() => void>();
let sourceVersion = 0;

function emit(): void {
  for (const listener of listeners) listener();
}
export function subscribeWorkspace(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
const loading: AutoSaveState = { status: 'idle', lastSavedAt: null, errorMessage: null };
export function workspaceState(): AutoSaveState {
  return saver?.state ?? loading;
}
export function workspaceHasConflict(): boolean {
  return saver?.conflict ?? false;
}

async function request<T>(method: 'GET' | 'PUT', body?: unknown): Promise<T> {
  const response = await fetch(`${getApiBase()}/pl-workspace`, {
    method,
    credentials: 'same-origin',
    cache: 'no-store',
    signal: AbortSignal.timeout(30_000),
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      typeof data?.detail === 'string'
        ? data.detail
        : `Workspace request failed (${response.status}).`;
    if (response.status === 409) throw new WorkspaceConflict(detail);
    throw new Error(detail);
  }
  return data as T;
}

/** Mount the original editor only after the native project imports successfully. */
export function initializeWorkspace(): Promise<void> {
  return (initialization ??= (async () => {
    const loaded = await request<{ project: VlxPayload; revision: string }>('GET');
    if (!loaded?.project || typeof loaded.revision !== 'string')
      throw new Error('Invalid workspace response.');
    await importVlxFile(
      new File([JSON.stringify(loaded.project)], 'project.vlx', { type: 'application/json' }),
    );
    const snapshot = () => buildVlxPayload({ name: loaded.project.name });
    const initial = snapshot();
    let previousKey = projectKey(initial);
    let previousSources = JSON.stringify(initial.fileGroups);
    saver = new ProjectSaver(
      initial,
      loaded.revision,
      async (project, revision) => {
        const result = await request<{ revision: string }>('PUT', { project, revision });
        if (typeof result?.revision !== 'string')
          throw new Error('The server did not confirm the saved project.');
        return result.revision;
      },
      emit,
    );

    const changed = () => {
      const next = snapshot();
      const key = projectKey(next);
      if (key === previousKey) return;
      previousKey = key;
      const sources = JSON.stringify(next.fileGroups);
      if (sources !== previousSources) {
        previousSources = sources;
        sourceVersion++;
        // Match the current code after an edit; never run yesterday's binary
        // after a failed compile. Compilation and execution remain upstream.
        useSimulatorStore.getState().stopSimulation();
        useSimulatorStore.setState((state) => ({
          compiledHex: null,
          boards: state.boards.map((board) => ({ ...board, compiledProgram: null })),
        }));
      }
      saver!.update(next);
    };
    useEditorStore.subscribe(changed);
    useSimulatorStore.subscribe(changed);
    installSaveActionImpl(() => {
      void flushWorkspace().catch(() => {});
    });
    installAutoSaveImpl((setState) => {
      setState(workspaceState());
      return subscribeWorkspace(() => setState(workspaceState()));
    });
    // Save as soon as the student leaves for PrairieLearn instead of waiting
    // for the autosave delay.
    const saveOnLeave = () => {
      if (saver?.unsaved) void flushWorkspace().catch(() => {});
    };
    window.addEventListener('blur', saveOnLeave);
    window.addEventListener('pagehide', saveOnLeave);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') saveOnLeave();
    });
    window.addEventListener('beforeunload', (event) => {
      if (saver?.unsaved) {
        event.preventDefault();
        event.returnValue = '';
      }
    });
    emit();
  })());
}

export async function flushWorkspace(): Promise<void> {
  if (!saver) throw new Error('The workspace has not loaded.');
  await saver.flush();
}

/** A clean tab must detect a newer saved project before it compiles or runs. */
export async function verifyWorkspace(): Promise<void> {
  await flushWorkspace();
  const revision = saver!.revision;
  const remote = await request<{ revision: string }>('GET');
  if (saver!.revision !== revision || saver!.dirty) return verifyWorkspace();
  if (remote.revision !== revision) {
    saver!.markConflict();
    useSimulatorStore.getState().stopSimulation();
    throw new WorkspaceConflict('This workspace changed in another tab. Reload before running.');
  }
}

export async function prepareWorkspaceCompile(
  files: Array<{ name: string; content: string }>,
): Promise<() => boolean> {
  const version = sourceVersion;
  await verifyWorkspace();
  const savedFiles = Object.values(saver!.project.fileGroups).flat();
  if (sourceVersion !== version || JSON.stringify(files) !== JSON.stringify(savedFiles)) {
    throw new Error('The code changed before compilation. Run again.');
  }
  return () => !saver!.conflict && sourceVersion === version;
}
