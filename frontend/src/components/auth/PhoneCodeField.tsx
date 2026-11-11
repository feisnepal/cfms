/** PhoneCodeField — a mobile number with a "Send code" button and a resend countdown. The parent owns the values. */
import React, { useEffect, useState } from 'react';
import { useT } from '../../i18n/hooks';
import { apiErrorText } from '../../lib/apiErrorText';

interface Props {
  phone: string;
  code: string;
  onPhone: (v: string) => void;
  onCode: (v: string) => void;
  /** Asks the server to text the code. Rejects with the server's error. */
  send: (phone: string) => Promise<void>;
  /** Show the code box only after a code was sent. */
  idPrefix?: string;
}

const input =
  'mt-1 block w-full rounded-xl border border-gray-200 bg-white/80 px-3.5 py-2.5 text-sm text-gray-900 placeholder-gray-400 shadow-sm transition focus:border-emerald-500 focus:outline-none focus:ring-4 focus:ring-emerald-100';

const PhoneCodeField: React.FC<Props> = ({ phone, code, onPhone, onCode, send, idPrefix = 'phone' }) => {
  const t = useT();
  const [sent, setSent] = useState(false);
  const [wait, setWait] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (wait <= 0) return undefined;
    const id = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(id);
  }, [wait]);

  const onSend = async () => {
    setError('');
    setBusy(true);
    try {
      await send(phone);
      setSent(true);
      setWait(60);
    } catch (err) {
      setError(apiErrorText(err, t('auth.registrationFailed')));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <label htmlFor={`${idPrefix}-number`} className="block text-sm font-medium text-gray-700">
        {t('auth.phoneRequired')}
      </label>
      <div className="flex gap-2">
        <input
          id={`${idPrefix}-number`}
          name="phone"
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          required
          className={input}
          placeholder="98XXXXXXXX"
          value={phone}
          onChange={(e) => onPhone(e.target.value)}
        />
        <button
          type="button"
          onClick={onSend}
          disabled={busy || wait > 0 || phone.trim().length < 8}
          className="mt-1 shrink-0 rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm shadow-emerald-600/30 transition hover:bg-emerald-700 disabled:bg-gray-300 disabled:shadow-none"
        >
          {wait > 0 ? t('auth.resendIn', { seconds: wait }) : sent ? t('auth.resendCode') : t('auth.sendCode')}
        </button>
      </div>
      <p className="text-xs text-gray-500">{t('auth.phoneHelp')}</p>
      {error && <p className="text-sm text-red-700" role="alert">{error}</p>}
      {sent && (
        <div>
          <label htmlFor={`${idPrefix}-code`} className="block text-sm font-medium text-gray-700">
            {t('auth.verificationCode')}
          </label>
          <input
            id={`${idPrefix}-code`}
            name="phone_code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={8}
            required
            className={`${input} text-center text-lg font-semibold tracking-[0.5em]`}
            placeholder="123456"
            value={code}
            onChange={(e) => onCode(e.target.value.replace(/\D/g, ''))}
          />
          <p className="mt-1 text-xs text-green-700">{t('auth.codeSent')}</p>
        </div>
      )}
    </div>
  );
};

export default PhoneCodeField;
