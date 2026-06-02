import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, getInitDataRaw } from './client'
import type { TodayItem, IntakeIn, AdherenceResponse, StreakItem, Medication, MedicationIn, Dependent, StockInfo, UserSettings } from './types'

export function useToday() {
  return useQuery<TodayItem[]>({
    queryKey: ['today'],
    queryFn: () => api.get<TodayItem[]>('/today'),
    enabled: !!getInitDataRaw(),
  })
}

export function useAdherence() {
  return useQuery<AdherenceResponse>({
    queryKey: ['adherence'],
    queryFn: () => api.get<AdherenceResponse>('/stats/adherence'),
    enabled: !!getInitDataRaw(),
  })
}

export function useStreak() {
  return useQuery<StreakItem[]>({
    queryKey: ['streak'],
    queryFn: () => api.get<StreakItem[]>('/stats/streak'),
    enabled: !!getInitDataRaw(),
  })
}

export function useMedications() {
  return useQuery<Medication[]>({
    queryKey: ['medications'],
    queryFn: () => api.get<Medication[]>('/medications'),
    enabled: !!getInitDataRaw(),
  })
}

export function useDependents() {
  return useQuery<Dependent[]>({
    queryKey: ['dependents'],
    queryFn: () => api.get<Dependent[]>('/dependents'),
    enabled: !!getInitDataRaw(),
  })
}

export function useCreateMedication() {
  const qc = useQueryClient()
  return useMutation<{ id: number }, Error, MedicationIn>({
    mutationFn: (body) => api.post<{ id: number }>('/medications', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['medications'] })
      qc.invalidateQueries({ queryKey: ['today'] })
    },
  })
}

export function useUpdateMedication() {
  const qc = useQueryClient()
  return useMutation<void, Error, { id: number } & MedicationIn>({
    mutationFn: ({ id, ...body }) => api.put<void>(`/medications/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['medications'] })
      qc.invalidateQueries({ queryKey: ['today'] })
    },
  })
}

export function useDeleteMedication() {
  const qc = useQueryClient()
  return useMutation<void, Error, number>({
    mutationFn: (id) => api.delete<void>(`/medications/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['medications'] })
      qc.invalidateQueries({ queryKey: ['today'] })
    },
  })
}

export function usePauseMedication() {
  const qc = useQueryClient()
  return useMutation<void, Error, { id: number; paused: boolean }>({
    mutationFn: ({ id, paused }) =>
      api.post<void>(`/medications/${id}/${paused ? 'pause' : 'resume'}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['medications'] })
      qc.invalidateQueries({ queryKey: ['today'] })
    },
  })
}

export function useStock(medId: number) {
  return useQuery<StockInfo>({
    queryKey: ['stock', medId],
    queryFn: () => api.get<StockInfo>(`/medications/${medId}/stock`),
    enabled: !!getInitDataRaw(),
  })
}

export function useSetStock() {
  const qc = useQueryClient()
  return useMutation<void, Error, { medId: number; qty: number }>({
    mutationFn: ({ medId, qty }) => api.put<void>(`/medications/${medId}/stock`, { qty }),
    onSuccess: (_, { medId }) => {
      qc.invalidateQueries({ queryKey: ['stock', medId] })
      qc.invalidateQueries({ queryKey: ['medications'] })
    },
  })
}

export function useAddStock() {
  const qc = useQueryClient()
  return useMutation<void, Error, { medId: number; amount: number }>({
    mutationFn: ({ medId, amount }) => api.post<void>(`/medications/${medId}/stock/add`, { amount }),
    onSuccess: (_, { medId }) => {
      qc.invalidateQueries({ queryKey: ['stock', medId] })
      qc.invalidateQueries({ queryKey: ['medications'] })
    },
  })
}

export function useSetStockUnits() {
  const qc = useQueryClient()
  return useMutation<void, Error, { medId: number; units: number }>({
    mutationFn: ({ medId, units }) => api.put<void>(`/medications/${medId}/stock/units`, { units }),
    onSuccess: (_, { medId }) => {
      qc.invalidateQueries({ queryKey: ['stock', medId] })
    },
  })
}

export function useSetStockThreshold() {
  const qc = useQueryClient()
  return useMutation<void, Error, { medId: number; days: number }>({
    mutationFn: ({ medId, days }) => api.put<void>(`/medications/${medId}/stock/threshold`, { days }),
    onSuccess: (_, { medId }) => {
      qc.invalidateQueries({ queryKey: ['stock', medId] })
    },
  })
}

export function useDisableStock() {
  const qc = useQueryClient()
  return useMutation<void, Error, number>({
    mutationFn: (medId) => api.delete<void>(`/medications/${medId}/stock`),
    onSuccess: (_, medId) => {
      qc.invalidateQueries({ queryKey: ['stock', medId] })
      qc.invalidateQueries({ queryKey: ['medications'] })
    },
  })
}

export function useSettings() {
  return useQuery<UserSettings>({
    queryKey: ['settings'],
    queryFn: () => api.get<UserSettings>('/settings'),
    enabled: !!getInitDataRaw(),
  })
}

export function useSetReminderMode() {
  const qc = useQueryClient()
  return useMutation<void, Error, 'once' | 'repeat'>({
    mutationFn: (mode) => api.put<void>('/settings/reminder-mode', { mode }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })
}

export function useSetPreset() {
  const qc = useQueryClient()
  return useMutation<void, Error, { slot: string; time: string }>({
    mutationFn: ({ slot, time }) => api.put<void>(`/settings/presets/${slot}`, { time }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })
}

export function useSetDailyPlan() {
  const qc = useQueryClient()
  return useMutation<void, Error, { enabled: boolean; time?: string }>({
    mutationFn: (body) => api.put<void>('/settings/daily-plan', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })
}

export function useSetCaregiver() {
  const qc = useQueryClient()
  return useMutation<void, Error, boolean>({
    mutationFn: (enabled) => api.put<void>('/settings/caregiver', { enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })
}

export function useLogIntake() {
  const qc = useQueryClient()
  return useMutation<void, Error, IntakeIn>({
    mutationFn: (body) => api.post<void>('/today/intake', body),
    onMutate: async (intake) => {
      await qc.cancelQueries({ queryKey: ['today'] })
      const prev = qc.getQueryData<TodayItem[]>(['today'])
      qc.setQueryData<TodayItem[]>(['today'], (old) =>
        old?.map((item) =>
          item.medication_id === intake.medication_id &&
          item.reminder_time === intake.scheduled_time
            ? { ...item, status: intake.status }
            : item,
        ),
      )
      return { prev }
    },
    onError: (_err, _vars, ctx) => {
      const c = ctx as { prev?: TodayItem[] } | undefined
      if (c?.prev) qc.setQueryData(['today'], c.prev)
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['today'] })
      qc.invalidateQueries({ queryKey: ['streak'] })
      qc.invalidateQueries({ queryKey: ['adherence'] })
    },
  })
}
