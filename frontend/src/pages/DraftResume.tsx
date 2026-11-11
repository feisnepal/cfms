/** DraftResume — resume draft forest creation flow using MapCreationWizard. */
import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import MapCreationWizard from '../components/MapCreation/MapCreationWizard';
import { forestApi, API_BASE_URL } from '../services/api';
import { useBoundaryPreview } from '../contexts/BoundaryPreviewContext';
import { useT } from '../i18n/hooks';
import { apiErrorText } from '../lib/apiErrorText';

interface DraftData {
  id: string;
  forest_name: string;
  draft_data: {
    islands: Array<{
      id: string;
      geometry: any;
      area: number;
    }>;
    mode: string;
    islands_count: number;
    total_area: number;
  };
  created_at: string;
  updated_at: string;
}

export default function DraftResume() {
  const { draftId } = useParams<{ draftId: string }>();
  const navigate = useNavigate();
  const t = useT();
  const { reviewBoundary } = useBoundaryPreview();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<DraftData | null>(null);
  const [forestName, setForestName] = useState('');

  useEffect(() => {
    loadDraft();
  }, [draftId]);

  const loadDraft = async () => {
    if (!draftId) return;
    
    try {
      setLoading(true);
      const data = await forestApi.getDraft(draftId);
      setDraft(data);
      setForestName(data.forest_name || t('uploads.unnamedForest'));
    } catch (err: any) {
      setError(apiErrorText(err, t('workspace.errorLoadingDraft')));
    } finally {
      setLoading(false);
    }
  };

  const handleComplete = async (data: {
    outerBoundary: any;
    gpsPoints: any[];
    blocks: any[];
    subAreas: any[];
  }) => {
    if (!draftId) return;

    if (!data.outerBoundary || !data.outerBoundary.type || !data.outerBoundary.coordinates) {
      setError(t('workspace.invalidGeometry'));
      return;
    }

    try {
      // PF-3: pre-flight preview — a drawn draft boundary may overlap/gap a
      // neighbour. Surface the preview so the user decides before converting.
      if (typeof forestApi.previewBoundaryOverlap === 'function') {
        try {
          const rel = await forestApi.previewBoundaryOverlap({
            geometry: data.outerBoundary,
            method: 'digitize',
          });
          if (rel?.overlapping_forests?.length || rel?.gaps?.length) {
            reviewBoundary({
              geometry: data.outerBoundary,
              forestName: 'Forest',
              method: 'digitize',
              onResolved: (r) => {
                if (r.id) navigate(`/calculations/${r.id}/block-naming`);
                else navigate('/my-uploads');
              },
            });
            return;
          }
        } catch {
          /* preview unavailable — fall through to convert */
        }
      }
      // Convert draft to calculation
      const response = await fetch(`${API_BASE_URL}/api/forests/drafts/${draftId}/convert`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
        body: JSON.stringify({
          outer_boundary: data.outerBoundary,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || t('workspace.convertFailed'));
      }

      const result = await response.json();
      navigate(`/calculations/${result.id}/block-naming`);
    } catch (err: any) {
      setError(err.message || t('workspace.saveFailed'));
    }
  };

  const handleCancel = () => {
    navigate('/upload');
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-green-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">{t('workspace.loadingDraft')}</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-2xl mx-auto p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <h2 className="text-red-800 font-semibold">{t('common.error')}</h2>
          <p className="text-red-600 mt-2">{error}</p>
          <button
            onClick={() => navigate('/upload')}
            className="mt-4 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
          >
            {t('workspace.backToUpload')}
          </button>
        </div>
      </div>
    );
  }

  if (!draft) {
    return (
      <div className="max-w-2xl mx-auto p-6">
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <h2 className="text-yellow-800 font-semibold">{t('workspace.draftNotFound')}</h2>
          <p className="text-yellow-600 mt-2">{t('workspace.draftDeleted')}</p>
          <button
            onClick={() => navigate('/upload')}
            className="mt-4 px-4 py-2 bg-yellow-600 text-white rounded hover:bg-yellow-700"
          >
            {t('workspace.backToUpload')}
          </button>
        </div>
      </div>
    );
  }

  // Get initial polygon from draft data
  const islands = draft.draft_data?.islands || [];
  const draftStepIndex = (draft.draft_data as any)?.draft_step_index ?? 0; // U11: resume at saved step
  let initialPolygon: any = null;

  if (islands.length === 1) {
    initialPolygon = islands[0].geometry;
  } else if (islands.length > 1) {
    // Combine into MultiPolygon
    initialPolygon = {
      type: 'MultiPolygon',
      coordinates: islands.map(i => i.geometry.coordinates),
    };
  }

  return (
    <div className="max-w-7xl mx-auto p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">{t('workspace.resumeDraft')}</h1>
        <p className="text-gray-600 mt-1">
          {t('workspace.continuingWorkOn', { name: draft.forest_name })}
        </p>
        {draft.draft_data?.islands_count > 0 && (
          <p className="text-sm text-gray-500 mt-1">
            {t('workspace.islandsCount', { count: draft.draft_data.islands_count, area: draft.draft_data.total_area?.toFixed(2) ?? '0' })}
          </p>
        )}
      </div>

      <MapCreationWizard
        forestName={draft.forest_name || t('uploads.unnamedForest')}
        onComplete={handleComplete}
        onCancel={handleCancel}
        initialPolygon={initialPolygon}
        initialDraftId={draft.id}
        isDraft={true}
        initialStepIndex={draftStepIndex}
      />
    </div>
  );
}
