# Phase 05 - Ops UI

## Scope

Dashboard van hanh de tao, theo doi va retry pipeline jobs.

## Current State

- Dashboard page hien la man hinh chinh
- Co danh sach jobs, summary cards, create job form
- Co SSE tu `/jobs/events` de cap nhat realtime
- Co retry action cho job

## Key Files

- `frontend/src/pages/dashboard/DashboardPage.tsx`
- `frontend/src/features/jobs/api/jobs.ts`
- `frontend/src/features/jobs/components/JobsTable.tsx`
- `frontend/src/features/jobs/components/JobSummaryCards.tsx`
- `frontend/src/features/jobs/components/CreateJobForm.tsx`

## Open Notes

- UI hien tai phuc vu van hanh noi bo
- Neu mo rong sang filter, pagination, detail drawer, cap nhat phase nay
