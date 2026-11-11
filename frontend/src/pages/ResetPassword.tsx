/** ResetPassword — opened from the emailed link (or one a super admin handed over): choose a new password. */
import React, { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useT } from '../i18n/hooks';
import LanguageSelector from '../components/LanguageSelector';
import { authApi } from '../services/api';
import { apiErrorText } from '../lib/apiErrorText';

const ResetPassword: React.FC = () => {
  const t = useT();
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const [password, setPassword] = useState('');
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      await authApi.resetPassword({ token, new_password: password });
      setDone(true);
    } catch (err) {
      setError(apiErrorText(err, t('auth.resetFailed')));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-6">
        <LanguageSelector />
        <h2 className="text-center text-2xl font-extrabold text-gray-900">{t('auth.setNewPassword')}</h2>
        {done ? (
          <div className="rounded-md bg-green-50 p-6 text-center space-y-4">
            <p className="text-sm text-green-900">{t('auth.resetDone')}</p>
            <Link to="/login" className="font-medium text-green-700">{t('auth.backToSignIn')}</Link>
          </div>
        ) : !token ? (
          <p className="rounded-md bg-red-50 p-4 text-sm text-red-800">{t('auth.resetFailed')}</p>
        ) : (
          <form className="space-y-4" onSubmit={submit}>
            {error && <div className="rounded-md bg-red-50 p-4 text-sm text-red-800" role="alert">{error}</div>}
            <div>
              <label htmlFor="new-password" className="block text-sm font-medium text-gray-700">{t('auth.newPassword')}</label>
              <input id="new-password" type="password" autoComplete="new-password" required
                className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-green-500 focus:border-green-500 sm:text-sm"
                value={password} onChange={(e) => setPassword(e.target.value)} />
              <p className="mt-1 text-xs text-gray-500">{t('auth.passwordHint')}</p>
            </div>
            <button type="submit" disabled={busy}
              className="w-full flex justify-center py-2 px-4 text-sm font-medium rounded-md text-white bg-green-600 hover:bg-green-700 disabled:bg-gray-400">
              {t('auth.setNewPassword')}
            </button>
          </form>
        )}
      </div>
    </div>
  );
};

export default ResetPassword;
