# Pack-A-Mal Development Environment

Docker Compose-based development environment for Pack-A-Mal with separate services for backend, frontend, and database.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Nginx (Port 8080)                    │
│            Static Files Serving + Reverse Proxy         │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ↓
┌─────────────────────────────────────────────────────────┐
│              Django Backend (Port 8001)                  │
│              Pack-A-Mal Web Application                  │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ↓
┌─────────────────────────────────────────────────────────┐
│            PostgreSQL Database (Port 5433)              │
│                   packamal_dev                          │
└─────────────────────────────────────────────────────────┘
```

---

# Table of Contents

1. [Local Testing with Docker Compose](#1-local-testing-with-docker-compose)
2. [Local Testing with Kubernetes (Minikube)](#2-local-testing-with-kubernetes-minikube)
3. [Production Deployment on Azure Kubernetes Service (AKS)](#3-production-deployment-on-azure-kubernetes-service-aks)
4. [CI/CD with GitHub Actions](#4-cicd-with-github-actions)

---

## 1. Local Testing with Docker Compose

The simplest way to run Pack-A-Mal locally for development and testing.

### Prerequisites

- Docker Desktop installed and running
- Docker Compose V2

### Quick Start

```bash
# Build all images
docker-compose build

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Access:
# - Frontend: http://localhost:8080
# - Backend API: http://localhost:8001
# - Database: localhost:5433
```

### Services

#### 🐳 Backend (Django)
- **Container**: `packamal-backend-dev`
- **Port**: 8001 (mapped from 8000)
- **Framework**: Django 5.1.6
- **Python**: 3.12
- **Features**: Hot reload via volume mounting, Gunicorn with 4 workers

#### 🌐 Frontend (Nginx)
- **Container**: `packamal-frontend-dev`
- **Port**: 8080 (mapped from 80)
- **Purpose**: Serves static files and proxies to backend
- **Features**: Gzip compression, caching headers

#### 💾 Database (PostgreSQL)
- **Container**: `packamal-db-dev`
- **Port**: 5433 (mapped from 5432)
- **Version**: PostgreSQL 15 Alpine
- **Database**: `packamal`

#### 🔴 Redis
- **Container**: `packamal-redis-dev`
- **Port**: 6379
- **Purpose**: Message broker for Celery

#### ⚙️ Celery Workers
- **Worker 1**: Processes analysis queue (single worker for single-container execution)
- **Worker 2**: Processes maintenance and celery queues
- **Beat**: Periodic task scheduler
- **Flower**: Monitoring dashboard on port 5555

### Using Makefile (Recommended)

```bash
# Start services
make up

# View logs
make logs

# Run migrations
make migrate

# Create superuser
make createsuperuser

# Access backend shell
make shell-backend

# Access database shell
make shell-db

# Stop services
make down

# See all commands
make help
```

### Configuration

#### Environment Variables

Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
```

Default values:
- **POSTGRES_DB**: packamal
- **POSTGRES_USER**: packamal_db
- **POSTGRES_PASSWORD**: rock-beryl-say-devices
- **DEBUG**: True
- **BACKEND_PORT**: 8001
- **FRONTEND_PORT**: 8080
- **DB_PORT**: 5433

### Development Workflow

#### Making Code Changes

1. Edit files in `backend/` directory
2. Changes auto-reload (Django development server watches for changes)
3. Refresh browser to see updates

#### Database Migrations

```bash
# Create migrations
docker-compose exec backend python manage.py makemigrations

# Apply migrations
docker-compose exec backend python manage.py migrate

# Or use Makefile
make migrate
```

#### Installing New Dependencies

```bash
# Add to backend/requirements.txt
echo "new-package==1.0.0" >> backend/requirements.txt

# Rebuild backend image
docker-compose build backend

# Restart backend
docker-compose restart backend
```

### Scaling

```bash
# Scale to 3 instances
docker-compose up -d --scale backend=3

# Or using Makefile
make scale-backend

# View running instances
docker-compose ps
```

Nginx automatically load balances between backend instances.

