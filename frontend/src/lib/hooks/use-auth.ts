'use client'

import { useAuthStore } from '@/lib/stores/auth-store'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

/** Only same-origin paths are followed after sign-in (no open redirects). */
export function safeNext(next: string | null | undefined): string | null {
  if (!next || !next.startsWith('/') || next.startsWith('//')) return null
  return next
}

export function useAuth() {
  const router = useRouter()
  const { isAuthenticated, isLoading, login, logout, checkAuth, error, hasHydrated, user } = useAuthStore()

  useEffect(() => {
    if (hasHydrated) {
      void checkAuth()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasHydrated])

  const handleLogin = async (username: string, password: string, next?: string | null) => {
    const success = await login(username, password)
    if (success) {
      const target = safeNext(next)
      if (target?.startsWith('/api/oidc/')) {
        // Continue the Tut Agent sign-in on the server
        window.location.href = target
        return success
      }
      const stored = safeNext(sessionStorage.getItem('redirectAfterLogin'))
      sessionStorage.removeItem('redirectAfterLogin')
      router.push(target || stored || '/notebooks')
    }
    return success
  }

  const handleLogout = async () => {
    await logout()
    router.push('/login')
  }

  return {
    isAuthenticated,
    isLoading: isLoading || !hasHydrated,
    error,
    user,
    isAdmin: user?.role === 'admin',
    login: handleLogin,
    logout: handleLogout,
  }
}
