# Packamal AKS Production Deployment Plan - Overview

## Executive Summary

This document provides a comprehensive production deployment plan for migrating the Packamal application from local Minikube to Azure Kubernetes Service (AKS). The plan covers infrastructure setup, security, scalability, monitoring, and operational best practices.

## Application Architecture

### Components

1. **Frontend (Nginx)**
   - Serves static files and media
   - Port: 80
   - Image: `packamal-frontend`

2. **Backend (Django/Gunicorn)**
   - REST API server
   - Port: 8000
   - Image: `packamal-backend`
   - Horizontal Pod Autoscaler (HPA) enabled

3. **Celery Worker**
   - Processes analysis jobs from Redis queue
   - Creates ephemeral Kubernetes Jobs for heavy analysis
   - Image: `packamal-backend` (same as backend, different command)

4. **Celery Beat**
   - Scheduled task scheduler
   - Image: `packamal-backend`

5. **Flower**
   - Celery monitoring dashboard
   - Image: `packamal-backend`

6. **Go Analysis Worker (Ephemeral Jobs)**
   - Created dynamically by Celery worker
   - Performs heavy package analysis
   - Image: `packamal-go-worker-analysis`
   - Requires privileged mode for Podman-in-Pod

7. **PostgreSQL**
   - Primary database
   - Persistent storage required

8. **Redis**
   - Message broker for Celery
   - Cache storage
   - Persistent storage for AOF

### Data Flow

1. **Request Flow:**
   - User → Frontend (Nginx) → Backend API
   - Backend creates task in PostgreSQL
   - Backend pushes job to Redis queue

2. **Analysis Flow:**
   - Celery worker picks job from Redis
   - Celery worker creates Kubernetes Job via RBAC
   - Go analysis worker pod executes analysis
   - Results saved to PVC (`analysis-results-pvc`)
   - Worker calls backend callback API
   - Backend reads results from PVC and updates database

3. **Storage:**
   - `postgres-pvc`: PostgreSQL data (5Gi)
   - `redis-pvc`: Redis AOF data (1Gi)
   - `app-shared-pvc`: Static files and media (2Gi)
   - `analysis-results-pvc`: Analysis results (10Gi)

## Key Requirements

### Functional Requirements
- ✅ Dynamic pod creation for analysis jobs
- ✅ Persistent storage for database, cache, and results
- ✅ Horizontal scaling of backend
- ✅ Static file serving via Nginx
- ✅ Internal API communication

### Non-Functional Requirements
- **High Availability**: Multi-node cluster with pod distribution
- **Scalability**: HPA for backend, dynamic job scaling
- **Security**: RBAC, network policies, secrets management
- **Performance**: Image preloading, resource optimization
- **Observability**: Logging, monitoring, alerting
- **Disaster Recovery**: Automated backups, restore procedures
- **Cost Optimization**: Right-sizing, spot instances for jobs

## AKS-Specific Considerations

### Advantages Over Minikube
1. **Production-Grade Infrastructure**
   - Managed Kubernetes control plane
   - Multi-node cluster support
   - Built-in load balancing
   - Azure integration (Key Vault, Monitor, etc.)

2. **Storage**
   - Azure Disk (Premium SSD) for persistent volumes
   - Azure Files for ReadWriteMany scenarios
   - Automatic backup and snapshot capabilities

3. **Networking**
   - Azure Load Balancer for external access
   - Application Gateway for advanced routing
   - Network policies for micro-segmentation

4. **Security**
   - Azure AD integration for RBAC
   - Managed identities for service accounts
   - Key Vault integration for secrets

5. **Monitoring**
   - Azure Monitor for containers
   - Log Analytics workspace
   - Application Insights integration

### Challenges to Address
1. **Privileged Pods**: Go worker requires privileged mode for Podman
2. **HostPath Volumes**: Need to replace with Azure Disk/Files
3. **Image Registry**: Migrate from local images to ACR
4. **Network Policies**: Implement pod-to-pod communication rules
5. **Resource Limits**: Optimize for AKS node sizes
6. **Cost Management**: Monitor and optimize resource usage

## Deployment Phases

### Phase 1: Infrastructure Setup
- Create AKS cluster
- Set up Azure Container Registry (ACR)
- Configure networking and security
- Set up storage classes

### Phase 2: Image Migration
- Build and push images to ACR
- Update image references in manifests
- Test image pulls

### Phase 3: Application Deployment
- Deploy base infrastructure (namespace, config, secrets)
- Deploy databases (PostgreSQL, Redis)
- Deploy application components
- Configure RBAC and service accounts

### Phase 4: External Access
- Configure ingress controller
- Set up load balancer
- Configure DNS

### Phase 5: Monitoring & Operations
- Set up Azure Monitor
- Configure logging
- Set up alerting
- Create runbooks

### Phase 6: Optimization
- Performance tuning
- Cost optimization
- Security hardening
- Backup automation

## Success Criteria

- ✅ All components deployed and running
- ✅ External access via HTTPS
- ✅ Analysis jobs execute successfully
- ✅ HPA scales backend based on load
- ✅ Monitoring and alerting operational
- ✅ Backups automated
- ✅ Security best practices implemented
- ✅ Cost within budget

## Document Structure

1. **00-overview.md** (this document) - High-level overview
2. **01-infrastructure-setup.md** - AKS cluster and infrastructure
3. **02-container-registry.md** - ACR setup and image management
4. **03-security-rbac.md** - Security and access control
5. **04-kubernetes-manifests/** - AKS-optimized manifests
6. **05-cicd-pipeline.md** - CI/CD automation
7. **06-monitoring-logging.md** - Observability setup
8. **07-backup-disaster-recovery.md** - Backup and DR
9. **08-cost-optimization.md** - Cost management
10. **09-migration-guide.md** - Step-by-step migration from Minikube

## Next Steps

1. Review infrastructure requirements (01-infrastructure-setup.md)
2. Set up AKS cluster and ACR
3. Follow migration guide (09-migration-guide.md)
4. Deploy using provided manifests
5. Configure monitoring and alerting
6. Perform load testing and optimization

