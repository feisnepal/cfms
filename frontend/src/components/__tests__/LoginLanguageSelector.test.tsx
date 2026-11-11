/**
 * LoginLanguageSelector — Phase 1 verification:
 *  - fresh visitor lands on Nepali (default),
 *  - LanguageSelector switch persists to localStorage and re-renders,
 *  - no English leaks on the login card when Nepali is active.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import Login from '../../pages/Login';
import { AuthProvider } from '../../contexts/AuthContext';
import i18n from '../../i18n';

const renderLogin = () =>
  render(
    <AuthProvider>
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<Login />} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>
  );

describe('Login page language behavior (Phase 1)', () => {
  beforeEach(async () => {
    localStorage.clear();
    await i18n.changeLanguage('ne');
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('renders Nepali by default with no English leak on the card', async () => {
    renderLogin();

    expect(
      await screen.findByText('सामुदायिक वन व्यवस्थापन प्रणाली'),
    ).toBeInTheDocument();

    expect(screen.getByPlaceholderText('इमेल')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('पासवर्ड')).toBeInTheDocument();
    expect(
      screen.getByText('खाता छैन? यहाँ दर्ता गर्नुहोस्'),
    ).toBeInTheDocument();

    expect(screen.queryByText('Community Forest Management System')).toBeNull();
    expect(screen.queryByText(/Sign in to your account/i)).toBeNull();
    expect(screen.queryByText(/Don't have an account/i)).toBeNull();
  });

  it('persists the chosen language to localStorage and updates the UI', async () => {
    renderLogin();

    await screen.findByText('सामुदायिक वन व्यवस्थापन प्रणाली');
    fireEvent.click(screen.getByText('English'));

    await waitFor(() => {
      expect(i18n.language).toBe('en');
    });
    expect(localStorage.getItem('i18nextLng')).toBe('en');

    expect(
      await screen.findByText('Community Forest Management System'),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Email')).toBeInTheDocument();
  });

  it('switches back to Nepali deterministically', async () => {
    localStorage.setItem('i18nextLng', 'ne');
    renderLogin();

    expect(
      await screen.findByText('सामुदायिक वन व्यवस्थापन प्रणाली'),
    ).toBeInTheDocument();
    expect(i18n.language).toBe('ne');
  });
});