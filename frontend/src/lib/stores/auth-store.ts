import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { getApiUrl } from '@/lib/config'

export type Role = 'admin' | 'user'

export interface SessionUser {
  id: string
  username: string
  display_name: string
  role: Role
  active: boolean
  created?: string | null
  last_login?: string | null
}

interface AuthState {
  isAuthenticated: boolean
  token: string | null
  user: SessionUser | null
  isLoading: boolean
  error: string | null
  lastAuthCheck: number | null
  isCheckingAuth: boolean
  hasHydrated: boolean
  setHasHydrated: (state: boolean) => void
  login: (username: string, password: string) => Promise<boolean>
  logout: () => Promise<void>
  checkAuth: () => Promise<boolean>
}

const CHECK_INTERVAL_MS = 30_000

async function readError(response: Response): Promise<string> {
  if (response.status === 401) return 'Wrong username or password.'
  if (response.status === 429) return 'Too many attempts. Wait a moment and try again.'
  if (response.status >= 500) return 'The server could not sign you in. Try again shortly.'
  try {
    const body = await response.json()
    return typeof body?.detail === 'string' ? body.detail : `Sign-in failed (${response.status})`
  } catch {
    return `Sign-in failed (${response.status})`
  }
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      isAuthenticated: false,
      token: null,
      user: null,
      isLoading: false,
      error: null,
      lastAuthCheck: null,
      isCheckingAuth: false,
      hasHydrated: false,

      setHasHydrated: (state: boolean) => set({ hasHydrated: state }),

      login: async (username: string, password: string) => {
        set({ isLoading: true, error: null })
        try {
          const apiUrl = await getApiUrl()
          // Raw fetch: the apiClient interceptors would attach a stale token
          // and redirect on 401.
          const response = await fetch(`${apiUrl}/api/auth/login`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: username.trim(), password }),
          })
          if (!response.ok) {
            set({ error: await readError(response), isLoading: false, isAuthenticated: false, token: null, user: null })
            return false
          }
          const session = await response.json()
          set({
            isAuthenticated: true,
            token: session.token,
            user: session.user,
            isLoading: false,
            lastAuthCheck: Date.now(),
            error: null,
          })
          return true
        } catch {
          set({
            error: 'Unable to reach the server. Check that MCIT AI is running.',
            isLoading: false,
            isAuthenticated: false,
            token: null,
            user: null,
          })
          return false
        }
      },

      logout: async () => {
        try {
          const apiUrl = await getApiUrl()
          await fetch(`${apiUrl}/api/auth/logout`, { method: 'POST', credentials: 'include' })
        } catch {
          // Signing out locally is enough when the server is unreachable
        }
        set({ isAuthenticated: false, token: null, user: null, error: null, lastAuthCheck: null })
      },

      checkAuth: async () => {
        const { token, lastAuthCheck, isCheckingAuth, isAuthenticated } = get()
        if (isCheckingAuth) return isAuthenticated
        if (!token) {
          set({ isAuthenticated: false })
          return false
        }
        const now = Date.now()
        if (isAuthenticated && lastAuthCheck && now - lastAuthCheck < CHECK_INTERVAL_MS) return true

        set({ isCheckingAuth: true })
        try {
          const apiUrl = await getApiUrl()
          const response = await fetch(`${apiUrl}/api/auth/me`, {
            headers: { Authorization: `Bearer ${token}` },
            credentials: 'include',
          })
          if (response.ok) {
            const body = await response.json()
            set({ isAuthenticated: true, user: body.user, lastAuthCheck: now, isCheckingAuth: false })
            return true
          }
          set({ isAuthenticated: false, token: null, user: null, lastAuthCheck: null, isCheckingAuth: false })
          return false
        } catch {
          // Keep the session through a transient network failure
          set({ isCheckingAuth: false })
          return isAuthenticated
        }
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({ token: state.token, user: state.user, isAuthenticated: state.isAuthenticated }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true)
      },
    }
  )
)

export const useIsAdmin = () => useAuthStore((s) => s.user?.role === 'admin')
