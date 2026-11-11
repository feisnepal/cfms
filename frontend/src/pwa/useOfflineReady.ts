import { useEffect, useState } from 'react';
import { offlineReadiness, onOfflineReadinessChange, type OfflineReadiness } from './offline';

/** Is this page saved on the phone for opening without a signal? 'unsupported' in development and in browsers without service workers. */
export function useOfflineReady(): OfflineReadiness {
  const [state, setState] = useState<OfflineReadiness>(offlineReadiness());
  useEffect(() => onOfflineReadinessChange(() => setState(offlineReadiness())), []);
  return state;
}
