import React, { useEffect, useState } from 'react';
import { useT } from '../../i18n/hooks';
import { nationalCodeApi, type NationalCodeMatch, type NationalCodeMatchCandidate } from '../../services/api';
import {
  EMPTY_PARTS, composeNationalCode, divisionLabel, divisionsOf, isCompleteNationalCode, localsOf, parseNationalCode,
  type NationalCodeParts, type NationalCodeProvince,
} from '../../lib/cfNationalCode';

/** The Schedule 11 table never changes within a session, so it is fetched once. */
let referenceCache: Promise<NationalCodeProvince[]> | null = null;
const loadReference = (): Promise<NationalCodeProvince[]> => {
  if (!referenceCache) {
    referenceCache = nationalCodeApi.reference().then((r) => r.provinces).catch((e) => {
      referenceCache = null; // a failed load can be retried
      throw e;
    });
  }
  return referenceCache;
};

const SELECT = 'w-full border border-gray-300 rounded px-2 py-1.5 text-sm bg-white';

/**
 * "Build from Schedule 11": picks Province, Division and Municipality from the schedule's own list and asks only for the two things the
 * schedule leaves to the user (the 2-letter sub-division code and the serial number). The full code is shown as it builds and written
 * into the field on "Use this code". Typing the code by hand stays possible; this only helps.
 */
export interface NationalCodeHints {
  province: string;
  palika: string;
  district: string;
  /** The form's own Serial Number: it is the code's last part. */
  serial: string;
}

const DEVANAGARI_DIGITS = '०१२३४५६७८९';
/** "१२" or "12" -> "12": digits only, either script, at most 4 (the code's serial width). */
export const serialDigits = (raw: string): string =>
  Array.from(raw ?? '')
    .map((c) => (DEVANAGARI_DIGITS.includes(c) ? String(DEVANAGARI_DIGITS.indexOf(c)) : c))
    .join('')
    .replace(/\D/g, '')
    .slice(0, 4);

