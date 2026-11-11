/** UserTypeFields — "who are you": four type cards, then only the fields that type asks for.
 *
 * Shared by Register and CompleteProfile. The parent owns the value; `typePayload` turns it into the
 * body the server expects and `typeReady` says whether every required field is filled.
 */
import React from 'react';
import { useT } from '../../i18n/hooks';
import type { Designation, UserType } from '../../types';

export interface TypeValue {
  userType: UserType | '';
  designation: Designation | '';
  subDivision: string;
  /** student / researcher / organization fields, keyed as the server stores them. */
  details: Record<string, string>;
}

export const EMPTY_TYPE: TypeValue = { userType: '', designation: '', subDivision: '', details: {} };

const TYPES: Array<[UserType, string, string, string]> = [
  ['official', 'auth.typeOfficial', 'auth.typeOfficialHint', '🌲'],
  ['student', 'auth.typeStudent', 'auth.typeStudentHint', '🎓'],
  ['researcher', 'auth.typeResearcher', 'auth.typeResearcherHint', '🔬'],
  ['organization', 'auth.typeOrganization', 'auth.typeOrganizationHint', '🤝'],
];

const DESIGNATIONS: Array<[Designation, string, string]> = [
  ['forest_guard', 'auth.designationForestGuard', '🛡️'],
  ['forester', 'auth.designationForester', '🌲'],
  ['ranger', 'auth.designationRanger', '🥾'],
  ['office', 'auth.designationOffice', '🏢'],
];

const LEVELS = ['university', 'college', 'campus'];
const ORG_KINDS = ['cfug', 'ngo', 'ingo', 'donor', 'government', 'company', 'other'];

/** [key, label, input kind, required] for each non-official type, in the order they are asked. */
const FIELDS: Record<Exclude<UserType, 'official'>, Array<[string, string, 'text' | 'email' | 'level' | 'orgKind', boolean]>> = {
  student: [
    ['level', 'auth.studentLevel', 'level', true],
    ['institution', 'auth.institution', 'text', true],
    ['programme', 'auth.programme', 'text', true],
    ['supervisor_name', 'auth.supervisorName', 'text', true],
    ['supervisor_email', 'auth.supervisorEmail', 'email', true],
  ],
  researcher: [
    ['affiliation', 'auth.affiliation', 'text', true],
    ['topic', 'auth.researchTopic', 'text', true],
    ['orcid', 'auth.orcid', 'text', false],
  ],
  organization: [
    ['organization_name', 'auth.organizationName', 'text', true],
    ['org_kind', 'auth.orgKind', 'orgKind', true],
    ['position', 'auth.position', 'text', true],
  ],
};

export const typeReady = (v: TypeValue): boolean => {
  if (!v.userType) return false;
  if (v.userType === 'official') return !!v.designation && v.subDivision.trim().length >= 2;
  return FIELDS[v.userType].every(([key, , , required]) => !required || (v.details[key] ?? '').trim().length > 0);
};

/** The part of the sign-up / profile body that depends on the type. */
export const typePayload = (v: TypeValue) =>
  v.userType === 'official'
    ? { user_type: v.userType, designation: v.designation as Designation, sub_division: v.subDivision.trim() }
    : { user_type: v.userType as UserType, details: v.details };

const input =
  'mt-1 block w-full rounded-xl border border-gray-200 bg-white/80 px-3.5 py-2.5 text-sm text-gray-900 placeholder-gray-400 shadow-sm transition focus:border-emerald-500 focus:outline-none focus:ring-4 focus:ring-emerald-100';
const label = 'block text-sm font-medium text-gray-700';

interface Props {
  value: TypeValue;
  onChange: (next: TypeValue) => void;
}

