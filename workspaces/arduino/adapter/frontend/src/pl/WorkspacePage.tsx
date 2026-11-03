import { useEffect, useState, useSyncExternalStore } from 'react';
import { EditorPage } from '../pages/EditorPage';
import { triggerDownloadVlx } from '../utils/vlxFile';
import { initializeWorkspace, subscribeWorkspace, workspaceState } from './workspace';
import './workspace.css';

export function WorkspacePage() {
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const state = useSyncExternalStore(subscribeWorkspace, workspaceState);
  useEffect(() => {
    void initializeWorkspace()
      .then(() => setReady(true))
      .catch((error) => setLoadError(String(error.message ?? error)));
  }, []);
  if (!ready)
    return (
      <main className="pl-workspace-loading">
        <h1>Velxio workspace</h1>
        <p role={loadError ? 'alert' : 'status'}>
          {loadError ? `Could not load project.vlx. ${loadError}` : 'Loading your saved project…'}
        </p>
        {loadError && <button onClick={() => window.location.reload()}>Retry</button>}
      </main>
    );
  // The file explorer's save icon shows this state; announce the same changes.
  const label = {
    idle: 'Loading…',
    saved: 'Saved to workspace',
    dirty: 'Unsaved changes',
    saving: 'Saving…',
    error: 'Save failed',
  }[state.status];
  return (
    <div className="pl-workspace">
      <span className="pl-visually-hidden" role="status" data-testid="pl-save-status">
        {label}
      </span>
      {state.errorMessage && (
        <div className="pl-workspace-error" role="alert">
          {state.errorMessage}{' '}
          <button onClick={() => triggerDownloadVlx({ name: 'workspace-recovery' })}>
            Export local project
          </button>
        </div>
      )}
      <EditorPage />
    </div>
  );
}
