# Packamal GKE Deployment - Overview

## Executive Summary
This document defines the production GKE architecture for Packamal. It preserves the heavy Go analysis workload requirements while improving security, scalability, and GKE-specific integration.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│               Google Cloud HTTPS Load Balancer           │
│                   (GKE Ingress + Managed TLS)            │
└──────────────────────────┬───────────────────────────────┘
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
┌───────▼────────┐                    ┌───────▼────────┐
│   Frontend     │                    │    Backend     │
│   (Nginx)      │<──────────────────►│   (Django)     │
└────────────────┘                    └───────┬────────┘
                                               │
                     ┌─────────────────────────┼──────────────────────────┐
                     │                         │                          │
             ┌───────▼───────┐         ┌───────▼───────┐          ┌────────▼────────┐
             │  Celery       │         │  PostgreSQL   │          │   Redis         │
             │  Worker/Beat  │         │  (PD SSD)     │          │  (PD/Memory)    │
             └───────┬───────┘         └───────────────┘          └─────────────────┘
                     │
             ┌───────▼─────────────────────────────────────────────────────────┐
             │   Go Analysis Jobs (Privileged, hostPath, Podman-in-Pod)         │
             │   Dedicated heavy-analysis node pool (tainted)                   │
             └─────────────────────────────────────────────────────────────────┘
```

## GKE-Specific Improvements (with Rationale)
- **Workload Identity**: Removes static cloud credentials from pods and aligns with Google IAM best practices.
- **GKE Sandbox (gVisor)**: Applied to stateless workloads to reduce kernel attack surface.
- **Dedicated node pool for heavy analysis**: Protects core services from noisy neighbor effects and ensures privileged pods run only where allowed.
- **Persistent Disk-backed PVCs**: Uses standard/premium PD StorageClasses for all data volumes.
- **NetworkPolicies + PDBs + Quotas**: Adds enterprise-grade isolation and availability guarantees.

## Key Functional Requirements
- Dynamic Kubernetes Jobs for Go analysis workers
- Privileged containers with hostPath access to `/var/lib/containers`
- Persistent storage for PostgreSQL, Redis (celery), static/media, and analysis results
- Horizontal scaling for backend
- TLS termination and HTTPS redirects

## Success Criteria
- GKE Ingress serves HTTPS traffic for frontend and API
- Celery worker can create analysis jobs and receive callbacks
- Analysis results persist and are accessible to backend
- Pods comply with security contexts and network policies
