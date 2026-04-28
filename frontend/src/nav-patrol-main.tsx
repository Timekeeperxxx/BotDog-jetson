import { createRoot } from 'react-dom/client'
import './index.css'
import './styles/pcdMapDemo.css'
import { PcdMapDemoPage } from './pages/PcdMapDemoPage'

createRoot(document.getElementById('nav-patrol-root')!).render(
  <PcdMapDemoPage />,
)
