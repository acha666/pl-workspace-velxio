import type { AutoSaveState } from '../hooks/useAutoSaveProject';

/**
 * Quiet text beside the save icon. The time has minute precision, so
 * autosaves while the student types change it at most once a minute.
 */
export function saveStatusLabel(state: AutoSaveState): string {
  switch (state.status) {
    case 'error':
      return 'Not saved';
    case 'saving':
      return 'Saving…';
    case 'dirty':
      return 'Unsaved changes';
    default:
      if (state.lastSavedAt === null) return 'Saved';
      return `Saved ${new Date(state.lastSavedAt).toLocaleTimeString([], {
        hour: 'numeric',
        minute: '2-digit',
      })}`;
  }
}
