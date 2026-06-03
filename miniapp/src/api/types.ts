export interface TodayItem {
  medication_id: number
  name: string
  dosage: string
  meal_relation: string
  reminder_time: string
  status: 'pending' | 'taken' | 'skipped'
  is_due: boolean
  dependent_name: string | null
  linked_user_id?: number
  linked_user_name?: string
  dep_share_id?: number
  dep_share_name?: string
}

export interface IntakeIn {
  medication_id: number
  scheduled_time: string
  status: 'taken' | 'skipped' | 'pending'
}

export interface AdherenceMed {
  medication_id: number
  name: string
  dosage: string
  dependent_name: string | null
  due: number
  taken: number
  pct: number
}

export interface AdherenceResponse {
  medications: AdherenceMed[]
  total_pct: number | null
}

export interface StreakItem {
  dependent_id: number | null
  name: string | null
  streak: number
}

export type MealRelation = 'before' | 'after' | 'with' | 'any'
export type Frequency = 'daily' | 'interval' | 'weekdays' | 'monthly'

export interface ScheduleRule {
  medication_id?: number
  reminder_time: string
  frequency: Frequency
  interval_days: number | null
  weekdays: string | null
  month_day: number | null
  anchor_date: string | null
  dosage: string | null
}

export interface RuleIn {
  reminder_time: string
  frequency: Frequency
  interval_days?: number
  weekdays?: string
  month_day?: number
  anchor_date?: string
  dosage?: string
}

export interface Medication {
  id: number
  name: string
  dosage: string
  meal_relation: MealRelation
  times_per_day: number
  active: number
  paused: number
  dependent_id: number | null
  dependent_name: string | null
  stock_qty: number | null
  units_per_dose: number
  low_stock_days: number
  rules: ScheduleRule[]
  linked_user_id?: number
  linked_user_name?: string
  dep_share_id?: number
  dep_share_name?: string
}

export interface StockInfo {
  stock_qty: number | null
  units_per_dose: number
  low_stock_days: number
  days_left: number | null
}

export interface MedicationIn {
  name: string
  dosage: string
  meal_relation: MealRelation
  times_per_day: number
  dependent_id?: number | null
  for_linked_user_id?: number | null
  for_dep_share_id?: number | null
  rules: RuleIn[]
}

export interface Dependent {
  id: number
  name: string
}

export interface WeekStatRow {
  name: string
  dosage: string
  day: string
  taken: number
  skipped: number
  total: number
}

export interface CaregiverRequest {
  id: number
  caregiver_telegram_id: number
  caregiver_username: string | null
  created_at: string
}

export interface CaregiverLinkInfo {
  id: number
  status: string
  created_at: string
  break_requested?: number
  caregiver_telegram_id?: number
  caregiver_username?: string | null
  dependent_user_id?: number
  dependent_telegram_id?: number
  dependent_username?: string | null
  reminder_mode?: 'once' | 'repeat'
  reminder_repeat_hours?: number
  reminder_repeat_minutes?: number
  strict_mode?: number
  strict_mode_hours?: number
  strict_mode_minutes?: number
}

export interface UserSettings {
  timezone: string
  reminder_mode: 'once' | 'repeat'
  time_morning: string
  time_lunch: string
  time_evening: string
  time_night: string
  daily_plan_enabled: number
  daily_plan_time: string | null
  caregiver_enabled: number
  hearts: number
  strict_mode: number
  strict_mode_hours: number
  strict_mode_minutes: number
  reminder_repeat_hours: number
  reminder_repeat_minutes: number
  is_admin: boolean
  caregiver_code: string
  pending_requests: CaregiverRequest[]
  active_caregiver: CaregiverLinkInfo | null
  active_dependents: CaregiverLinkInfo[]
  pending_sent: CaregiverLinkInfo[]
  dep_shares: Record<string, DepShareInfo>
  viewing_deps: ViewingDepInfo[]
  pending_viewing_deps: PendingViewingDepInfo[]
}

export interface DepShareInfo {
  share_code: string | null
  active_viewer: { share_id: number; username: string } | null
  pending_viewers: { share_id: number; username: string }[]
}

export interface ViewingDepInfo {
  share_id: number
  dep_id: number
  dep_name: string
  owner_username: string
}

export interface PendingViewingDepInfo {
  share_id: number
  dep_name: string
  owner_username: string
}

export interface ServiceStatus {
  name: string
  unit: string
  status: string
}

export interface AdminStats {
  db: string
  redis: string
  services: ServiceStatus[]
  total_users: number
  total_meds: number
  active_today: number
  // system
  cpu_pct: number
  cpu_count: number
  load_1m: number
  ram_used_mb: number
  ram_total_mb: number
  ram_pct: number
  swap_used_mb: number
  swap_total_mb: number
  swap_pct: number
  disk_used_gb: number
  disk_free_gb: number
  disk_total_gb: number
  disk_pct: number
  // redis
  redis_mem?: string
  redis_clients?: number
  arq_queue?: number
  // db pool
  db_pool_size?: number
  db_pool_available?: number
  db_pool_requests?: number
}
