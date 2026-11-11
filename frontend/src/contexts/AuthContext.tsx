/**
 * AuthContext — authentication state and methods for the entire app.
 *
 * Provides login, register, logout, and token-refresh methods via React
 * context. Stores the current user and JWT token in localStorage and
 * exposes them to all child components.
 */
import React, { createContext, useContext, useState, useEffect, ReactNode, useRef } from 'react';
import { authApi, storeTokens, clearTokens, LAST_USER_KEY } from '../services/api';
import { clearOfflineApiCache } from '../pwa/offline';
import type { User, LoginRequest, RegisterRequest, TokenResponse } from '../types';
import { useWorkspaceStore } from '../store/workspaceStore';
import { mapBackendRoleToFrontend } from '../lib/roleMapping';

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  login: (credentials: LoginRequest) => Promise<void>;
  /** Finish a sign-in that was done another way (phone code, Facebook): store the tokens and load the user. */
  loginWithTokens: (tokenData: TokenResponse) => Promise<void>;
  register: (userData: RegisterRequest) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
  refreshUser: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

interface AuthProviderProps {
  children: ReactNode;
}

// Auto-refresh interval (check every 5 minutes)
const REFRESH_CHECK_INTERVAL = 5 * 60 * 1000;

// Idle timeout — log out after 1 hour of no API activity
const IDLE_TIMEOUT_MS = 60 * 60 * 1000;
const IDLE_CHECK_INTERVAL = 30 * 1000; // check every 30s

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const refreshTimerRef = useRef<NodeJS.Timeout | null>(null);
  const idleTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Check if token needs refresh (within 60 minutes of expiry)
  const checkAndRefreshToken = async () => {
    const expiryStr = localStorage.getItem('token_expiry');
    if (!expiryStr || !user) return;

    // Backoff: stop retrying after 3 consecutive failures (token truly dead)
    const failCount = parseInt(localStorage.getItem('refresh_fail_count') || '0');
    if (failCount >= 3) return;

    const expiryTime = parseInt(expiryStr);
    const now = Date.now();
    const timeUntilExpiry = expiryTime - now;

    // Only refresh if token is close to expiry (avoids unnecessary calls)
    if (timeUntilExpiry < 0) {
      // Token already expired. With no signal nothing can be renewed and the session is not over: a field team keeps working offline, and the
      // first call after the signal returns renews it (or ends the session if the server says so).
      if (typeof navigator !== 'undefined' && navigator.onLine === false) return;
      // Online: log out
      logout();
      return;
    }
    if (timeUntilExpiry > 60 * 60 * 1000) return;

    try {
      // authApi.refresh stores the rotated pair itself — the old refresh token
      // is dead as soon as this returns (H2.5 / S1-05).
      await authApi.refresh();
      localStorage.removeItem('refresh_fail_count');
    } catch {
      localStorage.setItem('refresh_fail_count', String(failCount + 1));
    }
  };

  useEffect(() => {
    const loadUser = async () => {
      const token = localStorage.getItem('access_token');
      if (token) {
        try {
          const userData = await authApi.me();
          setUser(userData);
          useWorkspaceStore.getState().setUserRoles(mapBackendRoleToFrontend(userData.role));
          try { localStorage.setItem(LAST_USER_KEY, JSON.stringify(userData)); } catch { /* storage full or blocked: only an offline start loses the name */ }
        } catch (error: any) {
          // No answer at all (no signal) is not "signed out": the person who was signed in still is. Only the server's own refusal ends the session.
          let remembered: any = null;
          try { remembered = JSON.parse(localStorage.getItem(LAST_USER_KEY) || 'null'); } catch { remembered = null; }
          if (!error?.response && remembered) {
            setUser(remembered);
            useWorkspaceStore.getState().setUserRoles(mapBackendRoleToFrontend(remembered.role));
          } else {
            clearTokens();
          }
        }
      }
      setIsLoading(false);
    };

    loadUser();

    // Set up periodic token expiry check
    refreshTimerRef.current = setInterval(checkAndRefreshToken, REFRESH_CHECK_INTERVAL);

    // Set up idle timeout check (every 30s)
    const checkIdle = () => {
      const lastActive = localStorage.getItem('last_active');
      if (!lastActive || !user) return;
      // Working offline makes no calls, so "last active" stands still while the person is busy: no idle logout without a signal.
      if (typeof navigator !== 'undefined' && navigator.onLine === false) return;
      if (Date.now() - parseInt(lastActive) > IDLE_TIMEOUT_MS) {
        logout();
      }
    };
    idleTimerRef.current = setInterval(checkIdle, IDLE_CHECK_INTERVAL);

    return () => {
      if (refreshTimerRef.current) {
        clearInterval(refreshTimerRef.current);
      }
      if (idleTimerRef.current) {
        clearInterval(idleTimerRef.current);
      }
    };
  }, []);

  const login = async (credentials: LoginRequest) => {
    await loginWithTokens(await authApi.login(credentials));
  };

  const loginWithTokens = async (tokenData: TokenResponse) => {
    // Somebody is signing in: what the last person's session kept for offline use is not theirs to read.
    clearOfflineApiCache();
    // Stores the access token and the refresh token that rotates it.
    storeTokens(tokenData);
    const userData = await authApi.me();
    setUser(userData);
    useWorkspaceStore.getState().setUserRoles(mapBackendRoleToFrontend(userData.role));
  };

  const register = async (userData: RegisterRequest) => {
    await authApi.register(userData);
    // No auto-login: the person signs in on the login page. The account is active but
    // unapproved (limited tier) until a super admin approves it.
  };

  const logout = () => {
    // H2.5 / S1-05: tell the server first. Clearing localStorage on its own is
    // what "logging out" used to mean here, and it left every issued token
    // valid until it expired on its own — a stolen one indefinitely.
    authApi.logout().catch(() => {
      // Offline or already-expired session: the local state must still be
      // cleared, and the tokens will lapse on their own.
    });
    clearTokens();
    setUser(null);
  };

  const refreshUser = async () => {
    try {
      const userData = await authApi.me();
      setUser(userData);
      useWorkspaceStore.getState().setUserRoles(mapBackendRoleToFrontend(userData.role));
    } catch {
      logout();
    }
  };

  const value = {
    user,
    isLoading,
    login,
    loginWithTokens,
    register,
    logout,
    isAuthenticated: !!user,
    refreshUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
