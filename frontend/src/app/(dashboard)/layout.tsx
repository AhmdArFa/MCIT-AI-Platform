'use client'

import { useAuth } from '@/lib/hooks/use-auth'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { ModalProvider } from '@/components/providers/ModalProvider'
import { CreateDialogsProvider } from '@/lib/hooks/use-create-dialogs'
import { CommandPalette } from '@/components/common/CommandPalette'
import { AdminGate } from '@/components/admin/AdminParts'

// Platform configuration pages: administrators only (the API enforces it too)
const ADMIN_ROUTES = ['/admin', '/settings', '/transformations', '/advanced']

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const { isAuthenticated, isLoading } = useAuth()
  const router = useRouter()
  const pathname = usePathname() || ''
  const adminRoute = ADMIN_ROUTES.some((r) => pathname === r || pathname.startsWith(`${r}/`))
  const [hasCheckedAuth, setHasCheckedAuth] = useState(false)


  useEffect(() => {
    // Mark that we've completed the initial auth check
    if (!isLoading) {
      setHasCheckedAuth(true)

      // Redirect to login if not authenticated
      if (!isAuthenticated) {
        // Store the current path to redirect back after login
        const currentPath = window.location.pathname + window.location.search
        sessionStorage.setItem('redirectAfterLogin', currentPath)
        router.push('/login')
      }
    }
  }, [isAuthenticated, isLoading, router])

  // Show loading spinner during initial auth check or while loading
  if (isLoading || !hasCheckedAuth) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  // Don't render anything if not authenticated (during redirect)
  if (!isAuthenticated) {
    return null
  }

  return (
    <ErrorBoundary>
      <CreateDialogsProvider>
        {adminRoute ? <AdminGate>{children}</AdminGate> : children}
        <ModalProvider />
        <CommandPalette />
      </CreateDialogsProvider>
    </ErrorBoundary>
  )
}
