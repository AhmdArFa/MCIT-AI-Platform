'use client'

import { useEffect, useState } from 'react'
import { Card } from '@/components/ui/card'
import { getConfig } from '@/lib/config'
import { Badge } from '@/components/ui/badge'
import { useTranslation } from '@/lib/hooks/use-translation'

export function SystemInfo() {
  const { t } = useTranslation()
  const [config, setConfig] = useState<{
    version: string
    latestVersion?: string | null
    hasUpdate?: boolean
  } | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const loadConfig = async () => {
      try {
        const cfg = await getConfig()
        setConfig(cfg)
      } catch (error) {
        console.error('Failed to load config:', error)
      } finally {
        setIsLoading(false)
      }
    }

    loadConfig()
  }, [])

  if (isLoading) {
    return (
      <Card className="p-6">
        <div className="space-y-4">
          <h2 className="font-display text-xl font-semibold tracking-tight">{t('advanced.systemInfo')}</h2>
          <div className="text-sm text-muted-foreground">{t('common.loading')}</div>
        </div>
      </Card>
    )
  }

  return (
    <Card className="p-6">
      <div className="space-y-4">
        <h2 className="font-display text-xl font-semibold tracking-tight">{t('advanced.systemInfo')}</h2>

        <div className="space-y-3">
          {/* Current Version */}
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">{t('advanced.currentVersion')}</span>
            <Badge variant="outline" className="font-mono text-[11px]">{config?.version || t('advanced.unknown')}</Badge>
          </div>

          {/* Latest Version */}
          {config?.latestVersion && (
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{t('advanced.latestVersion')}</span>
              <Badge variant="outline" className="font-mono text-[11px]">{config.latestVersion}</Badge>
            </div>
          )}

          {/* Update Status */}
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">{t('advanced.status')}</span>
            {config?.hasUpdate ? (
              <Badge variant="outline" className="border-transparent bg-warn-tint text-warn">
                {t('advanced.updateAvailable', { version: config.latestVersion || '' })}
              </Badge>
            ) : config?.latestVersion ? (
              <Badge variant="outline" className="text-fern border-fern/30">
                {t('advanced.upToDate')}
              </Badge>
            ) : (
              <Badge variant="outline" className="text-muted-foreground">
                {t('advanced.unknown')}
              </Badge>
            )}
          </div>


          {/* Version Check Failed Message */}
          {!config?.latestVersion && config?.version && (
            <div className="pt-2 text-xs text-muted-foreground">
              {t('advanced.updateCheckFailed')}
            </div>
          )}
        </div>
      </div>
    </Card>
  )
}
