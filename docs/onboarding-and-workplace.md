# Staff onboarding and workplace policies

Two HR capabilities built on the same rules engine, permissions and audit trail as the rest of BOP Evolve:

- **Staff onboarding** brings the bank's 3,400+ staff, from C-level to officers, into the system in planned waves.
- **Workplace policies** measures attendance, check-in and check-out, breaks and dress code every day, and turns rule matches into fair, explainable exceptions.

All data in the demo is synthetic. The time clock is simulated; a real deployment feeds `attendance_days` from the bank's time-and-attendance system.

## Onboarding 3,400+ staff

The approach: one roster file, access derived from grade, invitations in waves, and a short welcome journey that is measured end to end.

### 1. Roster import (HR › Staff onboarding › Import roster)

HR exports the staff list as CSV. **Download the sample roster** button produces a realistic 3,400-person file with fictional people.

| Column | Required | Notes |
|---|---|---|
| `employee_number` | yes | HR number; becomes the username. Re-imports update by this number. |
| `full_name`, `full_name_ar` | name yes | Shown inside BOP Evolve only; never sent to the AI assistant. |
| `grade` | yes | `C` C-level, `D` director, `RM` regional manager, `BM` branch manager, `SM` section/unit head, `TL` team lead, `O` officer, `A` assistant. |
| `job_title` | yes | |
| `department_code` | yes | e.g. `DEP-RETAIL` |
| `region_code`, `branch_code`, `section_code` | as needed | Blank levels are skipped. Optional `*_name` / `*_name_ar` columns name units that do not exist yet. |
| `manager_employee_number` | no | Must exist in the file or the system. |
| `customer_facing` | no | yes/no (default yes). Customer-facing staff also acknowledge the service policies. |
| `work_start`, `work_end` | no | HH:MM (default 08:00-15:00). |
| `start_date` | no | YYYY-MM-DD. |
| `language` | no | `en` or `ar`. |

Validation runs first and writes nothing. It reports every row error, including:

- duplicate numbers
- unknown grades
- bad times or dates
- unknown managers
- a unit placed under a different parent
- a manager grade without the unit their access needs

The preview also shows the new org units and the access each grade will receive. **Import** then creates the accounts as **invited**: no password, unable to sign in until activated.

Measured on PostgreSQL in this environment with 3,400 rows:

| Step | Time |
|---|---|
| Validation | 0.2 s |
| Commit | 2.7 s |
| Launching a wave of 3,400 | 1.2 s |

### 2. Access from grade

| Grade | Role | Sees |
|---|---|---|
| C, D | Department Head / Chief Officer | own department |
| RM | Regional Manager | own region |
| BM | Branch Manager | own branch |
| SM | Section Manager | own section |
| TL | Team Lead | own section |
| O, A | Employee | own records |

Department overrides:

- **HR:** C/D grades get Chief HR Officer, everyone else gets HR / L&D.
- **Risk, Compliance, Audit:** Risk / Compliance.
- **IT:** Data / AI Ops.

Everyone also gets employee self-service on their own records. The mapping lives in `backend/app/services/onboarding.py` (`GRADES`, `DEPARTMENT_ROLES`) and is a proposal for HR and Compliance to confirm.

### 3. Waves and activation codes

A wave selects people by grade and/or org unit (subtree), for example:

1. "Leadership (C, D, RM)"
2. "Head office"
3. "North Region"

**Launch** issues a one-time code per person and downloads them once as CSV, for distribution through HR's usual secure channel. How the codes are protected:

- Only a SHA-256 hash of each code is stored.
- Codes expire after `onboarding.code_ttl_days` (default 14).
- Five wrong attempts block a code.
- Relaunching reissues codes and revokes the unused ones.

The person chooses **First time? Activate your account** on the sign-in screen and enters:

- their employee number
- the code
- a new password (at least 8 characters, letters and digits)

### 4. Welcome journey (Getting started)

Five steps, each timestamped:

1. Activate the account.
2. Choose a language.
3. Take the guided tour. Finishing the tour ticks this step automatically.
4. Acknowledge the policies that apply. Everyone acknowledges HR-01..03; customer-facing staff also acknowledge the service policies. Each acknowledgement is stored per policy version.
5. Pass a 3-question check (2 correct). The questions are written by the AI assistant from the policies in force, or come from a built-in set when the assistant is off. Answers are checked on the server, and the correct answers are never sent before submission.

An optional AI welcome tailors first-week tips to the person's role. It uses only the role and unit type, never the name.