export function NationalCodeBuilder({
  value, onUse, calculationId, hints,
}: { value: string; onUse: (code: string) => void; calculationId?: string; hints?: NationalCodeHints }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [ref, setRef] = useState<NationalCodeProvince[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [parts, setParts] = useState<NationalCodeParts>(EMPTY_PARTS);
  const [match, setMatch] = useState<NationalCodeMatch | null>(null);

  useEffect(() => {
    if (!open || ref) return;
    let live = true;
    loadReference().then((r) => live && setRef(r)).catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [open, ref]);

  // Start from a code that already follows the format, so correcting one part does not mean re-picking the others.
  // Opening the builder: from a code that already follows the format; otherwise preselected from the forest's own Province and
  // Municipality (the schedule lists each municipality under its own division office) and its Serial Number. A starting point only.
  useEffect(() => {
    if (!open) return;
    const existing = parseNationalCode(value);
    if (existing) {
      setParts(existing);
      setMatch(null);
      return;
    }
    const serial = serialDigits(hints?.serial ?? '');
    setParts({ ...EMPTY_PARTS, serial });
    setMatch(null);
    if (!calculationId || !hints || (!hints.province && !hints.palika)) return;
    let live = true;
    nationalCodeApi
      .match(calculationId, { province: hints.province, palika: hints.palika, district: hints.district })
      .then((m) => {
        if (!live) return;
        setMatch(m);
        setParts((p) => ({
          ...p,
          province: m.province_code ?? p.province,
          division: m.confidence === 'exact' || m.confidence === 'close' ? m.division_code ?? '' : p.division,
          localNo: m.confidence === 'exact' || m.confidence === 'close' ? m.local_no ?? '' : p.localNo,
        }));
      })
      .catch(() => live && setMatch(null)); // a failed lookup just leaves the pickers empty
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const pickCandidate = (c: NationalCodeMatchCandidate) =>
    setParts((p) => ({ ...p, province: c.province_code, division: c.division_code, localNo: c.local_no }));

  const set = (patch: Partial<NationalCodeParts>) => setParts((p) => ({ ...p, ...patch }));
  const divisions = ref ? divisionsOf(ref, parts.province) : [];
  const locals = ref ? localsOf(ref, parts.province, parts.division) : [];
  const preview = composeNationalCode(parts);

  return (
    <div className="mt-1">
      <button
        type="button"
        className="text-xs text-blue-700 hover:underline"
        data-testid="fm-code-builder-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? '▾' : '▸'} {t('forestMetadata.nationalCode.build')}
      </button>
      {open && (
        <div className="mt-2 p-3 border border-gray-200 rounded bg-gray-50" data-testid="fm-code-builder">
          <p className="text-xs text-gray-600 mb-2">{t('forestMetadata.nationalCode.hint')}</p>
          {failed && <p className="text-xs text-red-600 mb-2">{t('forestMetadata.nationalCode.loadFailed')}</p>}
          {match && match.confidence !== 'none' && (
            <div className="mb-2 text-xs" data-testid="fm-code-match">
              {(match.confidence === 'exact' || match.confidence === 'close') && (
                <p className={match.confidence === 'exact' ? 'text-green-700' : 'text-amber-700'}>
                  {t(`forestMetadata.nationalCode.match.${match.confidence}`, {
                    name: match.local_name ?? '', division: match.division_name ?? '', code: match.division_code ?? '', no: match.local_no ?? '',
                  })}
                </p>
              )}
              {match.confidence === 'ambiguous' && (
                <div className="text-amber-700">
                  <p>{t('forestMetadata.nationalCode.match.ambiguous')}</p>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {match.candidates.map((c) => (
                      <button
                        key={`${c.division_code}-${c.local_no}`}
                        type="button"
                        className="px-2 py-0.5 border border-amber-300 rounded bg-white hover:bg-amber-50"
                        data-testid={`fm-code-candidate-${c.division_code}`}
                        onClick={() => pickCandidate(c)}
                      >
                        {`${c.local_name} — ${c.district} (${c.division_code}) ${c.local_no}`}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            <label className="text-xs text-gray-600">
              {t('forestMetadata.nationalCode.province')}
              <select
                className={SELECT}
                data-testid="fm-code-province"
                value={parts.province}
                onChange={(e) => set({ province: e.target.value, division: '', localNo: '' })}
              >
                <option value="">—</option>
                {(ref ?? []).map((p) => (
                  <option key={p.code} value={p.code}>{`${p.name} (${p.code})`}</option>
                ))}
              </select>
            </label>
            <label className="text-xs text-gray-600">
              {t('forestMetadata.nationalCode.division')}
              <select
                className={SELECT}
                data-testid="fm-code-division"
                value={parts.division}
                disabled={!parts.province}
                onChange={(e) => set({ division: e.target.value, localNo: '' })}
              >
                <option value="">—</option>
                {divisions.map((d) => (
                  <option key={d.code} value={d.code}>{divisionLabel(d)}</option>
                ))}
              </select>
            </label>
            <label className="text-xs text-gray-600">
              {t('forestMetadata.nationalCode.municipality')}
              <select
                className={SELECT}
                data-testid="fm-code-local"
                value={parts.localNo}
                disabled={!parts.division}
                onChange={(e) => set({ localNo: e.target.value })}
              >
                <option value="">—</option>
                {locals.map((l) => (
                  <option key={`${l.district}-${l.no}`} value={l.no}>{`${l.no} — ${l.name}`}</option>
                ))}
              </select>
            </label>
            <label className="text-xs text-gray-600">
              {t('forestMetadata.nationalCode.subDivision')}
              <input
                className={SELECT}
                data-testid="fm-code-sub"
                maxLength={2}
                value={parts.subDivision}
                placeholder="AB"
                onChange={(e) => set({ subDivision: e.target.value.replace(/[^A-Za-z]/g, '').toUpperCase() })}
              />
            </label>
            <label className="text-xs text-gray-600">
              {t('forestMetadata.nationalCode.serial')}
              <input
                className={SELECT}
                data-testid="fm-code-serial"
                maxLength={4}
                inputMode="numeric"
                value={parts.serial}
                placeholder="001"
                onChange={(e) => set({ serial: e.target.value.replace(/\D/g, '') })}
              />
            </label>
          </div>
          <div className="mt-2 flex items-center gap-3">
            <code className="text-sm bg-white border border-gray-200 rounded px-2 py-1" data-testid="fm-code-preview">{preview}</code>
            <button
              type="button"
              className="px-3 py-1 text-sm rounded bg-blue-600 text-white disabled:bg-gray-300"
              data-testid="fm-code-use"
              disabled={!isCompleteNationalCode(parts)}
              onClick={() => {
                onUse(preview);
                setOpen(false);
              }}
            >
              {t('forestMetadata.nationalCode.use')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Whether the typed code follows Schedule 11. Advisory: a code issued before the schedule is reported, never refused. */
export function NationalCodeStatus({ value }: { value: string }) {
  const t = useT();
  const [problems, setProblems] = useState<string[] | null>(null);

  useEffect(() => {
    const code = value.trim();
    if (!code) {
      setProblems(null);
      return;
    }
    let live = true;
    const timer = window.setTimeout(() => {
      nationalCodeApi.check(code).then((r) => live && setProblems(r.ok ? [] : r.problems)).catch(() => live && setProblems(null));
    }, 350);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [value]);

  if (problems === null) return null;
  if (problems.length === 0) {
    return <p className="text-xs text-green-700 mt-1" data-testid="fm-code-status">✓ {t('forestMetadata.nationalCode.follows')}</p>;
  }
  return (
    <p className="text-xs text-amber-700 mt-1" data-testid="fm-code-status">
      ⚠ {problems.map((p) => t(`forestMetadata.nationalCode.problem.${p}`)).join(' · ')}
    </p>
  );
}
