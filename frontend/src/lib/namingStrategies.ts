const NEPALI_DIGITS: Record<string, string> = {
  '0': '०', '1': '१', '2': '२', '3': '३', '4': '४',
  '5': '५', '6': '६', '7': '७', '8': '८', '9': '९',
};

export function toNepaliNumeral(n: number): string {
  if (n < 0) throw new RangeError(`Negative numbers not supported: ${n}`);
  return String(n).split('').map((ch) => NEPALI_DIGITS[ch] ?? ch).join('');
}

export function isNepaliNumeral(s: string): boolean {
  return /^[०१२३४५६७८९]+$/.test(s);
}

export function fromNepaliNumeral(s: string): number {
  const arabic = s.split('').map((ch) => {
    const entry = Object.entries(NEPALI_DIGITS).find(([, v]) => v === ch);
    return entry ? entry[0] : ch;
  }).join('');
  return parseInt(arabic, 10);
}

export interface SequenceGenerator {
  next(): number;
  peek(): number;
  reset(startAt?: number): void;
}

export function createSequenceGenerator(startAt: number = 1): SequenceGenerator {
  let current = startAt;
  return {
    next: () => current++,
    peek: () => current,
    reset: (s?: number) => { current = s ?? startAt; },
  };
}

export interface ValidationResult {
  readonly valid: boolean;
  readonly errorKey?: string;
  readonly errorParams?: Record<string, string>;
}

export type NameValidator = (name: string, existingNames: Set<string>) => ValidationResult;

export const NameValidators = {
  notEmpty: (name: string): ValidationResult => {
    if (!name || name.trim().length === 0) {
      return { valid: false, errorKey: 'geometry.edit.no_name_empty' };
    }
    return { valid: true };
  },

  maxLength: (max: number) => (name: string): ValidationResult => {
    if (name.length > max) {
      return {
        valid: false,
        errorKey: 'geometry.edit.name_too_long',
        errorParams: { max: String(max) },
      };
    }
    return { valid: true };
  },

  notDuplicate: (name: string, existingNames: Set<string>): ValidationResult => {
    if (existingNames.has(name.trim())) {
      return { valid: false, errorKey: 'geometry.edit.duplicate_name', errorParams: { name } };
    }
    return { valid: true };
  },

  matches: (pattern: RegExp, errorKey: string) => (name: string): ValidationResult => {
    if (!pattern.test(name.trim())) {
      return { valid: false, errorKey, errorParams: { pattern: pattern.source } };
    }
    return { valid: true };
  },

  noSpecialChars: (name: string): ValidationResult => {
    if (!/^[\w\s\-_\u0900-\u097F]+$/.test(name)) {
      return {
        valid: false,
        errorKey: 'geometry.edit.invalid_name_format',
        errorParams: { pattern: 'Letters, numbers, spaces, hyphens, underscores, and Nepali characters only' },
      };
    }
    return { valid: true };
  },
} as const;

export interface NamingStrategy {
  readonly id: string;
  readonly label: string;
  readonly labelNp: string;
  readonly isCompartment: boolean;
  generateDefaultName(index: number, useNepali?: boolean): string;
  generateName(prefix: string, index: number, useNepali?: boolean): string;
  parseName(name: string): { prefix: string; number: number } | null;
  nextAvailableIndex(existingNames: Iterable<string>): number;
  getValidator(): NameValidator;
  readonly pattern: string;
  readonly patternNp: string;
}

export class BlockNamingStrategy implements NamingStrategy {
  readonly id = 'block';
  readonly label = 'Block';
  readonly labelNp = 'ब्लक';
  readonly isCompartment = false;
  readonly pattern = 'B{N}';
  readonly patternNp = 'ब्लक {N}';

  private readonly _prefixEn = 'Block ';
  private readonly _prefixNp = 'ब्लक ';

  generateDefaultName(index: number, useNepali?: boolean): string {
    return useNepali
      ? `${this._prefixNp}${toNepaliNumeral(index)}`
      : `B${index}`; // owner 2026-10-11: B1, B2 ... like C1, C2 for compartments
  }

  generateName(prefix: string, index: number, useNepali?: boolean): string {
    return useNepali
      ? `${prefix} ${toNepaliNumeral(index)}`
      : `${prefix} ${index}`;
  }

  parseName(name: string): { prefix: string; number: number } | null {
    const serial = name.match(/^B(\d+)$/);
    if (serial) return { prefix: 'B', number: parseInt(serial[1], 10) };

    const enMatch = name.match(/^(Block\s+)(\d+)$/i);
    if (enMatch) return { prefix: enMatch[1].trim(), number: parseInt(enMatch[2], 10) };

    const npMatch = name.match(/^(ब्लक\s+)([०१२३४५६७८९]+)$/);
    if (npMatch) return { prefix: npMatch[1].trim(), number: fromNepaliNumeral(npMatch[2]) };

    const genericMatch = name.match(/^(.+?)\s+(\d+)$/);
    if (genericMatch) return { prefix: genericMatch[1], number: parseInt(genericMatch[2], 10) };

    return null;
  }