### Data Persistence

All data persists in `./volumes/`:
- `postgres_data/` - Database files
- `media/` - Uploaded media files
- `static/` - Collected static files
- `logs/` - Application logs
- `analysis-results/` - Dynamic analysis results (Docker volume)

### Useful Commands

```bash
# View service status
docker-compose ps

# View logs
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f database

# Execute commands in containers
docker-compose exec backend python manage.py shell
docker-compose exec database psql -U packamal_db -d packamal
docker-compose exec backend bash

# Collect static files
docker-compose exec backend python manage.py collectstatic --noinput

# Run tests
docker-compose exec backend python manage.py test
```

### Troubleshooting

#### Container Won't Start

```bash
# Check logs
docker-compose logs backend

# Rebuild image
docker-compose build --no-cache backend
docker-compose up -d
```

#### Database Connection Issues

```bash
# Check database is healthy
docker-compose exec database pg_isready -U packamal_db

# Verify environment variables
docker-compose exec backend env | grep POSTGRES
```

#### Port Already in Use

Change ports in `docker-compose.yml`:
- Backend: `"8001:8000"` → `"9001:8000"`
- Frontend: `"8080:80"` → `"9080:80"`
- Database: `"5433:5432"` → `"5434:5432"`

#### Clean Start

```bash
# Remove all containers and volumes
docker-compose down -v

# Rebuild and start fresh
docker-compose build
docker-compose up -d
```

### Inspecting Analysis Results Volume

```bash
# List files in volume
docker run --rm -v analysis_results:/data alpine ls -lah /data

# View a file
docker run --rm -v analysis_results:/data alpine cat /data/path/to/file.json

# Copy files to host
docker run --rm -v analysis_results:/data -v "$PWD":/host alpine sh -c 'cp -r /data/* /host/'

# Inspect volume path
docker volume inspect analysis_results
```

### Testing API

```bash
curl -X POST "http://localhost:8080/api/v1/analyze/" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"purl": "pkg:npm/lodash@4.17.21"}'
```

---

## 2. Local Testing with Kubernetes (Minikube)

Run Pack-A-Mal on a local Kubernetes cluster using Minikube for testing Kubernetes-specific features.

### Prerequisites

- Minikube installed
- kubectl installed
- Docker installed

### Quick Start

#### 1. Start Minikube

```bash
minikube start --driver=docker --force-systemd=true --container-runtime=containerd
```

#### 2. Build and Load Images

```bash
# Build local images
docker build -t packamal-backend:local ./backend
docker build -t packamal-frontend:local ./frontend
docker build -t packamal-go-worker-analysis:local -f ./worker/cmd/analyze/Dockerfile ./worker

# Load images into minikube
minikube image load packamal-backend:local 
minikube image load packamal-frontend:local
minikube image load packamal-go-worker-analysis:local
```

#### 3. Apply Kubernetes Resources

```bash
# Apply all resources in correct order
./prd/k8s_minikube/apply-k8s.sh
```

This script will:
- Create namespace "packamal"
- Set up ConfigMaps and Secrets
- Create PersistentVolumeClaims
- Set up RBAC permissions for pod creation
- Deploy all services (PostgreSQL, Redis, Backend, Frontend, Workers, etc.)
- Configure Horizontal Pod Autoscaler (HPA)

#### 4. Create Superuser

```bash
kubectl exec -it -n packamal deployment/backend -- python manage.py createsuperuser
```

#### 5. Expose Services

```bash
# Port forward frontend service
./prd/k8s_minikube/port-forward-external.sh
```

This will expose the frontend on `http://localhost:8080` (or another port if 8080 is busy).

### Architecture

All components run in a single Kubernetes namespace `packamal`:

- **Frontend** (listening on port 80)
- **Backend**: Django (listening on port 8000)
- **Heavy Task (Worker)**: Pods are automatically created by the backend during requests using the image `packamal-go-worker-analysis:local`
- **Database**: PostgreSQL (for persistent state)
- **Cache/Queue**: Redis (for job queuing)

