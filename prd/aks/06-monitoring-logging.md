# Monitoring, Logging, and Observability

## Overview

This document describes the monitoring and logging setup for Packamal on AKS using Azure Monitor, Application Insights, and other observability tools.

## Azure Monitor for Containers

### Enable Container Insights

Container Insights is automatically enabled when creating AKS with `--enable-addons monitoring`. To enable on existing cluster:

```bash
az aks enable-addons \
  --resource-group $RESOURCE_GROUP \
  --name $CLUSTER_NAME \
  --addons monitoring \
  --workspace-resource-id /subscriptions/{subscription-id}/resourceGroups/{resource-group}/providers/Microsoft.OperationalInsights/workspaces/{workspace-name}
```

### View Metrics

- **Azure Portal**: Navigate to AKS cluster → Insights
- **Metrics Explorer**: CPU, memory, network, disk usage
- **Live Metrics**: Real-time pod metrics
- **Performance**: Node and pod performance data

## Application Insights

### Install Application Insights

```bash
# Create Application Insights resource
az monitor app-insights component create \
  --app packamal-insights \
  --location $LOCATION \
  --resource-group $RESOURCE_GROUP

# Get instrumentation key
INSTRUMENTATION_KEY=$(az monitor app-insights component show \
  --app packamal-insights \
  --resource-group $RESOURCE_GROUP \
  --query instrumentationKey -o tsv)
```

### Configure Django Backend

Add to `backend/requirements.txt`:
```
opencensus-ext-azure
opencensus-ext-django
```

Update Django settings:
```python
# settings.py
INSTALLED_APPS = [
    # ...
    'opencensus.ext.django',
]

OPENCENSUS = {
    'TRACE': {
        'SAMPLER': 'opencensus.trace.samplers.ProbabilitySampler(rate=1.0)',
        'EXPORTER': 'opencensus.ext.azure.trace_exporter.AzureExporter',
        'EXPORTER': {
            'INSTRUMENTATION_KEY': os.environ.get('APPINSIGHTS_INSTRUMENTATION_KEY'),
        },
    },
}
```

### Add to ConfigMap

```yaml
# In 01-config.yaml
data:
  APPINSIGHTS_INSTRUMENTATION_KEY: "<your-key>"
```

## Logging Configuration

### Centralized Logging with Log Analytics

Logs are automatically collected by Azure Monitor. Configure log collection:

```bash
# Enable diagnostic settings
az monitor diagnostic-settings create \
  --name aks-diagnostics \
  --resource /subscriptions/{subscription-id}/resourceGroups/{resource-group}/providers/Microsoft.ContainerService/managedClusters/{cluster-name} \
  --workspace <log-analytics-workspace-id> \
  --logs '[{"category":"kube-audit","enabled":true},{"category":"kube-apiserver","enabled":true},{"category":"kube-controller-manager","enabled":true},{"category":"kube-scheduler","enabled":true},{"category":"cluster-autoscaler","enabled":true}]'
```

### Structured Logging

Configure applications to output structured JSON logs:

```python
# Django logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(asctime)s %(name)s %(levelname)s %(message)s'
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
```

### Log Queries (KQL)

Example queries for Log Analytics:

```kql
// Pod logs
ContainerLog
| where Namespace == "packamal"
| where Name contains "backend"
| order by TimeGenerated desc
| take 100

// Error logs
ContainerLog
| where Namespace == "packamal"
| where LogEntry contains "ERROR"
| summarize count() by bin(TimeGenerated, 5m)

// Pod restarts
KubePodInventory
| where Namespace == "packamal"
| where ContainerRestartCount > 0
| project TimeGenerated, Name, ContainerRestartCount
| order by TimeGenerated desc
```

## Prometheus and Grafana (Optional)

### Install Prometheus Operator

```bash
# Add Helm repo
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Install kube-prometheus-stack
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set prometheus.prometheusSpec.retention=30d
```

### Configure Service Monitors

```yaml
# service-monitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: backend-metrics
  namespace: packamal
spec:
  selector:
    matchLabels:
      app: backend
  endpoints:
  - port: http
    path: /metrics
    interval: 30s
```

## Custom Metrics

### Expose Django Metrics

Install `django-prometheus`:

