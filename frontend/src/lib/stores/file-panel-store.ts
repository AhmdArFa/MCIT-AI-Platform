import { create } from 'zustand'

interface FilePanelState {
  fileId: string | null
  ownerId: string | null
  fullscreen: boolean
  open: (id: string, ownerId?: string) => void
  close: () => void
  toggleFullscreen: () => void
}

export const useFilePanel = create<FilePanelState>((set) => ({
  fileId: null,
  ownerId: null,
  fullscreen: false,
  open: (id, ownerId) => set({ fileId: id, ownerId: ownerId ?? null, fullscreen: true }),
  close: () => set({ fileId: null, ownerId: null, fullscreen: false }),
  toggleFullscreen: () => set((s) => ({ fullscreen: !s.fullscreen })),
}))
