"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import React from "react";
import { EngramiaClient } from "./api";

const STORAGE_KEY_TOKEN = "engramia_token";
const STORAGE_KEY_URL = "engramia_url";
const STORAGE_KEY_ROLE = "engramia_role";

interface AuthState {
  token: string | null;
  baseUrl: string;
  role: string;
  client: EngramiaClient | null;
  login: (token: string, baseUrl: string) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthState>({
  token: null,
  baseUrl: "",
  role: "reader",
  client: null,
  login: async () => {},
  logout: () => {},
  isAuthenticated: false,
});

export function useAuth() {
  return useContext(AuthContext);
}

function getStored(key: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  return localStorage.getItem(key) ?? fallback;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [role, setRole] = useState("reader");
  const [client, setClient] = useState<EngramiaClient | null>(null);
  const [ready, setReady] = useState(false);

  // Hydrate from localStorage on mount
  useEffect(() => {
    const t = getStored(STORAGE_KEY_TOKEN, "");
    const u = getStored(STORAGE_KEY_URL, "");
    const r = getStored(STORAGE_KEY_ROLE, "reader");
    if (t && u) {
      setToken(t);
      setBaseUrl(u);
      setRole(r);
      setClient(new EngramiaClient(u, t));
    }
    setReady(true);
  }, []);

  const login = useCallback(async (newToken: string, newUrl: string) => {
    const c = new EngramiaClient(newUrl, newToken);
    // Validate connection
    await c.health();

    // Detect role
    let detectedRole = "reader";
    try {
      const keys = await c.listKeys();
      const prefix = newToken.slice(0, 16);
      const match = keys.keys.find((k) => k.key_prefix.startsWith(prefix));
      if (match) detectedRole = match.role;
    } catch {
      // keys:list requires admin+, fallback to reader
    }

    localStorage.setItem(STORAGE_KEY_TOKEN, newToken);
    localStorage.setItem(STORAGE_KEY_URL, newUrl);
    localStorage.setItem(STORAGE_KEY_ROLE, detectedRole);

    setToken(newToken);
    setBaseUrl(newUrl);
    setRole(detectedRole);
    setClient(c);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY_TOKEN);
    localStorage.removeItem(STORAGE_KEY_URL);
    localStorage.removeItem(STORAGE_KEY_ROLE);
    setToken(null);
    setBaseUrl("");
    setRole("reader");
    setClient(null);
  }, []);

  if (!ready) return null;

  return React.createElement(
    AuthContext.Provider,
    {
      value: {
        token,
        baseUrl,
        role,
        client,
        login,
        logout,
        isAuthenticated: !!token,
      },
    },
    children,
  );
}
