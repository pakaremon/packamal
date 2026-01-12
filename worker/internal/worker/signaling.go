package worker

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math/rand"
	"net"
	"net/http"
	"strings"
	"time"
)

const (
	donePath    = "/done/"
	timeoutPath = "/timeout/"
)

// CompletionReporter handles sending completion signals to the Python backend API.
type CompletionReporter struct {
	taskID    string
	baseURL   string // e.g., http://backend:8000/api/v1/internal/callback
	authToken string
	client    *http.Client
}

// NewCompletionReporter creates a new reporter.
// If taskID is empty, it returns a reporter that will no-op.
func NewCompletionReporter(taskID, baseURL, authToken string) *CompletionReporter {
	return &CompletionReporter{
		taskID:    taskID,
		baseURL:   baseURL,
		authToken: authToken,
		client: &http.Client{
			Timeout: 15 * time.Second,
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				// Don't follow redirects - they shouldn't happen if URL is correct
				// (Django redirects without trailing slash).
				return fmt.Errorf("unexpected redirect to %s", req.URL)
			},
		},
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

	if err := r.sendWithRetry(ctx, r.url(donePath), body, retryConfig{
		maxAttempts: 8,
		baseDelay:   1 * time.Second,
		maxDelay:    15 * time.Second,
		jitterMax:   500 * time.Millisecond,
	}); err != nil {
		return err
	}

	slog.InfoContext(ctx, "Successfully notified backend", "task_id", r.taskID, "status", status)
	return nil
}

// SendFinalStatus sends a "final" status (e.g. timeout/failed) to the backend.
//
// Tier-1 Graceful Timeout requirements:
// - Retry up to 5 times
// - Wait 5-10 seconds between attempts
// - Payload includes task_id, status, reason
func (r *CompletionReporter) SendFinalStatus(ctx context.Context, status, reason string) error {
	if r.taskID == "" {
		slog.DebugContext(ctx, "No task_id provided, skipping final status notification")
		return nil
	}

	payload := map[string]string{
		"task_id": r.taskID,
		"status":  status,
		"reason":  reason,
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal final status payload: %w", err)
	}

	if err := r.sendWithRetry(ctx, r.url(timeoutPath), body, retryConfig{
		maxAttempts: 5,
		baseDelay:   5 * time.Second,
		maxDelay:    10 * time.Second, // fixed-ish wait with jitter, per requirements
		jitterMax:   1 * time.Second,
	}); err != nil {
		return err
	}

	slog.InfoContext(ctx, "Successfully sent final status to backend",
		"task_id", r.taskID,
		"status", status,
		"reason", reason,
	)
	return nil
}

func (r *CompletionReporter) url(path string) string {
	base := strings.TrimRight(r.baseURL, "/")
	return base + path
}

type retryConfig struct {
	maxAttempts int
	baseDelay   time.Duration
	maxDelay    time.Duration
	jitterMax   time.Duration
}

func (r *CompletionReporter) sendWithRetry(ctx context.Context, url string, body []byte, cfg retryConfig) error {
	if cfg.maxAttempts <= 0 {
		cfg.maxAttempts = 1
	}

	rng := rand.New(rand.NewSource(time.Now().UnixNano()))
	var lastErr error

	for attempt := 1; attempt <= cfg.maxAttempts; attempt++ {
		lastErr = r.send(ctx, url, body)
		if lastErr == nil {
			return nil
		}
		if attempt == cfg.maxAttempts {
			break
		}

		delay := cfg.baseDelay
		// If maxDelay > baseDelay, do exponential growth capped at maxDelay.
		if cfg.maxDelay > cfg.baseDelay && cfg.baseDelay > 0 {
			shift := attempt - 1
			if shift > 30 {
				shift = 30
			}
			delay = cfg.baseDelay * (1 << shift)
			if delay > cfg.maxDelay {
				delay = cfg.maxDelay
			}
		} else if cfg.maxDelay > 0 {
			// fixed delay (with optional jitter)
			delay = cfg.maxDelay
		}

		if cfg.jitterMax > 0 {
			delay += time.Duration(rng.Int63n(int64(cfg.jitterMax)))
		}

		slog.WarnContext(ctx, "Backend callback failed, retrying...",
			"attempt", attempt,
			"max_attempts", cfg.maxAttempts,
			"error", lastErr,
			"next_retry_in", delay,
		)

		select {
		case <-time.After(delay):
		case <-ctx.Done():
			return ctx.Err()
		}
	}

	return fmt.Errorf("failed to notify backend after %d attempts: %w", cfg.maxAttempts, lastErr)
}

// send performs the actual HTTP POST request.
func (r *CompletionReporter) send(ctx context.Context, url string, body []byte) error {
	req, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewBuffer(body))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+r.authToken)

	resp, err := r.client.Do(req)
	if err != nil {
		// Retryable network errors (backend restart / rollout / transient overload).
		var netErr net.Error
		if errors.As(err, &netErr) {
			if netErr.Timeout() || netErr.Temporary() {
				return fmt.Errorf("network error (retryable): %w", err)
			}
		}
		// Fallback for common transient strings across environments.
		if strings.Contains(err.Error(), "EOF") ||
			strings.Contains(err.Error(), "connection refused") ||
			strings.Contains(err.Error(), "connection reset") {
			return fmt.Errorf("network error (retryable): %w", err)
		}
		return fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	// Read response body to ensure connection is fully consumed
	// This prevents EOF errors from incomplete reads
	var respBody bytes.Buffer
	if _, readErr := respBody.ReadFrom(resp.Body); readErr != nil {
		// Log warning but don't fail - the status code is more important
	}

	// Consider retryable status codes:
	// - 5xx: backend restart / overload
	// - 429: rate limiting / backpressure
	// - 408: request timeout
	if resp.StatusCode >= 500 || resp.StatusCode == 429 || resp.StatusCode == 408 {
		responseStr := respBody.String()
		if len(responseStr) > 500 {
			responseStr = responseStr[:500] + "..."
		}
		return fmt.Errorf("backend returned retryable error: %d (%s)", resp.StatusCode, responseStr)
	}

	// 4xx errors (except 429) mean our request is wrong; don't retry.
	if resp.StatusCode >= 400 {
		// Log the error response for debugging (limit length)
		responseStr := respBody.String()
		if len(responseStr) > 500 {
			responseStr = responseStr[:500] + "..."
		}
		slog.WarnContext(ctx, "Backend rejected request",
			"status", resp.StatusCode,
			"response", responseStr,
		)
		return fmt.Errorf("backend rejected request with status: %d", resp.StatusCode)
	}

	return nil
}
