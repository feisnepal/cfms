/**
 * The community forest user group's national database code, Schedule 11 of the Community Forestry Guidelines 2081.
 *
 * ``PPP/DDD/SS/LL/NNN``: province (3 letters) / division forest office (3 letters; a district can have more than one) /
 * sub-division office (2 letters, set by the division office) / local-level number (2 digits, from the schedule's list for the
 * division) / serial number of the handed-over community forest. The reference itself comes from the server
 * (`GET /calculations/forest-metadata/national-code-reference`); these are the pure helpers around it.
 */
export interface NationalCodeLocal {
  name: string;
  no: string;
  district: string;
}
export interface NationalCodeDivision {
  name: string;
  code: string;
  districts: string[];
  locals: NationalCodeLocal[];
}
export interface NationalCodeProvince {
  name: string;
  code: string;
  divisions: NationalCodeDivision[];
}

export interface NationalCodeParts {
  province: string;
  division: string;
  subDivision: string;
  localNo: string;
  serial: string;
}

export const EMPTY_PARTS: NationalCodeParts = { province: '', division: '', subDivision: '', localNo: '', serial: '' };

const CODE_RE = /^([A-Z]{3})\/([A-Z]{3})\/([A-Z]{2})\/(\d{2})\/(\d{1,4})$/;

/** The code from its parts; a part not yet chosen stays a blank run, so the preview shows what is missing. */
export function composeNationalCode(p: NationalCodeParts): string {
  return [
    p.province.toUpperCase() || '___',
    p.division.toUpperCase() || '___',
    p.subDivision.toUpperCase() || '__',
    p.localNo ? p.localNo.padStart(2, '0') : '__',
    p.serial.trim() || '___',
  ].join('/');
}

/** Every part chosen and well-formed: the code can be used. */
export function isCompleteNationalCode(p: NationalCodeParts): boolean {
  return CODE_RE.test(composeNationalCode(p));
}

/** Split an existing code into parts (to start the builder from what is already typed); null when it does not follow the format. */
export function parseNationalCode(code: string | null | undefined): NationalCodeParts | null {
  const m = CODE_RE.exec((code ?? '').trim());
  return m ? { province: m[1], division: m[2], subDivision: m[3], localNo: m[4], serial: m[5] } : null;
}

export function divisionsOf(ref: NationalCodeProvince[], provinceCode: string): NationalCodeDivision[] {
  return ref.find((p) => p.code === provinceCode)?.divisions ?? [];
}

export function localsOf(ref: NationalCodeProvince[], provinceCode: string, divisionCode: string): NationalCodeLocal[] {
  return divisionsOf(ref, provinceCode).find((d) => d.code === divisionCode)?.locals ?? [];
}

/** "Taplejung (TAP)"; for a district with several offices the district is named too: "Kailai Dhangadhi (KAI) - Kailai". */
export function divisionLabel(d: NationalCodeDivision): string {
  const district = d.districts.join(', ');
  return d.name === district || d.districts.length === 0 ? `${d.name} (${d.code})` : `${d.name} (${d.code}) - ${district}`;
}
