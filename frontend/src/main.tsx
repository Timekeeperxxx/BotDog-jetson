import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { AppRoot } from './AppRoot.tsx'
import { EventStreamProvider } from './runtime/EventStreamProvider'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <EventStreamProvider>
      <AppRoot />
    </EventStreamProvider>
  </StrictMode>,
)
