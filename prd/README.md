# Overview

## 1. The Architecture

All components run in a single Kubernetes namespace `packamal`:

- **Frontend** (listening on port 80)
- **Backend**: Django (listening on port 8000)
- **Heavy Task (Worker)**: Pods are automatically created by the backend during requests using the image `packamal-go-worker-analysis:local`. See details in `backend/package_analysis/services/k8s_service.py`
- **Database**: PostgreSQL (for persistent state)
- **Cache/Queue**: Redis (for job queuing)

## Communication Flow

1. Backend receives an API request and pushes a JSON job object into Redis. The Celery worker processes the job and sets the task status to "submitted" or "running".

2. The Celery worker creates a pod "go analysis worker" for dynamic analysis. See details in `backend/package_analysis/services/k8s_service.py`.

3. The pod "go analysis worker" performs the analysis. After the analysis is completed:
   - It saves the analysis result to permanent PVC storage called `"analysis-results-pvc"`
   - It sends a signal to the internal API at `"http://backend:8000/api/v1/internal/callback/done/"` to notify the backend that the analysis task is completed

4. The backend, upon receiving the signal from "go analysis worker":
   - Reads the analysis result from storage PVC `"analysis-results-pvc"`
   - Saves the result to the database
   - Updates the analysis task status to `DONE`

## Additional Components

- A Horizontal Pod Autoscaler (HPA) for the Backend deployment
- Automatic pod creation for analysis workers from image `packamal-go-worker-analysis:local`, based on requests from the Celery worker

# Setup

## Local minikube

### Start minikube

```bash
minikube start
```

### Build local images and load to minikube

PROJECT DIR SAMPLE: `/home/azureuser/packamal`

```bash
eval "$(minikube docker-env)"
docker build -t packamal-backend:local /home/azureuser/packamal/backend
docker build -t packamal-frontend:local /home/azureuser/packamal/frontend
docker build -t packamal-go-worker-analysis:local -f /home/azureuser/packamal/worker/cmd/analyze/Dockerfile /home/azureuser/packamal/worker
```

### Apply Kubernetes resources by phase

This script will:
- Start namespace "packamal"
- Build the pod for each service
- Setup permissions for the Celery worker service so that it can create pods

```bash
/home/azureuser/packamal/prd/apply-k8s.sh
```

### Create super user

```bash
kubectl exec -it -n packamal deployment/backend -- python manage.py createsuperuser
```

### Expose port of frontend service from node to local

```bash
/home/azureuser/packamal/prd/port-forward-external.sh
```

# Testing

You should login and create an API key before testing.


IP sample: `20.187.145.56`

```bash
curl -X POST "http://20.187.145.56:8080/api/v1/analyze/" \
  -H "Authorization: Bearer qBXbXoH8SI0W88RxJHkWV8OXfIjbZmpWIRj2ZCpaHZbjimzbrWPOwCrmWaWnDmoo" \
  -H "Content-Type: application/json" \
  -d '{"purl": "pkg:npm/lodash@4.17.21"}'
```
