import { Alert, Button, Card, Typography } from 'antd';
import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { getUnsampledUnits, UnitSizeCandidate, UnitSizeSummary } from '../../services/api';
import UnitSizeTable from '../sampling/UnitSizeTable';

const { Text, Paragraph } = Typography;

interface UnsampledUnitsNoteProps {
  fieldInventoryId?: string | null;
  reviewPct?: number;
  onLinkToSampling?: () => void;
}

/**
 * P8 - the field-inventory note.
 *
 * A block gets an inventory summary only if it was sampled, so an unsampled unit
 * simply vanishes and the user counts 21 blocks where the forest has 24, with
 * nothing explaining the gap. This names them. A bare count would just be the same
 * silence in a new place, so the units are listed with their reason.
 *
 * Read-only, and it reuses the same band classifier as the sampling review, so the
 * two surfaces cannot drift into telling the user two different things about the
 * same polygon.
 */
export const UnsampledUnitsNote: React.FC<UnsampledUnitsNoteProps> = ({
  fieldInventoryId,
  reviewPct,
  onLinkToSampling,
}) => {
  const { t } = useTranslation();
  const [units, setUnits] = useState<UnitSizeCandidate[]>([]);
  const [summary, setSummary] = useState<UnitSizeSummary | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!fieldInventoryId) {
      setUnits([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await getUnsampledUnits(fieldInventoryId, reviewPct);
      setUnits(data.unsampled_units || []);
      setSummary(data.summary || null);
      setTotal(data.total_units ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [fieldInventoryId, reviewPct]);

  useEffect(() => {
    void load();
  }, [load]);

  // Nothing to say when there is no inventory, no error, and nothing missing. An
  // always-on empty card is noise on the common case where every unit was sampled.
  if (!fieldInventoryId || (!loading && !error && units.length === 0)) {
    return null;
  }

  return (
    <Card
      size="small"
      title={t('sampling.unsampled.title')}
      style={{ marginBottom: 12 }}
    >
      {total != null && units.length > 0 && (
        <Text type="secondary">
          {t('sampling.unsampled.countLine', {
            unsampled: units.length,
            total,
          })}
        </Text>
      )}
      <Paragraph type="secondary" style={{ marginTop: 4 }}>
        {t('sampling.unsampled.description')}
      </Paragraph>
      {error && (
        <Alert
          type="warning"
          showIcon
          message={t('sampling.unitReview.error')}
          description={error}
          style={{ marginBottom: 8 }}
        />
      )}
      <UnitSizeTable
        candidates={units}
        summary={summary || undefined}
        loading={loading}
        error={null}
        onLinkToSampling={onLinkToSampling}
      />
      {onLinkToSampling && units.length > 0 && (
        <Button size="small" type="link" onClick={onLinkToSampling} style={{ paddingInline: 0 }}>
          {t('sampling.unsampled.seeSampling')}
        </Button>
      )}
    </Card>
  );
};

export default UnsampledUnitsNote;