### Communication Flow

1. Backend receives an API request and pushes a JSON job object into Redis. The Celery worker processes the job and sets the task status to "submitted" or "running".

2. The Celery worker creates a pod "go analysis worker" for dynamic analysis. See details in `backend/package_analysis/services/k8s_service.py`.

3. The pod "go analysis worker" performs the analysis. After the analysis is completed:
   - It saves the analysis result to permanent PVC storage called `"analysis-results-pvc"`
   - It sends a signal to the internal API at `"http://backend:8000/api/v1/internal/callback/done/"` to notify the backend that the analysis task is completed

4. The backend, upon receiving the signal from "go analysis worker":
   - Reads the analysis result from storage PVC `"analysis-results-pvc"`
   - Saves the result to the database
   - Updates the analysis task status to `DONE`

### Additional Components

- A Horizontal Pod Autoscaler (HPA) for the Backend deployment
- Automatic pod creation for analysis workers from image `packamal-go-worker-analysis:local`, based on requests from the Celery worker

### Restarting

```bash
# Restart minikube and rebuild/load images
./prd/k8s_minikube/restart_containerd_minikube.sh

# Use -w flag to build and load go-heavy worker
./prd/k8s_minikube/restart_containerd_minikube.sh -w
```

### Testing

You should log in and create an API key before testing.

```bash
curl -X POST "http://localhost:8080/api/v1/analyze/" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"purl": "pkg:npm/lodash@4.17.21"}'
```

### Troubleshooting

#### Podman Cgroup Errors

Check whether the Cgroup error is resolved:

```bash
kubectl exec -n packamal analysis-lodash-914f70e8-hdh4h -- sh -lc '
set -e
mkdir -p /sys/fs/cgroup/libpod_parent/test
echo $$ > /sys/fs/cgroup/libpod_parent/test/cgroup.procs
echo "OK: cgroup.procs write works"
'
```

#### Debugging Analysis Pods

For debugging, you can exec into an analysis pod:

```bash
kubectl exec -it -n packamal analysis-<analysis-pod> -- /bin/bash
```

Inside the pod, you can run:

```bash
analyze -ecosystem npm -package lodash -version 4.17.21 -mode dynamic -nopull -dynamic-bucket file:///results/
```

### Useful Commands

```bash
# Check pod status
kubectl get pods -n packamal

# View logs
kubectl logs -f -n packamal deployment/backend
kubectl logs -f -n packamal deployment/celery-worker

# Check services
kubectl get svc -n packamal

# Check PVCs
kubectl get pvc -n packamal

# Check HPA
kubectl get hpa -n packamal
```

### Documentation

For more details, see:
- [Minikube README](prd/k8s_minikube/README.md)
- [Minikube Instructions](prd/k8s_minikube/instructions.md)

---

## 3. Production Deployment on Azure Kubernetes Service (AKS)

Deploy Pack-A-Mal to Azure Kubernetes Service (AKS) for production use.

### Overview

This deployment uses Azure Kubernetes Service (AKS) with:
- Azure Container Registry (ACR) for container images
- Azure Disk for persistent storage
- Azure Load Balancer for external access
- Azure Monitor for logging and monitoring

### Prerequisites

- Azure subscription with appropriate permissions
- Azure CLI installed and configured
- kubectl installed
- Docker installed (for building images)

### Quick Start

#### 1. Set Up Infrastructure

Follow the comprehensive guide in [prd/aks/01-infrastructure-setup.md](prd/aks/01-infrastructure-setup.md) to:
- Create AKS cluster
- Set up networking
- Configure storage classes

#### 2. Set Up Container Registry

Follow [prd/aks/02-container-registry.md](prd/aks/02-container-registry.md) to:
- Create Azure Container Registry (ACR)
- Build and push images
- Configure AKS to pull from ACR

#### 3. Configure Security and RBAC

Follow [prd/aks/03-security-rbac.md](prd/aks/03-security-rbac.md) to:
- Set up RBAC
- Configure Azure Key Vault
- Set up network policies

