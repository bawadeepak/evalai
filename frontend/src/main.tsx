import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { AppRoutes, Providers } from './app/App'
import { applyTheme, initialTheme } from './app/theme'
import './styles/tokens.css'
import './styles/app.css'
import './styles/extras.css'

applyTheme(initialTheme())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Providers>
        <AppRoutes />
      </Providers>
    </BrowserRouter>
  </StrictMode>,
)
