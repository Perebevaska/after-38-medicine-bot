# Выполненные фазы (архив roadmap)

Завершённые фазы вынесены из `CLAUDE.md`. Закрытые баги — `HISTORY.md`. Полный аудит (2026-06-03) — `cloud.md`.

**Размер:** `S` < 1д · `M` 2–5д · `L` 1–2 нед · **Критичность:** 🔴 блокер · 🟡 важно · 🟢 желательно

---

## Закрытый тех-долг (бывш. Known Issues)

- **Аудит 2026-06-03** ✅ (`cloud.md`) — **всё закрыто**: F-1 npm valibot ReDoS → `overrides: valibot ^1.2.0` (0 vuln); D-1 sandbox-харднинг (OP6); B-1 `await` уведомлений в `dependent_shares` (не терять при GC); B-2 дефолт rate-limit 60→300; B-3 `/health` не отдаёт текст ошибок; D-4 backup-таймер в деплое (OP7); D-5 health-check после отката в CI; pool `open=True`.
  - **venv→3.14**: локальный venv пересобран на Python 3.14.5 (deadsnakes ppa) — совпадает с CI/прод; все cp314-колёса есть.
  - **TestClient deprecation**: глушится адресно через `filterwarnings` в `pytest.ini`. pytest = 0 warnings.
  - **Caddyfile**: вынесен в `deploy/Caddyfile.template` (единый источник); `setup.sh` рендерит через sed, CI ресинкает при `secrets.CADDY_DOMAIN` (graceful `caddy reload`).
- **AX11** ✅ Дубли SQL устранены: общие `_RULE_COLS` + `_USER_RULES_FROM` в `database.py`. Горячий путь `get_active_schedule_rows` сохранил собственный FROM.
- Фронт-lint `set-state-in-effect` — закрыт точечными `eslint-disable` (CI-гейт жёсткий, `continue-on-error` снят).
- Регресс-тест Dashboard ✅ vitest + 19 тестов (`miniapp/src/pages/Dashboard.test.tsx`): empty-state, секции Сейчас/Сегодня, TZ-баннер, статус taken/skipped, SlideToConfirm-жест, SkipButton, «Принять всё» double-tap, hold-hint, F7 read-only / F8 / локальный близкий.

---