#### 4. Deploy Application

```bash
# Connect to AKS cluster
az aks get-credentials --resource-group packamal-rg --name packamal-aks

# Apply Kubernetes manifests
./prd/aks/apply-aks.sh
```

This script will:
- Create namespace and ConfigMaps
- Set up PersistentVolumeClaims
- Configure RBAC
- Deploy databases (PostgreSQL, Redis)
- Deploy application components (Backend, Frontend, Workers)
- Set up HPA and monitoring

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Azure Load Balancer                   │
│                    (Ingress Controller)                  │
└───────────────────────┬─────────────────────────────────┘
                        │
        ┌───────────────┴───────────────┐
        │                                 │
┌───────▼────────┐              ┌───────▼────────┐
│   Frontend      │              │    Backend      │
│   (Nginx)       │──────────────│   (Django)      │
└────────────────┘              └───────┬──────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    │                   │                   │
            ┌───────▼──────┐    ┌───────▼──────┐    ┌───────▼──────┐
            │   Celery     │    │  PostgreSQL  │    │    Redis     │
            │   Worker     │    │              │    │              │
            └───────┬──────┘    └──────────────┘    └──────────────┘
                    │
            ┌───────▼──────┐
            │  Analysis    │
            │  Jobs (Go)    │
            │  (Ephemeral)  │
            └──────────────┘
```

### Key Components

- **Frontend**: Nginx serving static files
- **Backend**: Django/Gunicorn API server with HPA
- **Celery Worker**: Processes analysis jobs, creates Kubernetes Jobs
- **Go Analysis Worker**: Ephemeral pods for heavy analysis
- **PostgreSQL**: Primary database with persistent storage
- **Redis**: Message broker and cache with persistent storage

### Migration from Minikube

For step-by-step migration instructions, see [prd/aks/09-migration-guide.md](prd/aks/09-migration-guide.md).

### Documentation

Comprehensive documentation is available in the `prd/aks/` directory:

1. **[00-overview.md](prd/aks/00-overview.md)** - High-level overview, architecture, and goals
2. **[01-infrastructure-setup.md](prd/aks/01-infrastructure-setup.md)** - AKS cluster creation, networking, storage
3. **[02-container-registry.md](prd/aks/02-container-registry.md)** - Azure Container Registry setup and image management
4. **[03-security-rbac.md](prd/aks/03-security-rbac.md)** - Security, RBAC, Key Vault, network policies
5. **[04-kubernetes-manifests/](prd/aks/04-kubernetes-manifests/)** - AKS-optimized Kubernetes manifests
6. **[05-cicd-pipeline.md](prd/aks/05-cicd-pipeline.md)** - CI/CD pipeline setup
7. **[06-monitoring-logging.md](prd/aks/06-monitoring-logging.md)** - Monitoring, logging, and observability
8. **[07-backup-disaster-recovery.md](prd/aks/07-backup-disaster-recovery.md)** - Backup strategies and DR procedures
9. **[08-cost-optimization.md](prd/aks/08-cost-optimization.md)** - Cost optimization strategies
10. **[09-migration-guide.md](prd/aks/09-migration-guide.md)** - Step-by-step migration from Minikube to AKS

### Estimated Costs

**Initial Setup**: ~$549/month
- AKS Cluster (3 nodes): ~$450
- Storage: ~$15
- Load Balancer: ~$25
- Monitoring: ~$50
- Container Registry: ~$9

**After Optimization**: ~$80-240/month
- See [08-cost-optimization.md](prd/aks/08-cost-optimization.md) for details

### Useful Commands

```bash
# Connect to AKS
az aks get-credentials --resource-group packamal-rg --name packamal-aks

# Check deployments
kubectl get deployments -n packamal

# Check pods
kubectl get pods -n packamal

# View logs
kubectl logs -f -n packamal deployment/backend

# Check services
kubectl get svc -n packamal

# Check HPA
kubectl get hpa -n packamal

