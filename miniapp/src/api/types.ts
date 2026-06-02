export interface TodayItem {
  medication_id: number
  name: string
  dosage: string
  meal_relation: string
  reminder_time: string
  status: 'pending' | 'taken' | 'skipped'
  dependent_name: string | null
}

export interface IntakeIn {
  medication_id: number
  scheduled_time: string
  status: 'taken' | 'skipped'
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
  rules: RuleIn[]
}

export interface Dependent {
  id: number
  name: string
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
}