const UserTypeFields: React.FC<Props> = ({ value, onChange }) => {
  const t = useT();
  const set = (patch: Partial<TypeValue>) => onChange({ ...value, ...patch });
  const setDetail = (key: string, v: string) => set({ details: { ...value.details, [key]: v } });

  return (
    <div className="space-y-4">
      <div role="radiogroup" aria-label={t('auth.typeTitle')} className="grid grid-cols-2 gap-3">
        {TYPES.map(([id, nameKey, hintKey, icon]) => {
          const on = value.userType === id;
          return (
            <label
              key={id}
              className={`flex cursor-pointer flex-col gap-1 rounded-xl border px-3.5 py-3 transition focus-within:ring-4 focus-within:ring-emerald-100 ${
                on
                  ? 'border-emerald-500 bg-emerald-50 shadow-sm'
                  : 'border-gray-200 bg-white hover:border-emerald-300 hover:bg-emerald-50/40'
              }`}
            >
              <input type="radio" name="user_type" value={id} required checked={on} className="sr-only"
                onChange={() => set({ userType: id, details: {} })} />
              <span className="flex items-center gap-2 text-sm font-semibold text-gray-900">
                <span className="text-xl" aria-hidden="true">{icon}</span>
                {t(nameKey)}
              </span>
              <span className="text-xs text-gray-500">{t(hintKey)}</span>
            </label>
          );
        })}
      </div>

      {value.userType === 'official' && (
        <>
          <div role="radiogroup" aria-label={t('auth.designation')} className="grid grid-cols-2 gap-3">
            {DESIGNATIONS.map(([id, key, icon]) => {
              const on = value.designation === id;
              return (
                <label
                  key={id}
                  className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3.5 py-3 text-sm font-medium transition focus-within:ring-4 focus-within:ring-emerald-100 ${
                    on
                      ? 'border-emerald-500 bg-emerald-50 text-emerald-900 shadow-sm'
                      : 'border-gray-200 bg-white text-gray-700 hover:border-emerald-300 hover:bg-emerald-50/40'
                  }`}
                >
                  <input type="radio" name="designation" value={id} required checked={on} className="sr-only"
                    onChange={() => set({ designation: id })} />
                  <span className="text-xl" aria-hidden="true">{icon}</span>
                  {t(key)}
                </label>
              );
            })}
          </div>
          <div>
            <label htmlFor="sub_division" className={label}>{t('auth.subDivision')}</label>
            <input id="sub_division" name="sub_division" type="text" required minLength={2} className={input}
              placeholder={t('auth.subDivisionPlaceholder')} value={value.subDivision}
              onChange={(e) => set({ subDivision: e.target.value })} />
          </div>
        </>
      )}

      {value.userType && value.userType !== 'official' &&
        FIELDS[value.userType].map(([key, labelKey, kind, required]) => (
          <div key={key}>
            <label htmlFor={`detail_${key}`} className={label}>{t(labelKey)}</label>
            {kind === 'level' || kind === 'orgKind' ? (
              <select id={`detail_${key}`} required={required} className={input} value={value.details[key] ?? ''}
                onChange={(e) => setDetail(key, e.target.value)}>
                <option value="" disabled>{t('auth.choose')}</option>
                {(kind === 'level' ? LEVELS : ORG_KINDS).map((o) => (
                  <option key={o} value={o}>{t(`auth.${kind === 'level' ? 'level' : 'kind'}.${o}`)}</option>
                ))}
              </select>
            ) : (
              <input id={`detail_${key}`} type={kind} required={required} className={input}
                placeholder={key === 'orcid' ? '0000-0002-1825-0097' : undefined}
                value={value.details[key] ?? ''} onChange={(e) => setDetail(key, e.target.value)} />
            )}
          </div>
        ))}
      {value.userType === 'organization' && (
        <p className="text-xs text-gray-500">{t('auth.orgJoinHint')}</p>
      )}
      {(value.userType === 'student' || value.userType === 'researcher') && (
        <p className="text-xs text-gray-500">{t('auth.readOnlyHint')}</p>
      )}
    </div>
  );
};

export default UserTypeFields;
