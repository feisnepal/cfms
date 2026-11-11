/**
 * OnboardingWalkthrough.tsx — 5-step guided onboarding tour (Task 4.1.6).
 *
 * Walks new users through adding a layer, choosing a purpose, drawing,
 * using vertex tables, and finishing & saving. Stored in localStorage.
 */
import { useState, useEffect } from 'react';
import { useT } from '../i18n/hooks';

export function OnboardingWalkthrough() {
  const [step, setStep] = useState<number | null>(null);
  const t = useT();

  useEffect(() => {
    const completed = localStorage.getItem('cf_onboarding_completed');
    if (!completed) {
      setStep(1);
    }
  }, []);

  if (step === null) return null;

  const steps = [
    { title: t('onboarding.step1Title'), desc: t('onboarding.step1Desc') },
    { title: t('onboarding.step2Title'), desc: t('onboarding.step2Desc') },
    { title: t('onboarding.step3Title'), desc: t('onboarding.step3Desc') },
    { title: t('onboarding.step4Title'), desc: t('onboarding.step4Desc') },
    { title: t('onboarding.step5Title'), desc: t('onboarding.step5Desc') },
  ];

  const current = steps[step - 1];

  const handleNext = () => {
    if (step < steps.length) {
      setStep(step + 1);
    } else {
      localStorage.setItem('cf_onboarding_completed', 'true');
      setStep(null);
    }
  };

  const handleSkip = () => {
    localStorage.setItem('cf_onboarding_completed', 'true');
    setStep(null);
  };

  return (
    <div className="onboarding-tour-modal" role="dialog" aria-label={t('onboarding.guidedTour', { step, total: steps.length })} style={{
      position: 'fixed', bottom: '24px', left: '24px', zIndex: 9999,
      background: '#fff', padding: '20px', borderRadius: '12px',
      boxShadow: '0 10px 25px rgba(0,0,0,0.2)', width: '340px', border: '1px solid #e5e7eb'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
        <span style={{ fontSize: '12px', fontWeight: 600, color: '#2563eb' }}>{t('onboarding.guidedTour', { step, total: steps.length })}</span>
        <button onClick={handleSkip} style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#9ca3af', fontSize: '14px' }}>{t('onboarding.skip')}</button>
      </div>
      <h3 style={{ margin: '0 0 8px 0', fontSize: '16px', color: '#1f2937' }}>{current.title}</h3>
      <p style={{ margin: '0 0 16px 0', fontSize: '13px', color: '#4b5663', lineHeight: '1.4' }}>{current.desc}</p>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
        <button
          onClick={handleNext}
          style={{ background: '#2563eb', color: '#fff', border: 'none', padding: '6px 14px', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}
        >
          {step === steps.length ? t('onboarding.finish') : t('onboarding.next')}
        </button>
      </div>
    </div>
  );
}
