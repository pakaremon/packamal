# Packamal AKS Production Deployment Plan

## Overview

This directory contains a comprehensive production deployment plan for migrating Packamal from Minikube to Azure Kubernetes Service (AKS).

## Document Structure

1. **[00-overview.md](00-overview.md)** - High-level overview, architecture, and goals
2. **[01-infrastructure-setup.md](01-infrastructure-setup.md)** - AKS cluster creation, networking, storage
3. **[02-container-registry.md](02-container-registry.md)** - Azure Container Registry setup and image management
4. **[03-security-rbac.md](03-security-rbac.md)** - Security, RBAC, Key Vault, network policies
5. **[04-kubernetes-manifests/](04-kubernetes-manifests/)** - AKS-optimized Kubernetes manifests
6. **[05-cicd-pipeline.md](05-cicd-pipeline.md)** - CI/CD pipeline setup (GitHub Actions, Azure DevOps)
7. **[06-monitoring-logging.md](06-monitoring-logging.md)** - Monitoring, logging, and observability
8. **[07-backup-disaster-recovery.md](07-backup-disaster-recovery.md)** - Backup strategies and DR procedures
9. **[08-cost-optimization.md](08-cost-optimization.md)** - Cost optimization strategies
10. **[09-migration-guide.md](09-migration-guide.md)** - Step-by-step migration from Minikube to AKS

## Quick Start

### For First-Time Deployment

1. **Read the Overview**: Start with [00-overview.md](00-overview.md)
2. **Set Up Infrastructure**: Follow [01-infrastructure-setup.md](01-infrastructure-setup.md)
3. **Configure Container Registry**: Follow [02-container-registry.md](02-container-registry.md)
4. **Migrate from Minikube**: Follow [09-migration-guide.md](09-migration-guide.md)

### For Existing AKS Deployment

- **Security**: Review [03-security-rbac.md](03-security-rbac.md)
- **CI/CD**: Set up [05-cicd-pipeline.md](05-cicd-pipeline.md)
- **Monitoring**: Configure [06-monitoring-logging.md](06-monitoring-logging.md)
- **Backups**: Implement [07-backup-disaster-recovery.md](07-backup-disaster-recovery.md)
- **Costs**: Optimize with [08-cost-optimization.md](08-cost-optimization.md)

## Architecture

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

## Key Components

- **Frontend**: Nginx serving static files
- **Backend**: Django/Gunicorn API server
- **Celery Worker**: Processes analysis jobs, creates Kubernetes Jobs
- **Go Analysis Worker**: Ephemeral pods for heavy analysis
- **PostgreSQL**: Primary database
- **Redis**: Message broker and cache
- **HPA**: Horizontal Pod Autoscaler for backend

## Prerequisites

- Azure subscription with appropriate permissions
- Azure CLI installed and configured
- kubectl installed
- Docker installed (for building images)
- Basic knowledge of Kubernetes and Azure

## Estimated Costs

**Initial Setup**: ~$549/month
- AKS Cluster (3 nodes): ~$450
- Storage: ~$15
- Load Balancer: ~$25
- Monitoring: ~$50
- Container Registry: ~$9

**After Optimization**: ~$80-240/month
- See [08-cost-optimization.md](08-cost-optimization.md) for details

## Migration Timeline

**Estimated Time**: 4-7 hours
- Infrastructure Setup: 1-2 hours
- Image Migration: 30-60 minutes
- Configuration: 30 minutes
- Deployment: 1-2 hours
- Verification: 30 minutes
- Post-Migration: 1-2 hours

## Support and Troubleshooting

### Common Issues

1. **Image Pull Errors**: Check ACR attachment and permissions
2. **PVC Not Binding**: Verify storage class and node capacity
3. **Analysis Jobs Failing**: Check privileged mode and image preloader
4. **Database Connection**: Verify service and network policies

### Getting Help

1. Check relevant documentation in this directory
2. Review logs: `kubectl logs -n packamal <pod-name>`
3. Check events: `kubectl get events -n packamal`
4. Review Azure Monitor logs

## Best Practices

1. **Security**: Use Azure Key Vault for secrets, enable network policies
2. **Monitoring**: Set up Container Insights and Application Insights
3. **Backups**: Automate database and PVC backups
4. **Costs**: Right-size resources, use spot instances for jobs
5. **CI/CD**: Automate builds and deployments
6. **Documentation**: Keep runbooks updated

## Next Steps

1. Review [00-overview.md](00-overview.md) for architecture details
2. Follow [09-migration-guide.md](09-migration-guide.md) for step-by-step migration
3. Configure monitoring and backups after deployment
4. Optimize costs based on actual usage

## Additional Resources

- [Azure Kubernetes Service Documentation](https://docs.microsoft.com/azure/aks/)
- [Azure Container Registry Documentation](https://docs.microsoft.com/azure/container-registry/)
- [Kubernetes Documentation](https://kubernetes.io/docs/)

