import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { Route, Routes } from 'react-router-dom'
import { ApiError } from '../api/client'
import { ToastProvider } from '../components/Toast'
import { ComparePage } from '../pages/ComparePage'
import { DatasetDetailPage } from '../pages/DatasetDetailPage'
import { DatasetsPage } from '../pages/DatasetsPage'
import { ExternalImportPage } from '../pages/ExternalImportPage'
import { NotFoundPage } from '../pages/NotFoundPage'
import { OverviewPage } from '../pages/OverviewPage'
import { ProbabilityPage } from '../pages/ProbabilityPage'
import { ProvidersPage } from '../pages/ProvidersPage'
import { RunResultsPage } from '../pages/RunResultsPage'
import { RunSetupPage } from '../pages/RunSetupPage'
import { RunsPage } from '../pages/RunsPage'
import { ScenarioDetailPage } from '../pages/ScenarioDetailPage'
import { ScenariosPage } from '../pages/ScenariosPage'
import { ScenarioWizardPage } from '../pages/ScenarioWizardPage'
import { SettingsPage } from '../pages/SettingsPage'
import { TriagePage } from '../pages/TriagePage'
import { ProjectProvider } from './project'
import { Shell } from './Shell'

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        staleTime: 2000,
        retry: (count, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
          return count < 2
        },
      },
    },
  })
}

export function Providers({ children, client }: { children: ReactNode; client?: QueryClient }) {
  const [queryClient] = useState(() => client ?? makeQueryClient())
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <ProjectProvider>{children}</ProjectProvider>
      </ToastProvider>
    </QueryClientProvider>
  )
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<OverviewPage />} />
        <Route path="scenarios" element={<ScenariosPage />} />
        <Route path="scenarios/new" element={<ScenarioWizardPage />} />
        <Route path="scenarios/:id" element={<ScenarioDetailPage />} />
        <Route path="datasets" element={<DatasetsPage />} />
        <Route path="datasets/:id" element={<DatasetDetailPage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="runs/new" element={<RunSetupPage />} />
        <Route path="runs/:id" element={<RunResultsPage />} />
        <Route path="triage" element={<TriagePage />} />
        <Route path="probability" element={<ProbabilityPage />} />
        <Route path="compare" element={<ComparePage />} />
        <Route path="providers" element={<ProvidersPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="external/:id" element={<ExternalImportPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