# Get external IP
kubectl get svc frontend -n packamal
```

### Troubleshooting

#### Image Pull Errors

```bash
# Ensure AKS has permission to pull from ACR
az aks update -n packamal-aks -g packamal-rg --attach-acr packamalacr
```

#### PVC Not Binding

```bash
# Check storage class
kubectl get storageclass

# Check PVC status
kubectl get pvc -n packamal
kubectl describe pvc <pvc-name> -n packamal
```

#### Analysis Jobs Failing

```bash
# Check analysis job pods
kubectl get pods -n packamal | grep analysis

# Check logs
kubectl logs -n packamal <analysis-pod-name>

# Verify privileged mode is enabled
kubectl get job -n packamal -o yaml | grep privileged
```

---

## 4. CI/CD with GitHub Actions

Automated CI/CD pipeline for building, pushing, and deploying Pack-A-Mal to AKS.

### Overview

The CI/CD pipeline automatically:
- Builds Docker images (Backend, Frontend, Go Worker)
- Pushes images to Azure Container Registry (ACR)
- Updates Kubernetes manifests with new image tags
- Deploys to AKS cluster

### Prerequisites

- GitHub repository with Actions enabled
- Azure Container Registry (ACR) created
- AKS cluster deployed
- Azure Service Principal with appropriate permissions

### Quick Start

#### 1. Configure GitHub Secrets

Follow [prd/cicd/02-github-secrets.md](prd/cicd/02-github-secrets.md) to set up:

**Required Secrets:**
- `ACR_USERNAME` - ACR admin username
- `ACR_PASSWORD` - ACR admin password
- `AZURE_CREDENTIALS` - Azure Service Principal JSON

**Get ACR Credentials:**
```bash
az acr credential show --name packamalacr
```

**Create Service Principal:**
```bash
az ad sp create-for-rbac \
  --name "packamal-github-actions" \
  --role contributor \
  --scopes /subscriptions/SUBSCRIPTION_ID/resourceGroups/packamal-rg \
  --sdk-auth
```

#### 2. Workflow File

The workflow file is located at `.github/workflows/aks-deploy.yml`.

**Trigger:**
- Automatic: Push to `main` branch
- Manual: Workflow dispatch from GitHub Actions UI

#### 3. Test Workflow

1. Push code to `main` branch to trigger workflow automatically
2. Or manually trigger from GitHub Actions tab
3. View logs in GitHub Actions to monitor progress

### Pipeline Architecture

```
┌─────────────────┐
│  Git Push to    │
│  main branch    │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  GitHub Actions Workflow Trigger    │
│  (.github/workflows/aks-deploy.yml) │
└────────┬────────────────────────────┘
         │
         ├─────────────────┬─────────────────┐
         ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Build        │  │ Build        │  │ Build        │
│ Backend      │  │ Frontend     │  │ Go Worker    │
│ Image        │  │ Image        │  │ Image        │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       └─────────────────┴─────────────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  Push to ACR         │
              │  packamalacr.        │
              │  azurecr.io          │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  Update Image Tags    │
              │  in K8s Manifests     │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  Connect to AKS      │
              │  packamal-aks        │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  Deploy Manifests    │
              │  to namespace        │
              │  packamal            │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  Verify Deployment   │
              │  & Health Check      │
              └──────────────────────┘