## Фаза 8 — Надёжность эксплуатации ✅
**OP1** ✅ `Restart=always` + StartLimit на всех 3 юнитах (`deploy/systemd/`). Live = bare systemd+venv.
**OP2** ✅ `ci-cd.yml` deploy-step: `systemctl is-active --quiet` по всем сервисам.
**OP3** ✅ `OnFailure=medbot-alert@%n.service` → `deploy/alert.sh` (Telegram-алерт + 8 строк лога). ⚠️ НЕ ловит «тихие» сбои.
**OP4** ✅ `SystemMaxUse=200M` journald.
**OP5** ✅ Push опекуну при пропуске приёма подопечным → реализован в Фазе 10-C.
**OP6** ✅ Sandbox-харднинг 3 юнитов: `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=read-only`, `ReadWritePaths`, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`, `SystemCallFilter=@system-service`. Юзер root (app в /root). БД через TCP `127.0.0.1`.
**OP7** ✅ Бэкап-юниты в репо (`deploy/backup/medbot-backup.{service,timer}`). CI/setup.sh раскатывают + `systemctl enable --now medbot-backup.timer` (ежедневный pg_dump, ротация 7 дней).

---

## UX-интеграция бот ↔ Mini App
**U1/U2/U3** ⛔ Переформулированы → поглощены Фазой 10.

## Фаза 7 — Рефакторинг «Статистики» ✅
**S1** ✅ Позитивный тон · **S2** ✅ «дней с пропусками» (`SkippedBadge`) · **S3** ✅ Вёрстка ReportCard

## F7 — Caregiver-связь двух аккаунтов ✅
Backend (caregiver_links, caregiver_code, API, блокировки 403) + frontend (блок «Забота», read-only приёмы, CRUD аптечки, HH:MM TimePicker для подопечного). Все фазы 1–3 закрыты. Доп.: двухшаговая отвязка, tz-баннер на Dashboard.

## F8 — Шаринг локального близкого ✅
Backend (dependent_shares, share_code, viewer CRUD, intake, transfer-on-revoke, сердечки всем в связке) + frontend (секции own/linked/shared, единый «Для кого», блок «Забота» с «Запросы»/«Мои близкие»/«Помогаю», `PendingCard`). Bug-fix: F7-помощник больше не видит локальных близких подопечного.

## Mini App — UX-долг
**UX-B** ✅ Аудит race conditions — дедупликация/отмена таймеров.

## Фаза 9 — Frontend аудит (2026-06-03) ✅
FA-B1 (дефолт запаса→5), FA-B2 (React-key linked), FA-B3 (откат оптимистики handleTakeAll), FA-D1/D2 (мёртвый код hooks), FA-R1 (TimePicker), FA-R2 (constants.ts), FA-R3 (inline-style→классы), FA-R4/R5, FA-BE1 (`/stats/adherence` падал — `count_due_by_medication` со списком + `date.fromisoformat`).
- **FA-P1** ⏸ By design: все 4 таб-панели монтируются сразу (плавный свайп). Не трогать.

---

## Фаза 10 — Разделение ролей бот ↔ Mini App (2026-06-03) ✅ `L`
**Цель:** убрать дублирование. Бот = напоминания + ✓/✕ подтверждение приёма + подтверждение/отклонение связей «Забота» + пуши. Управление — только Mini App. tz-онбординг в боте при `/start` оставлен. Код бот-хендлеров удалён. PDF из бота убран (Mini App шлёт PDF в чат).

**10-A ✅ — ник в уведомлениях «Забота».** caregiver_links: запрос/request-break → `@username`; обратные уведомления confirm/decline. dependent_shares: join/decline уведомления. Хелперы `get_caregiver_link_parties`/`get_dep_share_parties`.

**10-B ✅ — F7/F8 confirm/decline inline в боте.** Уведомления несут `[✅ Подтвердить][❌ Отклонить]`; `handlers/care_links.py` (callback `cglink:`/`depshare:`) → `db.confirm_*/decline_*` + обратное уведомление. `_bot_notify` принимает `reply_markup`.

**10-C ✅ — OP5 пуш помощникам при пропуске.** scheduler строгий: auto-skipped → пуш опекунам (F7) / наблюдателям (F8). `get_caregiver_tids_for_dependent`/`get_dep_share_viewer_tids`; `_notify_caregivers_on_miss`. Тесты `test_miss_notify.py`.

> **Тесты локально:** роль `medbot` использует прод-пароль из `.env`. Гонять pytest с `TEST_DATABASE_URL=postgresql://medbot:<пароль>@127.0.0.1/medbot_test`. CI не затронут (контейнер `medbot:medbot`).

**10-D ✅ — де-дупликация (экстракция + снос бот-UI).** Меню → 3 пункта: `📱 Приложение` / `📋 Лекарства на сегодня` / `ℹ️ О проекте`. Удалены `handlers/{meds,meds_common,meds_add,meds_edit,caregiver,stock,settings,stats,export,admin}.py` + регистрации в `bot.py`. Экстракция чистой логики: `adherence.py` ← `adherence_window`/`compute_adherence`; `reports.py` ← PDF-builder'ы; `streak.py` += `_streak_phrase`/`_plural_days`; `constants.MEAL_LABELS_TEXT`. `handlers/` = только `timezone.py` + `care_links.py`.

---

## Фаза 11 — Упаковка / доза / курс + тексты бота (2026-06-04) ✅ `M` (кроме F — см. CLAUDE.md)
**B ✅** `ABOUT_TEXT` без ссылки GitHub; тон → «Напоминаю вовремя принять лекарства и отмечаю приёмы»; Dashboard «Выпил всё» → «Принять всё».

