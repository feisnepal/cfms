/** VerifyEmail — opened from the emailed link; the token alone proves the address. */
import React, { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useT } from '../i18n/hooks';
import { authApi } from '../services/api';

type State = 'checking' | 'ok' | 'failed';

const VerifyEmail: React.FC = () => {
  const t = useT();
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const [state, setState] = useState<State>(token ? 'checking' : 'failed');

  const asked = useRef(false);

  useEffect(() => {
    // The link works once, and React's dev double-run would send it twice: the second try would
    // find it spent and report failure for an address that was in fact verified. Ask exactly once.
    if (!token || asked.current) return;
    asked.current = true;
    authApi
      .verifyEmail(token)
      .then(() => setState('ok'))
      .catch(() => setState('failed'));
  }, [token]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4">
      <div className="max-w-md w-full rounded-md bg-white p-8 text-center space-y-4 shadow">
        <p className={state === 'failed' ? 'text-red-800' : 'text-green-900'}>
          {state === 'checking' ? t('auth.verifyingEmail') : state === 'ok' ? t('auth.emailVerified') : t('auth.emailVerifyFailed')}
        </p>
        <Link to="/login" className="font-medium text-green-700">{t('auth.backToSignIn')}</Link>
      </div>
    </div>
  );
};

export default VerifyEmail;