### 5. Following progress

**Progress** shows:

- the funnel (roster → invited → activated → language → tour → policies → quiz → completed)
- stage by department and by grade
- daily activations

**People** lists everyone with their stage, with filters and search.

For a wave, HR can draft a reminder with the AI assistant (English and Arabic) and post it. People who have not finished see the reminder on their Getting started page.

## Workplace policies (attendance, breaks, dress code)

### Policies and rules

| Policy | Rule | Fires when | Severity |
|---|---|---|---|
| HR-01 Working hours & attendance | `HR_LATE_ARRIVAL` | minutes late > 10 | low |
| | `HR_EARLY_LEAVE` | left > 10 min before end of shift | low |
| | `HR_MISSING_PUNCH` | check-in or check-out missing | medium |
| | `HR_UNAPPROVED_ABSENCE` | absent without approved leave | high |
| HR-02 Breaks | `HR_BREAK_OVERRUN` | break time > allowance + 10 min | low |
| HR-03 Dress code | `HR_DRESS_CODE` | supervisor recorded the standard as not met | low |

These are ordinary rules in **Policies & Control Rules**, under the categories *Attendance & working time* and *Dress code & appearance*. Policy owners change thresholds or add rules the usual way:

- draft → backtest on history → four-eyes approval

Rules can use these facts:

| Area | Facts |
|---|---|
| Time | minutes late, early-leave minutes, missing check-in/out, unapproved absence |
| Breaks | break minutes, break overrun, number of breaks |
| Context | weekday, customer-facing role |
| Dress code | area observed, compliant, earlier dress-code issues |

### Exception workflow

```
open --(employee explains: reason + optional text)--> explained
open/explained --(supervisor decides)--> excused | confirmed (+ reminder / coaching / schedule review / formal note) | dismissed
```

- Supervisors cannot decide their own exceptions.
- Bulk decisions (up to 200) handle cases like a time-clock fault that hit a whole branch.
- Reasons are structured (transport/checkpoint, family, medical, time-clock fault, approved by manager, serving a customer, other), so HR can see systemic causes.
- Free text written by staff never leaves BOP Evolve.

### KPIs

All KPIs are SQL aggregates, so the overview for 3,400+ people answers in about half a second.

| KPI | Definition |
|---|---|
| On-time check-in | check-ins within the grace period (`workplace.grace_minutes`, default 10) ÷ days with a check-in |
| Average lateness | minutes late on the late days only |
| Breaks within allowance | worked days without break overrun ÷ worked days (`workplace.break_allowance_minutes`, default 60) |
| Lost hours per employee / month | (late + early leave + break overrun minutes) ÷ worked days × 22 ÷ 60 |
| Attendance | worked days ÷ (scheduled − approved leave) |
| Complete check-in/out | worked days with both punches ÷ worked days |
| Dress code met | compliant observations ÷ observations |
| Policy adherence index | 0–100 weighted blend: punctuality 35 %, attendance 20 %, breaks 20 %, punches 10 %, dress code 15 % |

The **Workplace policies** page has three views:

- **Managers and HR:**
  - KPIs with drill-down from bank → department → region → branch → section
  - weekly trend of lost minutes and late arrivals by weekday
  - exceptions by rule and the reasons staff gave
  - a "who may need a conversation" list
  - the decisions queue
  - the dress-code observation form (line managers)
- **Employees** (**My attendance**):
  - their own KPIs and last 30 days
  - their dress-code checks
  - their exceptions, with an **Explain** button
- **Chief HR Officer's printable Employee Development Report:** a workplace section is included.

### Permissions

| Permission | Roles |
|---|---|
| `workplace.view` | managers and team leads (their units), Department Head / Regional Manager, HR (bank-wide), employees (self) |
| `workplace.review` | branch/section managers, team leads, HR |
| `workplace.observe` | branch/section managers, team leads |
| `workplace.respond` | employees (own exceptions) |
| `onboarding.manage` | System Administrator, Chief HR Officer, HR / L&D |

### Simulated time clock

The worker feeds the simulated time clock:

- **Every tick:** it writes yesterday's day for everyone.
- **Newly imported staff:** up to 30 days of history, 4,000 days per tick. 3,400 people are filled in about 30 s, never blocking a tick.
- **Tendencies:** each person has stable, deterministic habits (keyed by pseudonym), most of them punctual. Some improve over time, so trends are visible.

Upgrading an existing database adds HR-01..03, the six rules and about 120 days of history for the demo staff.
