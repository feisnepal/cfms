import { useQuery } from '@tanstack/react-query';
import { dbhClassApi } from '../services/api';
import { DBH_CLASS_LABEL_KEYS, DbhClassDef, DEFAULT_SYSTEM } from '../constants/dbhClasses';

/** A class as the API sends it: snake_case, straight out of `dbh_class_systems`. */
export interface ApiDbhClass {
  key: string;
  lower: number;
  upper: number | null;
  label_en: string;
  label_np: string;
  stand_type: string | null;
}

export interface ApiDbhSystem {
  system_name: string;
  class_count: number;
  classes: ApiDbhClass[];
}

export function useDbhSystems() {
  return useQuery<ApiDbhSystem[]>({
    queryKey: ['dbh-classes', 'systems'],
    queryFn: () => dbhClassApi.listSystems(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useDbhSystem(systemName: string | null) {
  return useQuery<ApiDbhSystem>({
    queryKey: ['dbh-classes', 'systems', systemName],
    queryFn: () => dbhClassApi.getSystem(systemName!),
    enabled: !!systemName,
    staleTime: 5 * 60 * 1000,
  });
}

/** Map one API class into the shape the components already consume. */
export function toDbhClassDef(cls: ApiDbhClass): DbhClassDef {
  return {
    key: cls.key,
    lower: Number(cls.lower),
    // `upper: null` means "no upper bound" for the top class. It is preserved as
    // null rather than coerced, because `Infinity` would render as a number in a
    // range label and `undefined` would read as "missing" -- neither is what the
    // database said.
    upper: cls.upper === null || cls.upper === undefined ? null : Number(cls.upper),
    labelEn: cls.label_en,
    labelNp: cls.label_np,
    labelKey: DBH_CLASS_LABEL_KEYS[cls.key],
    standType: cls.stand_type,
  };
}

/**
 * The class list for a system, ready to render.
 *
 * `guideline_2061` by default, because that is the system the Results tables are
 * written in. Callers pass a name when they mean another.
 *
 * Returns an **empty array** while loading or on error, deliberately. There is
 * no bundled fallback list any more, and that is the point: a silent stale copy
 * is how a per-hectare figure gets computed against boundaries the database no
 * longer uses. An empty list makes the caller render nothing, which is visible;
 * a stale copy renders confidently wrong numbers, which is not. Tables are
 * written so an empty class list shows an empty table rather than throwing.
 */
export function useDbhClassConfig(systemName: string = DEFAULT_SYSTEM): DbhClassDef[] {
  const { data } = useDbhSystem(systemName);
  return (data?.classes ?? []).map(toDbhClassDef);
}

/** `true` while the class list for a system is still loading. */
export function useDbhClassConfigLoading(systemName: string = DEFAULT_SYSTEM): boolean {
  return useDbhSystem(systemName).isLoading;
}

/**
 * The label to render for a class.
 *
 * A curated i18n key when there is one, and otherwise **the label the API sent**.
 * That fallback matters: eight of the classes across the five systems have no
 * i18n key, and the previous code reached for `'dbhClass.seedling'` as a default,
 * which is a key that does not exist in either bundle. `t()` then returned the
 * key string itself, so those tables rendered the literal text
 * `dbhClass.seedling` instead of a class name. Using the API's own label is both
 * correct and available, so the guess is gone rather than merely corrected.
 */
export function resolveClassLabel(
  cls: DbhClassDef,
  t: (key: string) => string,
  isNepali: boolean,
): string {
  if (cls.labelKey) return t(cls.labelKey);
  return isNepali ? cls.labelNp : cls.labelEn;
}
