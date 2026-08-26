import type { TaskItem, TaskStatus } from './types'

export function terminalTaskOverrideMessage(
  task: TaskItem,
  currentUserId: number,
  nextStatus: TaskStatus,
) {
  if (task.status === nextStatus) return null
  if (
    task.status === 'COMPLETED' &&
    task.completed_by &&
    task.completed_by.id !== currentUserId
  ) {
    return `Are you sure you want to change this task's status? It was marked Completed by ${task.completed_by.full_name}.`
  }
  if (
    task.status === 'DISMISSED' &&
    task.dismissed_by &&
    task.dismissed_by.id !== currentUserId
  ) {
    return `Are you sure you want to change this task's status? It was marked Dismissed by ${task.dismissed_by.full_name}.`
  }
  return null
}
