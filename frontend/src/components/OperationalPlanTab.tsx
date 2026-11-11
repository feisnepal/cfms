/** OperationalPlanTab — tab for operational plan document generation and preview. */
import { useState, useEffect, useRef } from 'react';
import { useT } from '../i18n/hooks';
import { operationalPlanApi } from '../services/api';
import type { OperationalPlanResponse } from '../types';
import { apiErrorText } from '../lib/apiErrorText';

interface OperationalPlanTabProps {
  calculationId: string;
}

export default function OperationalPlanTab({ calculationId }: OperationalPlanTabProps) {
  const t = useT();
  const [plan, setPlan] = useState<OperationalPlanResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<string>('section_1');
  const [editingContent, setEditingContent] = useState<string>('');
  const [saving, setSaving] = useState(false);
  const saveTimerRef = useRef<NodeJS.Timeout | null>(null);
  const lastSavedRef = useRef<string>('');

  useEffect(() => {
    loadOperationalPlan();
  }, [calculationId]);

  // Auto-save with 120 second delay (2 minutes)
  useEffect(() => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
    }

    if (editingContent && editingContent !== lastSavedRef.current) {
      saveTimerRef.current = setTimeout(() => {
        handleSaveSection();
        lastSavedRef.current = editingContent;
      }, 120000);
    }

    return () => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
      }
    };
  }, [editingContent]);

  const loadOperationalPlan = async () => {
    try {
      setLoading(true);
      const data = await operationalPlanApi.getByCalculation(calculationId);
      console.log('Loaded operational plan:', data);
      console.log('Sections:', data.sections);
      setPlan(data);
      setError(null);
    } catch (err: any) {
      if (err.response?.status === 404) {
        try {
          const newPlan = await operationalPlanApi.create(calculationId);
          setPlan(newPlan);
        } catch (createErr: any) {
          setError(t('operationalPlan.tab.createFailed'));
        }
      } else {
        setError(t('operationalPlan.tab.loadFailed'));
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSectionClick = (sectionKey: string) => {
    setActiveSection(sectionKey);
    const section = plan?.sections?.[sectionKey];
    if (section) {
      setEditingContent(section.content || '');
    }
  };

  const handleContentChange = (value: string) => {
    setEditingContent(value);
  };

  const handleSaveSection = async () => {
    if (!plan) {
      console.error('No plan loaded');
      return;
    }

    try {
      setSaving(true);
      console.log('Saving section:', activeSection, 'Content length:', editingContent.length);
      const updated = await operationalPlanApi.updateSection(
        plan.id,
        activeSection,
        editingContent,
        sections[activeSection]?.auto_data
      );
      console.log('Save successful:', updated);
      console.log('Updated sections:', Object.keys(updated.sections || {}));

      // Reload the plan to ensure we have the latest data
      await loadOperationalPlan();
      lastSavedRef.current = editingContent;
      setError(null);
    } catch (err: any) {
      console.error('Save error:', err);
      setError(apiErrorText(err, t('operationalPlan.tab.saveSectionFailed')));
    } finally {
      setSaving(false);
    }
  };

  const handleAutoPopulate = async () => {
    if (!plan) return;

    try {
      setSaving(true);
      const updated = await operationalPlanApi.autoPopulate(plan.id);
      setPlan(updated);
    } catch (err) {
      setError(t('operationalPlan.tab.autoPopulateFailed'));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="p-4">{t('operationalPlan.tab.loading')}</div>;
  }

  if (error) {
    return <div className="p-4 text-red-600">{error}</div>;
  }

  const sections = plan?.sections || {};
  const currentSection = sections[activeSection];

  return (
    <div className="flex h-full">
      {/* Left Sidebar - TOC */}
      <div className="w-1/3 bg-gray-50 border-r border-gray-200 overflow-y-auto">
        <div className="p-4">
          <h3 className="text-lg font-semibold mb-4">विषय सूचि (Table of Contents)</h3>
           <div className="flex gap-2 mb-4">
             <button
               onClick={handleAutoPopulate}
               disabled={saving}
               className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
             >
               {saving ? 'प्रक्रिया हुँदै...' : 'सिस्टमबाट डाटा भर्नुहोस्'}
             </button>
             <button
               onClick={() => {
                 console.log('Reloading operational plan...');
                 loadOperationalPlan();
               }}
               className="px-4 py-2 bg-gray-600 text-white rounded hover:bg-gray-700 text-sm"
             >
               रिफ्रेस
             </button>
           </div>
           <div className="text-xs text-gray-500 mb-2">
             Total sections: {Object.keys(sections).length}
           </div>

          <div className="space-y-1">
            {/* 1. TOC Items - editable sections */}
            {Object.entries(sections)
              .filter(([key]) => key.startsWith('toc_'))
              .map(([key, section]: [string, any]) => (
                <button
                  key={key}
                  onClick={() => handleSectionClick(key)}
                  className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                    activeSection === key
                      ? 'bg-green-100 text-green-800 font-medium'
                      : 'hover:bg-gray-100'
                  }`}
                >
                  <div className="font-medium">{section.section_number}</div>
                  <div className="text-xs text-gray-600">{section.title}</div>
                </button>
              ))}
            <div className="mb-4"></div>

            {/* 2. Section Headers - परिच्छेद १-१८ */}
            {Object.entries(sections)
              .filter(([key]) => key.startsWith('section_'))
              .map(([key, section]: [string, any]) => (
                <button
                  key={key}
                  onClick={() => handleSectionClick(key)}
                  className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                    activeSection === key
                      ? 'bg-green-100 text-green-800 font-medium'
                      : 'hover:bg-gray-100'
                  }`}
                >
                  <div className="font-medium">परिच्छेद {section.section_number}</div>
                  <div className="text-xs text-gray-600">{section.title}</div>
                  {section.is_auto_generated && (
                    <div className="text-xs text-blue-600 mt-1">स्वत: डाटा उपलब्ध</div>
                  )}
                </button>
              ))}

            {/* 3. Tables - at the very end */}
            {plan?.sections?.toc?.tables && (
              <div className="mt-4 pt-4 border-t border-gray-300">
                <div className="text-xs font-medium text-gray-500 mb-2 px-3">तालिकाहरु (Tables)</div>
                {plan.sections.toc.tables.map((item: string, idx: number) => (
                  <div key={`table-${idx}`} className="px-3 py-1.5 text-sm text-gray-600">
                    {item}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Right Panel - Section Editor */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-6">
          {currentSection && (
            <>
              <div className="mb-4">
                <h2 className="text-xl font-bold">
                  परिच्छेद {currentSection.section_number}: {currentSection.title}
                </h2>
                {currentSection.subsections && (
                  <div className="mt-2 text-sm text-gray-600">
                    {currentSection.subsections.map((sub: string, idx: number) => (
                      <div key={idx}>{sub}</div>
                    ))}
                  </div>
                )}
              </div>

              {/* Auto-populated data display */}
              {currentSection.auto_data && Object.keys(currentSection.auto_data).length > 0 && (
                <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded">
                  <h4 className="text-sm font-medium text-blue-800 mb-2">सिस्टम डाटा (Auto-populated Data)</h4>
                  <pre className="text-xs text-blue-700 whitespace-pre-wrap">
                    {JSON.stringify(currentSection.auto_data, null, 2)}
                  </pre>
                </div>
              )}

              {/* Editor */}
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  विवरण (Content)
                </label>
                <textarea
                  value={editingContent}
                  onChange={(e) => handleContentChange(e.target.value)}
                  className="w-full h-64 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500"
                  placeholder="यहाँ विवरण लेख्नुहोस्..."
                />
              </div>

              <button
                onClick={handleSaveSection}
                disabled={saving}
                className="px-6 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
              >
                {saving ? 'सेभ हुँदै...' : 'सेभ गर्नुहोस्'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
