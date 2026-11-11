/** Keeps `store.sfmBlockTypes` current for the workspace map: refetches when the forest or its geometry changes. */
import { useEffect } from 'react';
import { sfmApi } from '../services/api';
import { useWorkspaceStore } from '../store/workspaceStore';

export function useSfmBlockTypes(calculationId: string | null | undefined, geometryVersion: number): void {
  const setTypes = useWorkspaceStore((s) => s.setSfmBlockTypes);
  useEffect(() => {
    if (!calculationId) {
      setTypes({});
      return;
    }
    let live = true;
    sfmApi
      .getBlockTypes(calculationId)
      .then((t) => live && setTypes(t ?? {}))
      .catch(() => live && setTypes({})); // no SFM data (or offline): the map just shows no type labels
    return () => {
      live = false;
    };
  }, [calculationId, geometryVersion, setTypes]);
}