```

### Workflow Jobs

#### Job 1: build-and-push

- Builds Backend image from `./backend/Dockerfile`
- Builds Frontend image from `./frontend/Dockerfile`
- Builds Go Worker image from `./worker/cmd/analyze/Dockerfile`
- Pushes all images to `packamalacr.azurecr.io`
- Tags with commit SHA and `latest`

#### Job 2: deploy

- Logs into Azure using Service Principal
- Connects to AKS cluster `packamal-aks`
- Updates image tags in Kubernetes manifests
- Deploys all manifests to namespace `packamal`
- Verifies deployment and performs health checks

### Images Built

| Image | Dockerfile | Registry Path |
|-------|-----------|---------------|
| Backend | `./backend/Dockerfile` | `packamalacr.azurecr.io/packamal-backend` |
| Frontend | `./frontend/Dockerfile` | `packamalacr.azurecr.io/packamal-frontend` |
| Go Worker | `./worker/cmd/analyze/Dockerfile` | `packamalacr.azurecr.io/packamal-go-worker-analysis` |

### Manifests Updated

The workflow automatically updates image tags in:

1. **05-backend.yaml** - Backend deployment (initContainer and main container)
2. **07-frontend.yaml** - Frontend deployment
3. **06-worker.yaml** - Celery worker deployment
4. **08-worker-2.yaml** - Celery worker 2 deployment
5. **01-config.yaml** - ANALYSIS_IMAGE config value
6. **13-image-preloader.yaml** - Image preloader deployment

### Verify Deployment

```bash
# Connect to AKS
az aks get-credentials --resource-group packamal-rg --name packamal-aks

# Check deployments
kubectl get deployments -n packamal

# Check pods
kubectl get pods -n packamal

# Check image versions
kubectl get deployments -n packamal -o jsonpath='{range .items[*]}{.metadata.name}{":\t"}{.spec.template.spec.containers[*].image}{"\n"}{end}'
```

### Rollback

If deployment fails:

```bash
# Rollback deployment
kubectl rollout undo deployment/backend -n packamal
kubectl rollout undo deployment/frontend -n packamal
kubectl rollout undo deployment/celery-worker -n packamal

# Or rollback to previous image by updating manifest with old commit SHA
```

### Documentation

For more details, see:
- [CI/CD Plan](prd/cicd/01-plan.md) - Detailed pipeline architecture and implementation
- [GitHub Secrets Guide](prd/cicd/02-github-secrets.md) - How to configure secrets
- [CI/CD README](prd/cicd/README.md) - Overview and quick reference

### Troubleshooting

#### Workflow Not Triggering

- ✅ Check `.github/workflows/aks-deploy.yml` is committed
- ✅ Check push is to `main` branch
- ✅ Check GitHub Actions is enabled for repository

#### Build Failures

- ✅ Check Dockerfile syntax
- ✅ Check build context paths
- ✅ Check ACR credentials

#### Deploy Failures

- ✅ Check Azure credentials
- ✅ Check AKS cluster status
- ✅ Check Service Principal permissions
- ✅ Check kubectl connection

#### Image Pull Failures

```bash
# Ensure AKS has permission to pull from ACR
az aks update -n packamal-aks -g packamal-rg --attach-acr packamalacr
```

### Monitoring

#### GitHub Actions Logs

- View logs in GitHub Actions tab
- Each workflow run has detailed logs
- Logs can be downloaded

#### Kubernetes Logs

```bash
# View deployment status
kubectl get deployments -n packamal

# View pod logs
kubectl logs -f deployment/backend -n packamal

# View rollout status
kubectl rollout status deployment/backend -n packamal
```

---

## Support and Resources

### Project Documentation

- **Docker Compose**: This README (Section 1)
- **Minikube**: [prd/k8s_minikube/README.md](prd/k8s_minikube/README.md)
- **AKS**: [prd/aks/README.md](prd/aks/README.md)
- **CI/CD**: [prd/cicd/README.md](prd/cicd/README.md)

### External Resources

- [Django Documentation](https://docs.djangoproject.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [Azure Kubernetes Service Documentation](https://docs.microsoft.com/azure/aks/)
- [Azure Container Registry Documentation](https://docs.microsoft.com/azure/container-registry/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)

---

## Next Steps

1. **For Development**: Start with [Local Testing with Docker Compose](#1-local-testing-with-docker-compose)
2. **For Kubernetes Testing**: Follow [Local Testing with Kubernetes (Minikube)](#2-local-testing-with-kubernetes-minikube)
3. **For Production**: Deploy to [Azure Kubernetes Service (AKS)](#3-production-deployment-on-azure-kubernetes-service-aks)
4. **For Automation**: Set up [CI/CD with GitHub Actions](#4-cicd-with-github-actions)
