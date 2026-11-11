import { describe, it, expect } from 'vitest';
import { useWorkspaceStore } from '../workspaceStore';

describe('Hover info switch', () => {
  it('is on by default and can be turned off and on', () => {
    expect(useWorkspaceStore.getState().showHoverInfo).toBe(true);
    useWorkspaceStore.getState().setShowHoverInfo(false);
    expect(useWorkspaceStore.getState().showHoverInfo).toBe(false);
    useWorkspaceStore.getState().setShowHoverInfo(true);
    expect(useWorkspaceStore.getState().showHoverInfo).toBe(true);
  });
});
