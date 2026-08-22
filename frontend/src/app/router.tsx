import { Navigate, createBrowserRouter } from 'react-router-dom'

import { AppShell } from '../components/AppShell'
import { ActivityPage } from '../pages/ActivityPage'
import {
  AgentRoute,
  ManagerRoute,
  ProtectedRoute,
} from '../components/RouteGuards'
import { CaseDetailPage } from '../pages/CaseDetailPage'
import { CasesPage } from '../pages/CasesPage'
import { DashboardPage } from '../pages/DashboardPage'
import { GmailConnectionsPage } from '../pages/GmailConnectionsPage'
import { LoginPage } from '../pages/LoginPage'
import { AgentsPage } from '../pages/manager/AgentsPage'
import { AnalyticsPage } from '../pages/manager/AnalyticsPage'
import { CarriersPage } from '../pages/manager/CarriersPage'
import { SystemLogsPage } from '../pages/manager/SystemLogsPage'
import { ProfilePage } from '../pages/ProfilePage'
import { ReviewsPage } from '../pages/ReviewsPage'
import { ReviewDetailPage } from '../pages/ReviewDetailPage'
import { TasksPage } from '../pages/TasksPage'

export const managerRoutes = [
  { path: 'manager/analytics', element: <AnalyticsPage /> },
  { path: 'manager/agents', element: <AgentsPage /> },
  { path: 'manager/carriers', element: <CarriersPage /> },
  { path: 'manager/system-logs', element: <SystemLogsPage /> },
]

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
          {
            element: <AgentRoute />,
            children: [{ path: 'activity', element: <ActivityPage /> }],
          },
          { path: 'reviews', element: <ReviewsPage /> },
          { path: 'reviews/:reviewId', element: <ReviewDetailPage /> },
          { path: 'gmail-connections', element: <GmailConnectionsPage /> },
          { path: 'profile', element: <ProfilePage /> },
          {
            element: <ManagerRoute />,
            children: managerRoutes,
          },
        ],
      },
    ],
  },
])
