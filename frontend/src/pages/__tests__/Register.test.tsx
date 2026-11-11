/** Register: the phone must be proved before the form can go, and the declared role and social identity are sent. */
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

const register = vi.fn().mockResolvedValue(undefined);
const signupPhoneCode = vi.fn().mockResolvedValue(undefined);

vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ register }) }));
vi.mock('../../services/api', () => ({ authApi: { signupPhoneCode: (p: string) => signupPhoneCode(p) } }));
vi.mock('../../components/LanguageSelector', () => ({ default: () => null }));
vi.mock('../../i18n/hooks', () => ({
  useT: () => (key: string) => key,
}));

import Register from '../Register';

const renderPage = () => render(<MemoryRouter><Register /></MemoryRouter>);

describe('Register', () => {
  beforeEach(() => {
    register.mockClear();
    signupPhoneCode.mockClear();
  });

  it('asks for the code only after one was sent, then registers with the declared role', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(screen.queryByLabelText('auth.verificationCode')).toBeNull();

    await user.type(screen.getByLabelText('auth.fullName'), 'Sita Rai');
    await user.click(screen.getByRole('radio', { name: /auth\.typeOfficial/ }));
    await user.click(screen.getByRole('radio', { name: /auth\.designationRanger/ }));
    await user.type(screen.getByLabelText('auth.subDivision'), 'Rampur sub-division');
    await user.type(screen.getByLabelText('auth.phoneRequired'), '9841234567');
    await user.click(screen.getByRole('button', { name: 'auth.sendCode' }));

    await waitFor(() => expect(signupPhoneCode).toHaveBeenCalledWith('9841234567'));
    await user.type(await screen.findByLabelText('auth.verificationCode'), '123456');
    await user.type(screen.getByLabelText('auth.emailLabel'), 'sita@example.com');
    await user.type(screen.getByLabelText('auth.instagramHandle'), 'sita_rai');
    await user.type(screen.getByLabelText('auth.password'), 'TestPass123!');
    await user.click(screen.getByRole('button', { name: 'auth.register' }));

    await waitFor(() => expect(register).toHaveBeenCalledTimes(1));
    expect(register.mock.calls[0][0]).toMatchObject({
      full_name: 'Sita Rai',
      user_type: 'official',
      designation: 'ranger',
      sub_division: 'Rampur sub-division',
      phone: '9841234567',
      phone_code: '123456',
      email: 'sita@example.com',
      instagram_handle: 'sita_rai',
    });
    expect(await screen.findByTestId('registration-pending')).toBeTruthy();
  });

  it('asks a student for the study fields, not a designation, and sends them as details', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText('auth.fullName'), 'Ram Thapa');
    await user.click(screen.getByRole('radio', { name: /auth\.typeStudent/ }));
    expect(screen.queryByRole('radio', { name: /auth\.designationRanger/ })).toBeNull();
    await user.selectOptions(screen.getByLabelText('auth.studentLevel'), 'college');
    await user.type(screen.getByLabelText('auth.institution'), 'Pokhara Campus');
    await user.type(screen.getByLabelText('auth.programme'), 'BSc Forestry');
    await user.type(screen.getByLabelText('auth.supervisorName'), 'Dr Rai');
    await user.type(screen.getByLabelText('auth.supervisorEmail'), 'rai@pc.edu.np');
    await user.type(screen.getByLabelText('auth.phoneRequired'), '9841234568');
    await user.click(screen.getByRole('button', { name: 'auth.sendCode' }));
    await user.type(await screen.findByLabelText('auth.verificationCode'), '123456');
    await user.type(screen.getByLabelText('auth.emailLabel'), 'ram@example.com');
    await user.type(screen.getByLabelText('auth.instagramHandle'), 'ram_t');
    await user.type(screen.getByLabelText('auth.password'), 'TestPass123!');
    await user.click(screen.getByRole('button', { name: 'auth.register' }));

    await waitFor(() => expect(register).toHaveBeenCalledTimes(1));
    const sent = register.mock.calls[0][0];
    expect(sent.user_type).toBe('student');
    expect(sent.designation).toBeUndefined();
    expect(sent.details).toMatchObject({ level: 'college', institution: 'Pokhara Campus', supervisor_email: 'rai@pc.edu.np' });
  });

  it('cannot ask for a code from a number that is too short', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText('auth.phoneRequired'), '123');
    expect((screen.getByRole('button', { name: 'auth.sendCode' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
