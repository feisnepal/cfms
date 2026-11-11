import React from 'react';
import { FERTILITY_UNKNOWN_BADGE, resolveFertilityBand } from '../constants/nepaliLabels';

interface FertilityBadgeProps {
  /** The raw class from the soil data, e.g. `high` / `good` / `moderate` / `low` / `very_low`. */
  value?: string | null;
  /** Structural classes for the caller's layout. The band colour is applied separately. */
  className?: string;
}

/**
 * Soil fertility badge.
 *
 * The colour and the label both come from the one canonical band resolved out of
 * `constants/nepaliLabels`, keyed on the token the backend producer emits
 * (`app/core/soil_fertility.py::FertilityClass`).
 *
 * This replaced two inline chains that compared the raw value against 'Very High' /
 * 'High' / 'Medium' / 'Low' - labels the producer never writes - so all five bands fell
 * through to the final red arm and a `high` soil was displayed in the Very Low colour.
 * An unrecognised class is shown in neutral grey rather than in a band colour, so it is
 * visibly unclassified instead of being reported as the worst band.
 */
const FertilityBadge: React.FC<FertilityBadgeProps> = ({ value, className = '' }) => {
  const band = resolveFertilityBand(value);
  return (
    <span className={`${band ? band.badgeClass : FERTILITY_UNKNOWN_BADGE} ${className}`.trim()}>
      {band ? band.labelEn : value ?? ''}
    </span>
  );
};

export default FertilityBadge;
