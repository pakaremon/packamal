package worker

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"time"
)

// CompletionReporter handles sending completion signals to the Python backend API.
type CompletionReporter struct {
	taskID    string
	apiURL    string // e.g., http://backend-service.packamal.svc.cluster.local:8000/api/internal/callback/
	authToken string
}

// NewCompletionReporter creates a new reporter. 
// If taskID is empty, it returns a reporter that will no-op.
func NewCompletionReporter(taskID, apiURL, authToken string) *CompletionReporter {
	return &CompletionReporter{
		taskID:    taskID,
		apiURL:    apiURL,
		authToken: authToken,
	}
}

// ReportDone sends a POST request to the backend. It retries with exponential backoff 
// if the backend is down or busy (5xx errors or connection timeouts).
func (r *CompletionReporter) ReportDone(ctx context.Context, status string) error {
	if r.taskID == "" {
		slog.DebugContext(ctx, "No task_id provided, skipping backend notification")
		return nil
	}

	payload := map[string]string{
		"task_id": r.taskID,
		"status":  status,
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal payload: %w", err)
	}

	// Retry configuration
	maxRetries := 10
	initialWait := 2 * time.Second

	for i := 0; i < maxRetries; i++ {
		err := r.send(ctx, body)
		if err == nil {
			slog.InfoContext(ctx, "Successfully notified backend", "task_id", r.taskID, "status", status)
			return nil
		}

		// Calculate wait time for next retry (2s, 4s, 8s, 16s...)
		wait := initialWait * (1 << i) 
		
		slog.WarnContext(ctx, "Backend notification failed, retrying...",
			"attempt", i+1,
			"error", err,
			"next_retry_in", wait,
		)

		select {
		case <-time.After(wait):
			continue
		case <-ctx.Done():
			return ctx.Err()
		}
	}

	return fmt.Errorf("failed to notify backend after %d attempts", maxRetries)
}

// send performs the actual HTTP POST request.
func (r *CompletionReporter) send(ctx context.Context, body []byte) error {
	req, err := http.NewRequestWithContext(ctx, "POST", r.apiURL, bytes.NewBuffer(body))
	if err != nil {
		return err
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+r.authToken)

	// Short timeout per attempt to avoid hanging the worker
	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	// Consider 5xx errors and 429 (Too Many Requests) as retryable
	if resp.StatusCode >= 500 || resp.StatusCode == 429 {
		return fmt.Errorf("backend returned retryable error: %d", resp.StatusCode)
	}

	// 4xx errors (except 429) mean our request is wrong; don't retry.
	if resp.StatusCode >= 400 {
		return fmt.Errorf("backend rejected request with status: %d", resp.StatusCode)
	}

	return nil
}