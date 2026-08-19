import { Navigate, createBrowserRouter } from 'react-router-dom'

import { AppShell } from '../components/AppShell'
import { ManagerRoute, ProtectedRoute } from '../components/RouteGuards'
import { CaseDetailPage } from '../pages/CaseDetailPage'
import { CasesPage } from '../pages/CasesPage'
import { DashboardPage } from '../pages/DashboardPage'
import { GmailConnectionsPage } from '../pages/GmailConnectionsPage'
import { LoginPage } from '../pages/LoginPage'
import {
  AgentsPage,
  AnalyticsPage,
  CarriersPage,
  SettingsPage,
  SystemLogsPage,
} from '../pages/ManagerPages'
import { ProfilePage } from '../pages/ProfilePage'
import { ReviewsPage } from '../pages/ReviewsPage'
import { TasksPage } from '../pages/TasksPage'

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    element: <ProtectedRoute />,
    children: [
      {
        path: '/',
        element: <AppShell />,
        children: [
          { index: true, element: <Navigate to="/dashboard" replace /> },
          { path: 'dashboard', element: <DashboardPage /> },
          { path: 'cases', element: <CasesPage /> },
          { path: 'cases/:caseId', element: <CaseDetailPage /> },
          { path: 'tasks', element: <TasksPage /> },
          { path: 'reviews', element: <ReviewsPage /> },
          { path: 'gmail-connections', element: <GmailConnectionsPage /> },
          { path: 'profile', element: <ProfilePage /> },
          {
            element: <ManagerRoute />,
            children: [
              { path: 'manager/analytics', element: <AnalyticsPage /> },
              { path: 'manager/agents', element: <AgentsPage /> },
              { path: 'manager/carriers', element: <CarriersPage /> },
              { path: 'manager/system-logs', element: <SystemLogsPage /> },
              { path: 'manager/settings', element: <SettingsPage /> },
            ],
          },
        ],
      },
    ],
  },
])
