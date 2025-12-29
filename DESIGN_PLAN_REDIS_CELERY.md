# Design Plan: Redis/Celery Signaling Integration for Go Analyze Command

## Overview

This document outlines the design plan for integrating Redis message broker signaling into the `analyze` command using the [gocelery](https://github.com/gocelery/gocelery) library. The goal is to notify the Celery orchestrator when analysis completes, enabling the Django backend to update task status and process results.

## Architecture Context

Based on the provided architecture:

1. **Django Backend**: Creates a `Task` record in PostgreSQL and dispatches a Celery task
2. **Celery Orchestrator**: Launches ephemeral Go K8s Jobs via Kubernetes API
3. **Go Worker** (this binary): Runs analysis for 10m-2h, then must:
   - Update PostgreSQL Task record (status, result_json)
   - Publish `task_id` to Redis channel `task_updates`
   - Exit with `os.Exit(0)`

## Current State Analysis

### Current Flow in `cmd/analyze/main.go`

1. **Entry Point**: `main()` → `run()`
2. **Analysis Execution**:
   - `staticAnalysis()` - runs static analysis, saves results
   - `dynamicAnalysis()` - runs dynamic analysis, saves results
3. **Completion**: Returns `nil` on success, exits with error code on failure
4. **Missing**: No task_id tracking, no Redis connection, no completion signaling

### Key Observations

- Analysis modes are configurable via `-mode` flag (static, dynamic, or both)
- Results are saved to various buckets via `ResultStores`
- No current mechanism to receive or track `task_id`
- No database or Redis connectivity exists

## Design Requirements

### 1. Task ID Input

**Option A: Environment Variable (Recommended)**
- Read `TASK_ID` from environment (set by K8s Job)
- Pros: Standard K8s pattern, no flag pollution
- Cons: Requires environment variable setup

**Option B: Command Line Flag**
- Add `-task-id` flag
- Pros: Explicit, testable
- Cons: Requires K8s Job spec modification

**Decision**: Use **Option A** (environment variable) with **Option B** as fallback for local testing.

### 2. Redis Connection

**Configuration**:
- Redis URL from environment: `REDIS_URL` (default: `redis://localhost:6379/0`)
- Channel name: `task_updates` (hardcoded or configurable via env)
- Use gocelery's Redis broker/backend for compatibility

**Connection Pattern**:
```go
// Initialize Redis connection pool
redisPool := &redis.Pool{
    Dial: func() (redis.Conn, error) {
        c, err := redis.DialURL(redisURL)
        return c, err
    },
}
```

### 3. Completion Signaling

**When to Signal**:
- After **all requested analysis modes complete successfully**
- After **all result uploads complete** (or fail gracefully)
- Before program exit

**Signal Format**:
- Publish `task_id` as message to Redis channel `task_updates`
- Optionally include status: `completed`, `failed`, `partial` (if some modes failed)

**Error Handling**:
- If Redis publish fails: log error but don't fail the analysis
- Analysis success should not depend on signaling success

### 4. PostgreSQL Update (Optional Phase 1)

**Note**: This is mentioned in architecture but may be handled by Celery orchestrator. For now, focus on Redis signaling only.

**If implemented**:
- Connection string from environment: `DATABASE_URL` or `POSTGRES_*` vars
- Update `AnalysisTask` record:
  - `status` → `'completed'` or `'failed'`
  - `result_json` → JSON summary of analysis results
  - `completed_at` → current timestamp

## Implementation Plan

### Phase 1: Redis Signaling (Core Requirement)

#### Step 1: Add Dependencies

**File**: `go.mod`

Add gocelery and redis dependencies:
```go
require (
    github.com/gocelery/gocelery v0.0.0-... // latest version
    github.com/gomodule/redigo v2.0.0+incompatible // gocelery dependency
)
```

#### Step 2: Add Configuration Flags/Variables

**File**: `cmd/analyze/main.go`

Add new variables:
```go
var (
    // ... existing flags ...
    taskID = flag.String("task-id", "", "task ID for completion signaling (or use TASK_ID env)")
    redisURL = flag.String("redis-url", "", "Redis URL for signaling (or use REDIS_URL env)")
    redisChannel = flag.String("redis-channel", "task_updates", "Redis channel for task updates")
)
```

#### Step 3: Create Redis Signaling Module

**New File**: `internal/worker/signaling.go` (or add to existing worker package)

```go
package worker

import (
    "context"
    "log/slog"
    "os"
    
    "github.com/gocelery/gocelery"
    "github.com/gomodule/redigo/redis"
)

type CompletionSignaler struct {
    taskID      string
    redisURL    string
    channel     string
    redisPool   *redis.Pool
}

func NewCompletionSignaler(taskID, redisURL, channel string) (*CompletionSignaler, error) {
    // Create Redis connection pool
    pool := &redis.Pool{
        Dial: func() (redis.Conn, error) {
            c, err := redis.DialURL(redisURL)
            if err != nil {
                return nil, err
            }
            return c, err
        },
    }
    
    return &CompletionSignaler{
        taskID:    taskID,
        redisURL:  redisURL,
        channel:   channel,
        redisPool: pool,
    }, nil
}

func (s *CompletionSignaler) SignalCompletion(ctx context.Context, status string) error {
    if s.taskID == "" {
        slog.WarnContext(ctx, "No task_id provided, skipping Redis signal")
        return nil
    }
    
    conn := s.redisPool.Get()
    defer conn.Close()
    
    // Publish task_id to Redis channel
    _, err := conn.Do("PUBLISH", s.channel, s.taskID)
    if err != nil {
        slog.ErrorContext(ctx, "Failed to publish completion signal", 
            "error", err, "task_id", s.taskID, "channel", s.channel)
        return err
    }
    
    slog.InfoContext(ctx, "Published completion signal", 
        "task_id", s.taskID, "status", status, "channel", s.channel)
    return nil
}

func (s *CompletionSignaler) Close() error {
    return s.redisPool.Close()
}
```

#### Step 4: Integrate into `main.go`

**Modifications to `cmd/analyze/main.go`**:

1. **Initialize signaler in `run()`**:
```go
func run() error {
    // ... existing code ...
    
    // Get task_id from env or flag
    taskID := *taskID
    if taskID == "" {
        taskID = os.Getenv("TASK_ID")
    }
    
    // Get Redis URL from env or flag
    redisURL := *redisURL
    if redisURL == "" {
        redisURL = os.Getenv("REDIS_URL")
        if redisURL == "" {
            redisURL = "redis://localhost:6379/0" // default
        }
    }
    
    // Initialize completion signaler (non-blocking, can be nil if no task_id)
    var signaler *worker.CompletionSignaler
    if taskID != "" {
        var err error
        signaler, err = worker.NewCompletionSignaler(taskID, redisURL, *redisChannel)
        if err != nil {
            slog.WarnContext(ctx, "Failed to initialize Redis signaler", "error", err)
            // Continue without signaling rather than failing
        }
    }
    defer func() {
        if signaler != nil {
            signaler.Close()
        }
    }()
    
    // ... existing analysis code ...
    
    // Track completion status
    analysisStatus := "completed"
    var analysisError error
    
    if runMode[analysis.Static] {
        slog.InfoContext(ctx, "Starting static analysis")
        staticAnalysis(ctx, pkg, &resultStores)
        // Note: staticAnalysis doesn't return error, check logs for failures
    }
    
    if runMode[analysis.Dynamic] {
        slog.InfoContext(ctx, "Starting dynamic analysis")
        dynamicAnalysis(ctx, pkg, &resultStores)
        // Note: dynamicAnalysis doesn't return error, check logs for failures
    }
    
    // Signal completion
    if signaler != nil {
        if err := signaler.SignalCompletion(ctx, analysisStatus); err != nil {
            slog.ErrorContext(ctx, "Failed to signal completion", "error", err)
            // Don't fail the entire run if signaling fails
        }
    }
    
    return analysisError
}
```

2. **Update function signatures** (optional, for better error tracking):
   - Consider making `staticAnalysis()` and `dynamicAnalysis()` return errors
   - Track partial failures (e.g., static succeeded but dynamic failed)

### Phase 2: Enhanced Error Handling (Future)

- Track which analysis modes succeeded/failed
- Signal `partial` status if some modes failed
- Include error details in Redis message (JSON payload)

### Phase 3: PostgreSQL Update (Future)

- Add PostgreSQL connection using `pgx` or `database/sql`
- Update `AnalysisTask` record before signaling
- Handle database connection failures gracefully

## Testing Strategy

### Unit Tests

1. **Signaling Module**:
   - Test Redis connection initialization
   - Test message publishing
   - Test error handling (Redis unavailable)

### Integration Tests

1. **End-to-End**:
   - Run `analyze` with `TASK_ID` set
   - Verify message appears in Redis channel
   - Verify Celery orchestrator receives signal

### Local Testing

```bash
# Start Redis locally
docker run -d -p 6379:6379 redis:7-alpine

# Run analyze with task_id
TASK_ID=test-123 REDIS_URL=redis://localhost:6379/0 \
  ./analyze -ecosystem pypi -package requests

# Monitor Redis channel
redis-cli SUBSCRIBE task_updates
```

## Environment Variables

### Required (when running in K8s)

- `TASK_ID`: Task identifier from Django/Celery
- `REDIS_URL`: Redis connection URL (default: `redis://localhost:6379/0`)

### Optional

- `REDIS_CHANNEL`: Channel name for updates (default: `task_updates`)

## Kubernetes Job Configuration

Update K8s Job spec to pass `TASK_ID`:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: analysis-job-{{ task_id }}
spec:
  template:
    spec:
      containers:
      - name: analyze
        image: packamal-worker:latest
        env:
        - name: TASK_ID
          value: "{{ task_id }}"  # From Celery orchestrator
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: packamal-secrets
              key: redis-url
        command: ["/analyze"]
        args:
        - "-ecosystem"
        - "pypi"
        - "-package"
        - "requests"
```

## Error Scenarios & Handling

| Scenario | Behavior |
|----------|----------|
| `TASK_ID` not set | Skip signaling, log warning, continue analysis |
| Redis unavailable | Log error, continue analysis (don't fail) |
| Redis publish fails | Log error, continue (analysis succeeded) |
| Analysis fails | Signal with `failed` status (if signaler initialized) |
| Partial failure | Signal with `partial` status (future enhancement) |

## Migration Path

1. **Phase 1**: Add Redis signaling (non-breaking, optional)
2. **Phase 2**: Make signaling required (fail if `TASK_ID` set but Redis unavailable)
3. **Phase 3**: Add PostgreSQL updates
4. **Phase 4**: Enhanced status reporting (partial failures, error details)

## Dependencies

### New Dependencies

- `github.com/gocelery/gocelery` - Celery client library
- `github.com/gomodule/redigo/redis` - Redis client (gocelery dependency)

### Compatibility

- Works with existing Celery setup (Redis broker)
- Compatible with Celery message protocol version 1 (as per gocelery docs)
- No changes required to Django/Celery orchestrator (listens to Redis channel)

## Summary

This design adds Redis signaling to the `analyze` command with minimal changes:

1. **Single file modification**: `cmd/analyze/main.go`
2. **New module**: `internal/worker/signaling.go` (or similar)
3. **Non-breaking**: Works without `TASK_ID` (backward compatible)
4. **Resilient**: Analysis success doesn't depend on signaling success
5. **Standard patterns**: Uses environment variables, Redis pub/sub

The implementation follows Go best practices and integrates seamlessly with the existing Celery/Django architecture.

