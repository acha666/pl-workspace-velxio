import { useEffect, useState, useSyncExternalStore } from 'react';
import { EditorPage } from '../pages/EditorPage';
import { triggerDownloadVlx } from '../utils/vlxFile';
import { assetUrl } from './config';
import {
  initializeWorkspace,
  subscribeWorkspace,
  workspaceState,
  workspaceHasConflict,
  flushWorkspace,
} from './workspace';
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
  const label = {
    idle: 'Loading…',
    dirty: 'Unsaved changes',
    saving: 'Saving…',
    saved: 'Saved to workspace',
    error: 'Save failed',
  }[state.status];
  return (
    <div className="pl-workspace">
      <div className="pl-workspace-status">
        <span role="status" data-testid="pl-save-status">
          {label}
        </span>
        <button
          onClick={() => {
            void flushWorkspace().catch(() => {});
          }}
          disabled={state.status === 'saving' || workspaceHasConflict()}
        >
          Save now
        </button>
        <span className="pl-workspace-instruction">
          Wait for “Saved to workspace”, then return to PrairieLearn to submit.
        </span>
        <a href={assetUrl('pl-adapter-source.tar.gz')} download>
          Source &amp; licenses
        </a>
      </div>
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
