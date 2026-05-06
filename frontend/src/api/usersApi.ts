import { apiFetch } from './apiFetch'

export type Role = 'viewer' | 'operator' | 'admin'

export interface User {
  id: number
  username: string
  role: Role
  enabled: boolean
  must_change_password: boolean
  created_at: string
  updated_at: string
  last_login_at: string | null
  deleted_at: string | null
}

export interface CreateUserPayload {
  username: string
  password: string
  role: Role
  enabled?: boolean
  must_change_password?: boolean
}

export interface UpdateUserPayload {
  role?: Role
  enabled?: boolean
  must_change_password?: boolean
}

export interface ResetPasswordPayload {
  new_password: string
}

export interface ChangePasswordPayload {
  old_password: string
  new_password: string
}

export const usersApi = {
  listUsers(): Promise<User[]> {
    return apiFetch<User[]>('/api/v1/users')
  },

  createUser(payload: CreateUserPayload): Promise<User> {
    return apiFetch<User>('/api/v1/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  },

  updateUser(userId: number, payload: UpdateUserPayload): Promise<User> {
    return apiFetch<User>(`/api/v1/users/${userId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  },

  deleteUser(userId: number): Promise<void> {
    return apiFetch<void>(`/api/v1/users/${userId}`, {
      method: 'DELETE',
    })
  },

  resetPassword(userId: number, payload: ResetPasswordPayload): Promise<{ detail: string }> {
    return apiFetch<{ detail: string }>(`/api/v1/users/${userId}/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  },

  changePassword(payload: ChangePasswordPayload): Promise<{ detail: string }> {
    return apiFetch<{ detail: string }>('/api/v1/users/change-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  },
}