  nextAvailableIndex(existingNames: Iterable<string>): number {
    let max = 0;
    for (const name of existingNames) {
      const parsed = this.parseName(name);
      if (parsed && parsed.number > max) {
        max = parsed.number;
      }
    }
    return max + 1;
  }

  getValidator(): NameValidator {
    return (name: string, existingNames: Set<string>): ValidationResult => {
      for (const validator of this._validators) {
        const result = validator(name, existingNames);
        if (!result.valid) return result;
      }
      return { valid: true };
    };
  }

  private readonly _validators: NameValidator[] = [
    (n) => NameValidators.notEmpty(n),
    (n) => NameValidators.maxLength(100)(n),
    (n, ex) => NameValidators.notDuplicate(n, ex),
    (n) => NameValidators.noSpecialChars(n),
  ];
}

export class CompartmentNamingStrategy implements NamingStrategy {
  readonly id = 'compartment';
  readonly label = 'Compartment';
  readonly labelNp = 'कम्पार्टमेन्ट';
  readonly isCompartment = true;
  readonly pattern = 'C{N}';
  readonly patternNp = 'कम्पार्टमेन्ट {N}';

  generateDefaultName(index: number, useNepali?: boolean): string {
    return useNepali
      ? `${this.labelNp} ${toNepaliNumeral(index)}`
      : `C${index}`;
  }

  generateName(prefix: string, index: number, useNepali?: boolean): string {
    return useNepali
      ? `${prefix} ${toNepaliNumeral(index)}`
      : `${prefix}${index}`;
  }

  parseName(name: string): { prefix: string; number: number } | null {
    const shortMatch = name.match(/^C\s*(\d+)$/i);
    if (shortMatch) return { prefix: 'C', number: parseInt(shortMatch[1], 10) };

    const longMatch = name.match(/^(Compartment|कम्पार्टमेन्ट)\s+(\d+|[०१२३४५६७८९]+)$/i);
    if (longMatch) {
      const numStr = longMatch[2];
      const num = isNepaliNumeral(numStr) ? fromNepaliNumeral(numStr) : parseInt(numStr, 10);
      return { prefix: longMatch[1], number: num };
    }

    const subMatch = name.match(/^SC\s*(\d+)$/i);
    if (subMatch) return { prefix: 'SC', number: parseInt(subMatch[1], 10) };

    return null;
  }

  nextAvailableIndex(existingNames: Iterable<string>): number {
    let max = 0;
    for (const name of existingNames) {
      const parsed = this.parseName(name);
      if (parsed && parsed.number > max) {
        max = parsed.number;
      }
    }
    return max + 1;
  }

  getValidator(): NameValidator {
    return (name: string, existingNames: Set<string>): ValidationResult => {
      for (const validator of this._validators) {
        const result = validator(name, existingNames);
        if (!result.valid) return result;
      }
      return { valid: true };
    };
  }

  private readonly _validators: NameValidator[] = [
    (n) => NameValidators.notEmpty(n),
    (n) => NameValidators.maxLength(100)(n),
    (n, ex) => NameValidators.notDuplicate(n, ex),
    (n) => NameValidators.matches(/^[A-Za-z\u0900-\u097F][\w\s\-_\u0900-\u097F]*\d+$/,
      'geometry.edit.invalid_name_format')(n),
  ];
}

const STRATEGIES: Record<string, NamingStrategy> = {
  block: new BlockNamingStrategy(),
  compartment: new CompartmentNamingStrategy(),
};

export function getNamingStrategy(id: 'block' | 'compartment'): NamingStrategy {
  const strategy = STRATEGIES[id];
  if (!strategy) throw new Error(`Unknown naming strategy: ${id}`);
  return strategy;
}

export function resolveNamingStrategy(isCompartment: boolean): NamingStrategy {
  return isCompartment ? STRATEGIES.compartment : STRATEGIES.block;
}

export function registerNamingStrategy(strategy: NamingStrategy): void {
  STRATEGIES[strategy.id] = strategy;
}

/**
 * The default pattern a sub-unit divide uses when the caller specifies none (FS-4a.2):
 * `{parent_name}-SC{index}` for a sub-compartment, `{parent_name}-SB{index}` for a
 * sub-block. Mirrors `app.core.naming_strategies.sub_unit_naming_pattern`.
 */
export function subUnitNamingPattern(isCompartment: boolean): string {
  return isCompartment ? '{parent_name}-SC{index}' : '{parent_name}-SB{index}';
}

/**
 * Render the pattern above for one child without the caller knowing the template
 * syntax -- e.g. `subUnitSerial(false, 'B1', 1)` -> `'B1-SB1'`.
 */
export function subUnitSerial(
  isCompartment: boolean,
  parentName: string,
  index: number
): string {
  return subUnitNamingPattern(isCompartment)
    .replace('{parent_name}', parentName)
    .replace('{index}', String(index));
}
