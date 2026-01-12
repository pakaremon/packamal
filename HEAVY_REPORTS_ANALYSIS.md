# Analysis: Heavy Reports Causing Admin Page Crashes

## Problem Summary

The Django admin page crashes with **502 Bad Gateway** errors when loading AnalysisTask records. Root cause: **massive JSONField data in ReportDynamicAnalysis reports** (up to 41 MB per task).

## Root Cause: System Calls Array

Dynamic analysis captures **every system call** made during package execution, storing them in a `report.report` JSONField structure:

```json
{
  "report": {
    "domains": [...],
    "commands": [...],
    "system_calls": [
      {
        "rules": [],
        "system_call": "arch_prctl(0x3001, 0x7f48d241cbf0)"
      },
      // ... 179,000+ more entries for Task 193
    ]
  },
  "packages": {...}
}
```

## Data Size Analysis

### Task 193 (Example)
- **Total report size**: 37,550,554 bytes (≈35.8 MB)
- **System calls count**: 179,409 items
- **System calls size**: 37,549,838 bytes (≈35.8 MB)
- **Commands**: 8 items
- **Domains**: 1 item

### Other Large Tasks Found
- Task 145: **41.1 MB** (largest found)
- Task 143: **38.1 MB**
- Task 193: **35.8 MB**
- Task 147: **32.2 MB**
- Task 28: **17.8 MB**
- Task 3: **14.6 MB**
- Task 94: **17.1 MB**
- Task 142: **11.4 MB**
- Task 27: **11.9 MB**
- Task 2: **11.3 MB**

**9 tasks > 10MB**, many others at 7-9 MB.

## Why This Causes 502 Errors

1. **Eager loading**: Django's `select_related('report')` eagerly loads the entire 37MB+ JSONField for every task
2. **Memory explosion**: Loading multiple tasks with large reports consumes GB of memory
3. **Pod memory limits**: Backend pods have 2Gi limit, but are using 1Gi+ already
4. **Gunicorn worker death**: Workers get OOM killed or timeout when loading huge JSONFields
5. **Connection closure**: Backend closes connection prematurely → 502 Bad Gateway

### Memory Usage Pattern
```
Normal list view (50 tasks):
- Each task with report: 10-40 MB × 50 = 500 MB - 2 GB!
- Current pod usage: ~1 GB baseline
- Total: 1.5 - 3 GB → EXCEEDS 2Gi limit → CRASH
```

## Fixes Applied

### 1. Admin Queryset Optimization (`admin.py`)
- ✅ **Always defer `error_details`**: Loads on-demand only
- ✅ **Removed eager loading of report**: No `select_related('report')`
- ✅ **Report loads lazily**: Only when accessed, per individual task
- ✅ **Removed report field from form**: Prevents accidental loading in change view
- ✅ **Added `has_report` indicator**: Shows report existence without loading data

### 2. Code Changes
```python
def get_queryset(self, request):
    qs = super().get_queryset(request)
    qs = qs.select_related('api_key')  # Only lightweight fields
    qs = qs.defer('error_details')     # Defer large JSONField
    # Intentionally NO select_related('report') to avoid loading huge JSONField
    return qs
```

## Recommendations

### Immediate (Already Done)
- ✅ Optimized admin queryset
- ✅ Deferred large fields
- ✅ Removed eager loading

### Short-term (Quick Fix)
1. **Increase backend memory limits**:
   ```yaml
   resources:
     limits:
       memory: "3Gi"  # Up from 2Gi
     requests:
       memory: "768Mi"  # Up from 512Mi
   ```

2. **Monitor and alert on large reports**:
   - Alert when report > 10MB
   - Consider archiving or truncating old reports

### Medium-term (Architectural)
1. **Store reports in external storage** (S3, Azure Blob):
   - Keep only report metadata in database
   - Store full JSON in object storage
   - Reference via URL in `download_url`

2. **Truncate/limit system_calls during analysis**:
   - Cap system_calls at reasonable limit (e.g., 10,000)
   - Or sample system calls (every Nth call)
   - Store summary statistics instead of full list

3. **Implement pagination/chunking**:
   - Load system_calls in chunks via API
   - Admin view shows summary, full report via separate endpoint

4. **Database optimization**:
   - Move `report.report` to separate table with TOAST storage (PostgreSQL)
   - Use JSONB column compression
   - Archive old reports to separate archive database

### Long-term (Best Practices)
1. **Separate analysis data from metadata**:
   - Keep AnalysisTask lightweight (status, timestamps, etc.)
   - Store analysis results separately (FileStorage, ObjectStorage)
   - Reference via foreign key

2. **Streaming/Progressive loading**:
   - Load report data progressively
   - Use WebSockets or Server-Sent Events for large data

3. **Caching strategy**:
   - Cache frequently accessed reports in Redis
   - Implement report size-based caching (small reports cached, large ones streamed)

## Current State

After optimizations:
- Admin list view should work without crashing
- Memory usage reduced significantly (no eager loading of 37MB reports)
- Individual task views still functional (lazy loading when needed)
- Backend should be more stable

## Next Steps

1. **Deploy optimized admin.py** (done)
2. **Monitor memory usage** after deployment
3. **Consider increasing memory limits** if still having issues
4. **Plan migration to external storage** for large reports

## Technical Details

### Report Structure
- **Location**: `ReportDynamicAnalysis.report` (JSONField)
- **Content**: Dynamic analysis output from Go worker
- **Size range**: 7 MB - 41 MB per report
- **Primary component**: `system_calls` array (thousands to 179K+ entries)

### Why System Calls Are So Large
- Each system call is a JSON object: `{"rules": [], "system_call": "..."}`
- Packages like `commitlint` trigger 179,409 system calls during installation
- Each entry: ~200 bytes
- Total: 179,409 × 200 bytes ≈ 35.8 MB

### Error Details (Less Problematic)
- `error_details` is usually small (0-1MB)
- Already deferred in admin to be safe
- Not the primary cause of crashes

