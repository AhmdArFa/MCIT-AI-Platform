import { cn } from '@/lib/utils'

/** Tut Agent's identity: Tutankhamun, the default MCIT-Agent avatar. */
export function TutAvatar({ size = 32, className }: { size?: number; className?: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src="/avatars/tutankhamun.webp"
      alt="Tut Agent"
      width={size}
      height={size}
      className={cn('shrink-0 rounded-full object-cover ring-1 ring-border', className)}
    />
  )
}
