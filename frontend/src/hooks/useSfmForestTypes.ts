/** The 14 अनुसूची-१ forest types, fetched once per page and shared by every "Type N" tag. */
import { useEffect, useState } from 'react';
import { sfmApi, type SfmPrescription } from '../services/api';
import { loadForestTypes } from '../lib/sfmForestTypes';

export interface UseSfmForestTypes {
  types: Record<number, SfmPrescription> | null;
  /** True once the fetch failed; the tag then degrades to a plain label instead of a broken tooltip. */
  failed: boolean;
}

export function useSfmForestTypes(): UseSfmForestTypes {
  const [types, setTypes] = useState<Record<number, SfmPrescription> | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    loadForestTypes(() => sfmApi.getForestTypes())
      .then((t) => live && setTypes(t))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, []);

  return { types, failed };
}
