// The selected project, persisted locally. Every page reads it from here.

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { useProjects } from '../api/hooks'
import type { Project } from '../api/types'
import { readStorage, STORAGE_KEYS, writeStorage } from './storage'

type ProjectState = {
  projectId: string | null
  project: Project | null
  projects: Project[]
  setProjectId: (id: string) => void
  isPending: boolean
  error: unknown
  refetch: () => void
}

const ProjectContext = createContext<ProjectState>({
  projectId: null,
  project: null,
  projects: [],
  setProjectId: () => undefined,
  isPending: true,
  error: null,
  refetch: () => undefined,
})

export function ProjectProvider({ children }: { children: ReactNode }) {
  const query = useProjects()
  const [stored, setStored] = useState<string | null>(() => readStorage(STORAGE_KEYS.project))
  const setProjectId = useCallback((id: string) => {
    setStored(id)
    writeStorage(STORAGE_KEYS.project, id)
  }, [])
  const value = useMemo<ProjectState>(() => {
    const projects = query.data ?? []
    const project = projects.find((p) => p.id === stored) ?? projects[0] ?? null
    return {
      projectId: project?.id ?? null,
      project,
      projects,
      setProjectId,
      isPending: query.isPending,
      error: query.error,
      refetch: () => void query.refetch(),
    }
  }, [query, stored, setProjectId])
  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
}

export function useProject(): ProjectState {
  return useContext(ProjectContext)
}
