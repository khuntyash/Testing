import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import {
  clearSession,
  loadSession,
  saveSession,
  updateUserProfile,
} from "./authStorage.js";
import {
  firebaseEnabled,
  firebaseLogin,
  firebaseLoginWithGoogle,
  firebaseLogout,
  firebaseSignup,
  firebaseUpdateProfileName,
  observeFirebaseSession,
} from "./firebaseAuth.js";
import { apiGetCurrentUser, apiLogin, apiLogout, apiSignup, apiUpdateProfile } from "../api/authApi.js";
import { invalidateAll } from "../api/requestCache.js";

const AuthContext = createContext(null);

function buildUserScope(user) {
  const raw =
    user?.id ??
    user?.userId ??
    user?.uid ??
    (typeof user?.email === "string" ? user.email.trim().toLowerCase() : "");
  return String(raw || "").trim().toLowerCase() || "anonymous";
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => (firebaseEnabled ? null : loadSession()));
  const [authReady, setAuthReady] = useState(false);
  const previousScopeRef = useRef("anonymous");

  useEffect(() => {
    if (firebaseEnabled) {
      const unsub = observeFirebaseSession((session) => {
        setUser(session);
        setAuthReady(true);
      });
      return unsub;
    }

    let alive = true;
    const restoreSession = async () => {
      const current = loadSession();
      if (!current?.token) {
        if (current) clearSession();
        if (alive) {
          setUser(null);
          setAuthReady(true);
        }
        return;
      }
      try {
        const remote = await apiGetCurrentUser(current.token);
        if (!alive) return;
        saveSession(remote);
        setUser(remote);
      } catch {
        if (!alive) return;
        clearSession();
        setUser(null);
      } finally {
        if (alive) setAuthReady(true);
      }
    };
    restoreSession();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const nextScope = buildUserScope(user);
    if (previousScopeRef.current !== nextScope) {
      invalidateAll();
      previousScopeRef.current = nextScope;
    }
  }, [user]);

  const login = useCallback(async (email, password) => {
    if (firebaseEnabled) {
      const session = await firebaseLogin(email, password);
      setUser(session);
      return session;
    }
    try {
      const session = await apiLogin({ email, password });
      saveSession(session);
      setUser(session);
      return session;
    } catch (err) {
      if (err instanceof Error) throw err;
      throw new Error("Login failed. Please try again.");
    }
  }, []);

  const signup = useCallback(async ({ name, email, password }) => {
    if (firebaseEnabled) {
      return firebaseSignup({ name, email, password });
    }
    try {
      const session = await apiSignup({ name, email, password });
      saveSession(session);
      setUser(session);
      return session;
    } catch (err) {
      if (err instanceof Error) throw err;
      throw new Error("Could not create account.");
    }
  }, []);

  const logout = useCallback(() => {
    if (firebaseEnabled) {
      firebaseLogout();
      setUser(null);
      return;
    }
    if (user?.token) {
      apiLogout(user.token).catch(() => {
        // Logout should always clear local state, even if API call fails.
      });
    }
    clearSession();
    setUser(null);
  }, [user]);

  const loginWithGoogle = useCallback(async () => {
    if (!firebaseEnabled) {
      throw new Error("Google sign-in is not configured yet.");
    }
    const session = await firebaseLoginWithGoogle();
    setUser(session);
    return session;
  }, []);

  const updateProfile = useCallback(
    async ({ name }) => {
      if (!user) return;
      if (firebaseEnabled) {
        const nextFb = await firebaseUpdateProfileName(name);
        if (nextFb) setUser(nextFb);
        return;
      }
      let next;
      if (user.token) {
        next = await apiUpdateProfile(user.token, { name });
      } else {
        next = updateUserProfile(user.email, { name });
      }
      saveSession(next);
      setUser(next);
    },
    [user],
  );

  const value = useMemo(
    () => ({
      user,
      authReady,
      isAuthenticated: Boolean(user),
      firebaseEnabled,
      login,
      signup,
      loginWithGoogle,
      logout,
      updateProfile,
    }),
    [user, authReady, login, signup, loginWithGoogle, logout, updateProfile],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