**A1 ✅ — backend + схема.** Новые колонки `medications`: `unit_dose_value`/`unit_dose_label`, `dose_per_intake`, `pack_size` (→ стартовый `stock_qty`), `course_total`. `compute_units_per_dose()` на сервере. `get_course_progress()` = COUNT(taken); `set_course_total()`; `POST /medications/{id}/course/continue`. Rules опциональны. GET /medications отдаёт `course_done`.

**A2/A3 ✅ — фронт.** Форма: блоки Упаковка + Приём и курс; `NumberDrum`; авторасчёт «≈ N ед»; `parseDosage` для старых строк; расписание опционально. Список: бейдж/прогресс курса, баннер «Курс пройден → Продолжить/Удалить», «Добавить расписание». Отклонение от ТЗ: расписание не инлайн, кнопка открывает форму на блоке (prop `openSchedule`).

**C-1 ✅ — рефактор «Статистика» → «Прогресс».** Чистый `analytics.py`: `best_streak` · `daily_adherence`/`window_pct`/`weekly_adherence` (окна 7/30/90 + недельные бакеты, кламп по `created_at`) · `punctuality` (отклонение `taken_at − scheduled_time`; распределение early/ontime/late ±30 мин, «проблемный час», скрыто при `sample < 10`) · `therapy_load`. Эндпоинт `GET /stats/overview` (собственная терапия, окно 90д). Фронт `StatsPage.tsx`: StreakCard → LoadCard → AdherenceCard (+ WeeklyGraph) → PunctualityCard. Хук `useStatsOverview`. Демо: `seed_admin_stats.py`. Тесты `test_analytics.py` + `test_stats_overview_shape`.

**D ✅ — UX формы: компактность.** «Как принимать» и «Приёмов в день» → чип-раскрытие. 2 колонки (`.form-grid2`). «Приём №» → карточка `.rule-card` (`.rule-num` + чип `🕐 HH:MM`).

**E ✅ — своя доза на приём.** Тоггл «Разная доза по приёмам» (`form.per_dose`) → у `RuleSection` поле дозы; хранится в `schedule_rules.dosage`. Поприёмное списание `apply_intake_stock(med_id, status, old, scheduled_time)`: своя `dosage` по `reminder_time`, иначе единая `units_per_dose`. `today.py` шлёт `scheduled_time`; scheduler/skip → `None`.

**E2 ✅ — UX блока «расписание».** «Удалить расписание» наверх блока. Барабан «Приёмов в день» убран → «+ Добавить приём» внизу + ✕ на `rule-card`. `times_per_day` синхронится с `rules.length` (`addRule`/`removeRule`/`syncRules`).

**Haptic ✅** — slide/hold на Dashboard: `postEvent('web_app_trigger_haptic_feedback', {type:'impact', impact_style:'heavy'})`. Требует `web_app_ready` при старте (`main.tsx`). Фоллбэк `navigator.vibrate`.

---

## Фаза 11-F — чередование доз по дням (2026-06-04) ✅
v1 только `daily`; взаимоисключает с поприёмной дозой E.
- Колонка `schedule_rules.dose_cycle` (CSV "50,75"); единица общая (`unit_dose_label`); реф-дата = `anchor_date`.
- Хелпер `schedule_utils.cycle_dose_for_day(dose_cycle, anchor, day)` → токен дозы дня, индекс `(день − anchor) % len`.
- Списание `apply_intake_stock(..., day)` — цикл приоритетнее фикс-дозы правила; `today.py` шлёт дату.
- Показ дозы дня: `today.py` (Mini App) + `scheduler.py` (TG-напоминание + план дня).
- API `RuleIn.dose_cycle`: валидация (только daily, нужен anchor_date, ≥2 дозы, несовместим с dosage) → 422.
- Форма: чекбокс «Чередовать дозы по дням» в RuleSection.

---