```python
# settings.py
INSTALLED_APPS = [
    'django_prometheus',
    # ...
]

MIDDLEWARE = [
    'django_prometheus.middleware.PrometheusBeforeMiddleware',
    # ...
    'django_prometheus.middleware.PrometheusAfterMiddleware',
]

# urls.py
urlpatterns = [
    path('metrics', prometheus_views.ExportToDjangoView, name='prometheus-django-metrics'),
]
```

### Custom Metrics in Go Worker

```go
import (
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
    analysisDuration = prometheus.NewHistogramVec(
        prometheus.HistogramOpts{
            Name: "analysis_duration_seconds",
            Help: "Analysis job duration",
        },
        []string{"ecosystem", "status"},
    )
)

func init() {
    prometheus.MustRegister(analysisDuration)
}
```

## Alerting

### Azure Monitor Alerts

```bash
# Create alert rule for pod restarts
az monitor metrics alert create \
  --name "High Pod Restarts" \
  --resource-group $RESOURCE_GROUP \
  --scopes /subscriptions/{subscription-id}/resourceGroups/{resource-group}/providers/Microsoft.ContainerService/managedClusters/{cluster-name} \
  --condition "avg ContainerRestartCount > 5" \
  --window-size 5m \
  --evaluation-frequency 1m \
  --action-group <action-group-id>
```

### Alert Rules (YAML)

```yaml
# alerts.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: packamal-alerts
  namespace: packamal
spec:
  groups:
  - name: packamal
    rules:
    - alert: HighErrorRate
      expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "High error rate detected"
    
    - alert: PodCrashLooping
      expr: rate(kube_pod_container_status_restarts_total[15m]) > 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Pod is crash looping"
    
    - alert: HighMemoryUsage
      expr: (container_memory_usage_bytes / container_spec_memory_limit_bytes) > 0.9
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "High memory usage"
```

## Distributed Tracing

### OpenTelemetry (Recommended)

```python
# Install OpenTelemetry
pip install opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-django opentelemetry-exporter-azure-monitor

# Configure
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.azure_monitor import AzureMonitorTraceExporter

trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer(__name__)

azure_exporter = AzureMonitorTraceExporter(
    connection_string=os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
)
span_processor = BatchSpanProcessor(azure_exporter)
trace.get_tracer_provider().add_span_processor(span_processor)
```

## Health Checks and Dashboards

### Health Check Endpoint

```python
# Django health check
def health_check(request):
    checks = {
        'database': check_database(),
        'redis': check_redis(),
        'storage': check_storage(),
    }
    status = 200 if all(checks.values()) else 503
    return JsonResponse(checks, status=status)
```

### Azure Dashboard

Create custom dashboard in Azure Portal:

```json
{
  "lenses": [
    {
      "order": 0,
      "parts": [
        {
          "position": {
            "x": 0,
            "y": 0,
            "colSpan": 6,
            "rowSpan": 4
          },
          "metadata": {
            "inputs": [],
            "type": "Extension/Microsoft_OperationsManagementSuite_Part/PartType/LogsDashboardPart",
            "settings": {
              "content": {
                "Query": "ContainerLog | where Namespace == 'packamal' | summarize count() by bin(TimeGenerated, 1m)",
                "PartTitle": "Request Rate"
              }
            }
          }
        }
      ]
    }
  ]
}
```

## Best Practices

1. **Structured Logging**: Use JSON format for easy parsing
2. **Log Levels**: Use appropriate levels (DEBUG, INFO, WARNING, ERROR)
3. **Correlation IDs**: Include request IDs in logs for tracing
4. **Metrics**: Expose Prometheus metrics from all services
5. **Alerts**: Set up alerts for critical metrics
6. **Retention**: Configure log retention (30-90 days)
7. **Sampling**: Use sampling for high-volume traces
8. **Dashboards**: Create dashboards for key metrics
9. **Documentation**: Document alert runbooks

## Cost Optimization

- Use log sampling for high-volume applications
- Set appropriate retention periods
- Use metric queries instead of log queries when possible
- Archive old logs to cold storage

## Next Steps

1. Enable Container Insights
2. Configure Application Insights
3. Set up alert rules
4. Create dashboards
5. Document runbooks for alerts

