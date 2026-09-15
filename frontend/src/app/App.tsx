import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, useState, type ReactNode } from 'react'
import { Route, Routes } from 'react-router-dom'
import { ApiError } from '../api/client'
import { ToastProvider } from '../components/Toast'
import { ProjectProvider } from './project'
import { Shell } from './Shell'

// Pages load on demand so the first screen does not pay for every chart and editor.
const page = <K extends string>(load: () => Promise<Record<K, React.ComponentType>>, name: K) =>
  lazy(() => load().then((module) => ({ default: module[name] })))

const OverviewPage = page(() => import('../pages/OverviewPage'), 'OverviewPage')
const ScenariosPage = page(() => import('../pages/ScenariosPage'), 'ScenariosPage')
const ScenarioWizardPage = page(() => import('../pages/ScenarioWizardPage'), 'ScenarioWizardPage')
const ScenarioDetailPage = page(() => import('../pages/ScenarioDetailPage'), 'ScenarioDetailPage')
const DatasetsPage = page(() => import('../pages/DatasetsPage'), 'DatasetsPage')
const DatasetDetailPage = page(() => import('../pages/DatasetDetailPage'), 'DatasetDetailPage')
const RunsPage = page(() => import('../pages/RunsPage'), 'RunsPage')
const RunSetupPage = page(() => import('../pages/RunSetupPage'), 'RunSetupPage')
const RunResultsPage = page(() => import('../pages/RunResultsPage'), 'RunResultsPage')
const TriagePage = page(() => import('../pages/TriagePage'), 'TriagePage')
const ProbabilityPage = page(() => import('../pages/ProbabilityPage'), 'ProbabilityPage')
const ComparePage = page(() => import('../pages/ComparePage'), 'ComparePage')
const ProvidersPage = page(() => import('../pages/ProvidersPage'), 'ProvidersPage')
const SettingsPage = page(() => import('../pages/SettingsPage'), 'SettingsPage')
const ExternalImportPage = page(() => import('../pages/ExternalImportPage'), 'ExternalImportPage')
const NotFoundPage = page(() => import('../pages/NotFoundPage'), 'NotFoundPage')

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
