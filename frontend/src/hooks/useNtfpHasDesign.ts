import { useEffect, useState } from 'react';
import { ntfpApi } from '../services/api';
import { useWorkspaceStore } from '../store/workspaceStore';

/**
 * Whether the forest has an NTFP survey design: `undefined` while it is being read (or the read failed), so the caller can treat "not known" as "not shown".
 * Read again when the forest's geometry changes, as the plots layer does.
 */
export function useNtfpHasDesign(calculationId: string | undefined): boolean | undefined {
  const geometryVersion = useWorkspaceStore((s) => s.geometryVersion);
  const [has, setHas] = useState<boolean | undefined>(undefined);
  useEffect(() => {
    setHas(undefined);
    if (!calculationId) return;
    let alive = true;
    ntfpApi.getDesign(calculationId)
      .then((d) => { if (alive) setHas(!!d.design); })
      .catch(() => { /* not known: the row stays in the "More layers" band */ });
    return () => { alive = false; };
  }, [calculationId, geometryVersion]);
  return has;
}
