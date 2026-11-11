import { useQuery } from '@tanstack/react-query';
import { dbhClassApi } from '../services/api';

export function useDbhClassify(dbh: number | null, system: string = 'guideline_2061') {
  return useQuery({
    queryKey: ['dbh-classes', 'classify', dbh, system],
    queryFn: () => dbhClassApi.classifyDbh(dbh!, system),
    enabled: dbh !== null && dbh !== undefined && !isNaN(dbh),
    staleTime: 60 * 60 * 1000,
    retry: false,
  });
}