## Фаза 11 C-2 — паттерны/риск (2026-06-04) ✅ (за гейтом ≥21 день)
2 сигнала, остальные отменены. Чистая `analytics.risk_signals(daily, intakes, tz, today)` → `{ready, history_days, signals[]}`; гейт `history_days<21 → ready:False`. В `overview` ключ `risk`; фронт `RiskCard` в `StatsPage` (рендер при signals>0, дисклеймер «не диагноз»). Тесты `test_analytics` (+контракт overview в `test_api_endpoints`).
- ✅ **«Нарастающий риск»** (`rising_risk`, warn) — пропуски неделя A vs B (триггер B≥A+3 и ≥4). Не зависит от `taken_at`.
- ✅ **«Нестабильный график»** (`unstable_timing`, info) — population stdev отметок ≥90 мин на слоте с ≥8 приёмами.
- ❌ Отменены: «изменение привычки», «высокий риск сегодня/по вторникам» (слабая семантика из-за `taken_at`-caveat + шум при малой выборке). PDF-отчёты — как есть.

---

## Фаза 11.1 — UX-замечания (2026-06-04) ✅
1. ✅ Склонение «препараты» по числу (`plural` RU one/few/many).
2. ✅ Описание окон соблюдения 7/30/90 (подзаголовок).
3. ✅ Отчёты — убран «Мой прогресс».
4. ✅ «Забота»: единый блок-секция по владельцу для всех типов; выделение имени.
5. ✅ Терминология «лекарство» → «препарат» во всём UI (mini app + бот + PDF + ошибки API).
6. ✅ Empty-state «Приёмы» компактнее; пустой MedicationList без тавтологии.

---

## Фаза 13 — Тема (режим) (2026-06-04) ✅
Тема = режим (фон/текст). Переменные из JS (`theme.ts → applyTheme`) в `<html>` через `style.setProperty`.
- **Режим** (3 кнопки `theme-seg`, ключ `theme_pref`): `auto` = цвета Telegram / `light` / `dark`. Реакция на `themeChanged` в режиме auto.
- Палитра акцента снесена в Ф18 — единый бренд-акцент `ACCENT` (sea-green `#2b8a9e` light / `#4fb3c7` dark).
- Закрыты undefined CSS-переменные. `index.css` = фоллбэк до JS, без FOUC; `initTheme()` в `main.tsx`.
- Хранение — localStorage (кросс-девайс синк отложен в Ф16). Только фронт.

---

## Фаза 18 — Визуальный язык (2026-06-04) ✅ `M`
**18.1 ✅ — палитра убита.** Снесены `PALETTES`/`KEY_PALETTE`/`accentFor` и т.д. из `theme.ts` + `palette-*` CSS + UI-блок в SettingsPage. Один бренд-акцент `ACCENT`. Режим сохранён.

**18.2 ✅ — эмодзи в хроме → Lucide.** `💊`→`Pill` · `📦`→`Package` · `🕐`→`Clock` · `🏆`→`Trophy` · `🔥`→`Flame` · `🔒`→`Lock` · `📋/📅/🩺`→`ClipboardList/Calendar/Stethoscope` · `⏳/✅/⚠️`→`Loader2(.spin)/Check/AlertTriangle` · `👤/👥`→`User/Users` · `⏸`→`Pause` · `🗑`→`Trash2` · `☀/🌙`→`Sun/Moon` · `📍`→`MapPin` · `🌍`→`Globe` · `🔔/🔗`→`Bell/Link2` · `✓/✕/←/→`→`Check/X/ArrowLeft/ArrowRight` · `⎘`→`Copy`. Класс `.ic` для выравнивания; `.spin`. Оставлены эмодзи-контент: `❤/💔`, бейджи, `👋`.

**18.3 ✅ — ачивки-плитки + сдержанная типографика.** Ачивки: эмодзи → CSS-плитка (squircle, плоский тон уровня, белый глиф). `ACH_VISUAL` (code→{tier,Icon}) в StatsPage. `font-variant-numeric: tabular-nums` на метриках; `.streak-fire` `#f5934e`.

**18.4 ✅ — отметка приёма: слайдер вместо удержания (Dashboard).** `SlideToConfirm` (тянем вправо → `onConfirm('taken')` + haptic; недотянул → откат; `setPointerCapture`). `SkipButton` (тап → подтверждение 3с). Pending-карточка вертикальная (`.mlist-card--slide`). Подпись гаснет после первой отметки (localStorage `slide_learned`). Снесены `HoldButton`/`.hold-*`/мёртвые `.btn-take/skip/undo`.

