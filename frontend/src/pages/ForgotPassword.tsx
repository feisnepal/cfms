/** ForgotPassword — ask for a reset link (email) or code (phone); the answer is the same for any input. */
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useT } from '../i18n/hooks';
import LanguageSelector from '../components/LanguageSelector';
import { authApi } from '../services/api';
import { apiErrorText } from '../lib/apiErrorText';

const input =
  'mt-1 appearance-none block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-md focus:outline-none focus:ring-green-500 focus:border-green-500 sm:text-sm';
const button =
  'w-full flex justify-center py-2 px-4 text-sm font-medium rounded-md text-white bg-green-600 hover:bg-green-700 disabled:bg-gray-400';

const ForgotPassword: React.FC = () => {
  const t = useT();
  const [identifier, setIdentifier] = useState('');
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const isPhone = identifier.trim() !== '' && !identifier.includes('@');

  const run = async (work: () => Promise<void>, fallback: string) => {
    setError('');
    setBusy(true);
    try {
      await work();
    } catch (err) {
      setError(apiErrorText(err, fallback));
    } finally {
      setBusy(false);
    }
  };

  const request = (e: React.FormEvent) => {
    e.preventDefault();
    return run(async () => {
      await authApi.forgotPassword(identifier.trim());
      setSent(true);
    }, t('auth.resetFailed'));
  };

  const reset = (e: React.FormEvent) => {
    e.preventDefault();
    return run(async () => {
      await authApi.resetPassword({ phone: identifier.trim(), code, new_password: newPassword });
      setDone(true);
    }, t('auth.resetFailed'));
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-6">
        <LanguageSelector />
        <h2 className="text-center text-2xl font-extrabold text-gray-900">{t('auth.forgotPasswordTitle')}</h2>
        {error && <div className="rounded-md bg-red-50 p-4 text-sm text-red-800" role="alert">{error}</div>}

        {done ? (
          <div className="rounded-md bg-green-50 p-6 text-center space-y-4">
            <p className="text-sm text-green-900">{t('auth.resetDone')}</p>
            <Link to="/login" className="font-medium text-green-700">{t('auth.backToSignIn')}</Link>
          </div>
        ) : !sent ? (
          <form className="space-y-4" onSubmit={request}>
            <p className="text-sm text-gray-600">{t('auth.forgotPasswordHelp')}</p>
            <div>
              <label htmlFor="identifier" className="block text-sm font-medium text-gray-700">{t('auth.emailOrPhone')}</label>
              <input id="identifier" required className={input} value={identifier}
                onChange={(e) => setIdentifier(e.target.value)} />
            </div>
            <button type="submit" disabled={busy || !identifier.trim()} className={button}>{t('auth.sendReset')}</button>
          </form>
        ) : (
          <div className="space-y-4">
            <p className="rounded-md bg-green-50 p-4 text-sm text-green-900">{t('auth.resetSentGeneric')}</p>
            {isPhone && (
              <form className="space-y-4" onSubmit={reset}>
                <div>
                  <label htmlFor="code" className="block text-sm font-medium text-gray-700">{t('auth.verificationCode')}</label>
                  <input id="code" inputMode="numeric" autoComplete="one-time-code" maxLength={8} required className={input}
                    value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} />
                </div>
                <div>
                  <label htmlFor="new-password" className="block text-sm font-medium text-gray-700">{t('auth.newPassword')}</label>
                  <input id="new-password" type="password" autoComplete="new-password" required className={input}
                    value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
                  <p className="mt-1 text-xs text-gray-500">{t('auth.passwordHint')}</p>
                </div>
                <button type="submit" disabled={busy || code.length < 4} className={button}>{t('auth.setNewPassword')}</button>
              </form>
            )}
          </div>
        )}
        {!done && (
          <div className="text-center">
            <Link to="/login" className="text-sm font-medium text-green-600 hover:text-green-500">{t('auth.backToSignIn')}</Link>
          </div>
        )}
      </div>
    </div>
  );
};

export default ForgotPassword;
