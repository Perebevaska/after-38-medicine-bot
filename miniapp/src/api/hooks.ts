import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, getInitDataRaw } from './client'
import type { TodayItem, IntakeIn, AdherenceResponse, StreakItem } from './types'

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