---

## Фаза 19 — Синхронизация бот ↔ app + тексты (2026-06-04) ✅
**19.1 ✅ — TG-сообщение зависало с кнопками после отметки в app.** `worker.send_reminder(track_key=...)` → Redis `rmd:{med}:{HH:MM}:{YYYY-MM-DD}` → `{chat_id, message_id, text}` (TTL 13ч). `worker.edit_reminder(chat_id, message_id, text)` — `bot.edit_message_text` без `reply_markup` + статус. `api/main` поднимает `_arq_pool` в lifespan. `POST /today/intake` → `_sync_reminder_message` (best-effort). Ограничение: в repeat редактируется только последнее напоминание слота.

**19.2 ✅ — app не обновлялся из фона.** `visibilitychange`-хук в `App.tsx`: при `visible` → `queryClient.invalidateQueries()`.

**19.3 ✅ — хинт кода в «Забота».** `XXXX-XXXX-XXXX` → «подключиться к профилю близкого с другого устройства».

**19.4 ✅ — welcome бота: «лекарства» → «препараты».** ⚠️ Описание в BotFather (`/description`, `/setabouttext`) — вне кода, обновить вручную.

**19.5 ✅ — маска ввода кода «Забота».** `formatCodeInput()` чистит до `[A-Z0-9]`, режет по 4, вставляет `-` (max `XXXX-XXXX-XXXX`); trailing-dash срезается.

---

## Фаза 14 — Онбординг (2026-06-04) ✅
- **Empty-state «Приёмы»** (№7): `Dashboard` грузит `useMedications`; различает нет лекарств / все на паузе / нет приёмов сегодня. `onNavigate` из `App`.
- **Spotlight-тур** (№8): `components/OnboardingTour.tsx` — 4 шага, подсветка `.nav-item` через `getBoundingClientRect` (cutout `box-shadow`). Флаг `onboarding_done` в localStorage. `resetOnboarding()` на удалении аккаунта.
- **Повтор тура из Настроек** ✅ (commit d546e70).
- **Удаление расписания**: кнопка `schedule-remove-btn` → `rules:[]` → `update_medication` убирает `schedule_rules`, лекарство остаётся пакетом.

## Фаза 12a — Ачивки ✅
Детерминированные бейджи по абсолютным порогам (`achievements.py`: каталог 9 бейджей + `evaluate()`).
- Пороги: приёмы 10/100/500 · серия (best) 7/30/100 · соблюдение ≥90% за 30/90д (гейт `due≥20/60`) · первая «Забота».
- Таблица `achievements(user_id, code, unlocked_at)` UNIQUE(user_id,code). DB: `count_total_taken`/`has_any_care_link`/`get_achievements`/`unlock_achievements`.
- Ленивый анлок в `GET /stats/overview` → блок `achievements{catalog, unlocked, newly}`.
- Фронт: `AchievementsCard` (грид 3-кол, тап → хинт) + `AchievementToast`. Бейджи на иконки меню (`App.tsx`, `NavBadge`): Аптечка = `course_done`, Прогресс = новые ачивки (`notifications.ts`), Настройки = pending-«Забота». Тесты `test_achievements.py`.

---

