import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { Shell } from './App'
import './index.css'
import { ChatPage } from './pages/Chat'
import { PlanBoardPage } from './pages/PlanBoard'
import { ProfilePage } from './pages/Profile'
import { RecommendPage } from './pages/Recommend'
import { ReportPage } from './pages/Report'

const container = document.getElementById('root')
if (!container) throw new Error('index.html 缺少 #root 容器')

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Shell />}>
          {/* 根路径直接进建档向导：首屏就是向导本身，不做落地页（AGENTS.md §8.1） */}
          <Route index element={<Navigate to="/profile" replace />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/recommend" element={<RecommendPage />} />
          <Route path="/plan" element={<PlanBoardPage />} />
          <Route path="/report" element={<ReportPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="*" element={<Navigate to="/profile" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
