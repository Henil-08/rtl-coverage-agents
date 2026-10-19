import { MotionConfig } from 'motion/react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Shell } from './components/Shell'
import { DesignPage } from './pages/DesignPage'
import { Library } from './pages/Library'
import { ModelsPage } from './pages/ModelsPage'
import { SessionPage } from './pages/SessionPage'

export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <BrowserRouter>
        <Shell>
          <Routes>
            <Route path="/" element={<Library />} />
            <Route path="/designs/:name" element={<DesignPage />} />
            <Route path="/sessions/:id" element={<SessionPage />} />
            <Route path="/models" element={<ModelsPage />} />
          </Routes>
        </Shell>
      </BrowserRouter>
    </MotionConfig>
  )
}