## Фаза 18 — Дизайн-полировка: раскатка design-v2 ✅ (2026-06-05)
**design-v2 — единственный стиль.** `design.ts:applyDesign()` всегда вешает `body.design-v2`; нет localStorage-флага/`getDesignPref`. Тоггл «Классический/Новый вид» из `SettingsPage` удалён (блок «Внешний вид» = только тема auto/light/dark). Классическая base-CSS оставлена под скоупом как fallback. `.page-header-title`: 20px/700, `--link`.
- **v2-CSS-блок** в конце `App.css` под `body.design-v2` (токены `--r-card/--r-btn/--sp-*/--dur/--ease/--elev/--hairline`). Типографика секций без капс, плавающие карточки (med/mlist/wish = bg+тень), кнопки (радиус+press-scale), seg-btn, glass на bottom-nav. `.settings-block` = `--secondary-bg`.
- **Карточки раздельны по вкладкам:** Приёмы = `.mlist-card` (60/10·14); Аптечка = `.mlist-card--col` (геометрию задаёт только `.mlist-card-main` = `11px 14px`). Приёмы — время в строке названия `.mlist-name--withtime` (`Парацетамол · 09:00`). meal `any` = «Не зависит от еды».
- **Поверхности:** карточки = `--v2-surface` (= `secondary-bg`; light темнее через `color-mix 92% #000`). `.mlist-list` = transparent/gap:0. Слайдер/`.skip-circle`/`.mlist-action-btn` → `--bg`. Обводки убраны у `.seg-btn`/`.field-input`/`.field-select` (TimePicker не трогаем).
- **Навигация:** плавающая `bottom-nav` (12px, safe-area+10, h56, radius20, тень, bg97%+blur), без обводки. Активная = едущая pill (`--button-bg`, белая иконка) через `--nav-i`. Подписи убраны, иконки 23px, центрированная панель `--nav-item-w:60px`.
- **WP1 Формы** ✅ — sticky «Сохранить», ритм секций, hairline.
- **WP2 Dashboard** ✅ — `.section-title--now` точка `--accent`+пульс, due-pill, `.slide-fill` градиент, `.btn-take-all` press-scale.
- **WP3 StatsPage** ✅ — единый `.stats-card`; токены `--ok/--warn/--bad`; график «по неделям» удалён.
- **Курс:** плоско, близко к Telegram, на `themeParams`; не редизайн в чужую эстетику (iOS-скевоморфизм/Ubuntu-Yaru отброшены). Glass только на плавающих слоях. Реализация = token-first + scope-класс `.design-v2` (v1 в `:root`, v2 переопределяет); v2-стили ТОЛЬКО под `.design-v2`.

## Фаза 15 v1 — Соцмеханика пожеланий ✅ (за тоглом)
- **Ядро:** `wish_presets.py` · `api/routers/wishes.py` (status/send/inbox/react) · `wishes_sent`. Отправка → random получатель excl self → inbox. Получатель видит `WishZone` на Dashboard (👍 Помогло / ❤️ Очень поддержало).
- **Обратная связь (2 слоя):** (1) in-app всегда — карточка «вашу поддержку оценили: 👍N ❤️M» (`/wishes/status` → `ack_helped/ack_supported`); (2) TG-дайджест за тоглом `wishes_tg_notify` (default OFF) — 1/день в `WISH_DIGEST_TIME=20:00` через `scheduler._send_wish_digests`. Мгновенного пуша на реакцию НЕТ.
- **Тематика по времени:** `presets_for_hour(hour)` в TZ юзера.
- **Антифрод:** `WISH_DAILY_LIMIT=20`, only-presets (422), rate-limit. Гейт пула `WISH_MIN_POOL=2`.
- Тогл «Слова поддержки (тест)»; очистка `wishes_sent` в `delete_user_data`.

## Аудит фронтенда 2026-06-05 — баги/мёртвый код ✅
✅ B1–B4 + D1–D3, D5 (коммит `e5309c5`). D4 (поллинг) оставлен осознанно — гейт по pending сломал бы появление бейджа нового запроса.
- **B1** Бейдж «Аптечка»: `m.course_total != null && (m.course_done ?? 0) >= m.course_total` (как `courseComplete` в `MedicationList.tsx`).
- **B2** «Принять всё» метило чужие секции — метить только own-due в `setQueryData`.
- **B3** `DOMMatrixReadOnly('none')` guard: `t === 'none' ? 0 : ...m41`.
- **B4** Док-дрейф: механика = `SlideToConfirm`, не HoldButton.
- **D1** 6 stock-хуков снесены (`useStock`/`useSetStock`/...). **D2** `useWeekStats`+`WeekStatRow` снесены. **D3/D5** подчищены.
