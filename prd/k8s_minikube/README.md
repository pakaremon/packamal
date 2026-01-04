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
minikube start --driver=docker --force-systemd=true --container-runtime=containerd
```


### Build local images and load to minikube

PROJECT DIR SAMPLE: `/home/azureuser/packamal`


Run the following:
```sh

docker build -t packamal-backend:local /home/azureuser/packamal/backend
docker build -t packamal-frontend:local /home/azureuser/packamal/frontend
docker build -t packamal-go-worker-analysis:local -f /home/azureuser/packamal/worker/cmd/analyze/Dockerfile /home/azureuser/packamal/worker

minikube image load packamal-backend:local 
minikube image load packamal-frontend:local
minikube image load packamal-go-worker-analysis:local

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


# Restarting
```sh
prd/restart_containerd_minikube.sh 
```

- Use `-w`: to build and load `go-heavy worker`
# Testing

You should log in and create an API key before testing.


Example IP: `20.187.145.56`

```bash
curl -X POST "http://20.187.145.56:8080/api/v1/analyze/" \
  -H "Authorization: Bearer 0rslEeJnMdBZvSfpMyF2xKYWZDEzYHwZixO00p0l33D8RcO6bkRfYQ8hawIsLeZd" \
  -H "Content-Type: application/json" \
  -d '{"purl": "pkg:npm/lodash@4.17.21"}'
```

# Troubleshooting

## Podman Cgroup Errors


Check whether the Cgroup error is resolved:
```bash
kubectl exec -n packamal analysis-lodash-914f70e8-hdh4h   -- sh -lc '
set -e
mkdir -p /sys/fs/cgroup/libpod_parent/test
echo $$ > /sys/fs/cgroup/libpod_parent/test/cgroup.procs
echo "OK: cgroup.procs write works"
'
```

For debugging: you should run a command to create a pod with `/bin/bash -c "sleep 3600"` in file `backend/package_analysis/services/k8s_service.py` to test the following command

```bash
❯ kubectl exec -it -n packamal analysis-<analysis-pod> -- /bin/bash
root@analysis-lodash-914f70e8-hdh4h:/# analyze -ecosystem npm -package lodash -version 4.17.21 -mode dynamic -nopull -dynamic-bucket file:///results/
```