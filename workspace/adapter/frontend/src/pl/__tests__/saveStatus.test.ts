import { describe, expect, it } from 'vitest';
import type { AutoSaveState } from '../../hooks/useAutoSaveProject';
import { saveStatusLabel } from '../saveStatus';

const state = (status: AutoSaveState['status'], lastSavedAt: number | null = null) => ({
  status,
  lastSavedAt,
  errorMessage: null,
});

describe('save status text', () => {
  it('shows the last save time without changing within a minute', () => {
    const early = saveStatusLabel(state('saved', new Date(2026, 9, 19, 17, 2, 5).getTime()));
    const late = saveStatusLabel(state('saved', new Date(2026, 9, 19, 17, 2, 55).getTime()));
    expect(early).toMatch(/^Saved \d/);
    expect(late).toBe(early);
    expect(saveStatusLabel(state('saved'))).toBe('Saved');
  });
  it('names overdue and failed saves', () => {
    expect(saveStatusLabel(state('saving', 1))).toBe('Saving…');
    expect(saveStatusLabel(state('dirty', 1))).toBe('Unsaved changes');
    expect(saveStatusLabel(state('error', 1))).toBe('Not saved');
  });
});
