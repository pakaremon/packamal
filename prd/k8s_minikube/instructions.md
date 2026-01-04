Subject: Architecting a Scalable Web System on Kubernetes (Minikube/DOKS)

Role: You are a Senior DevOps and Full-Stack Engineer. Your goal is to implement a decoupled, scalable architecture using a single Docker image that can perform multiple roles.

1. The Architecture Blueprint
Implement a system with the following components in a single Kubernetes namespace:

Frontend  (listening on port 80).

Backend: Django (listening on port 8000).

Heavy Task (Worker): packamal/backend/package_analysis/analysis_runner.py script that processes intensive jobs from a queue.

Database: PostgreSQL (for persistent state).

Cache/Queue: Redis (for job queuing and Pub/Sub signaling).

2. Implementation Requirements
Single Image Strategy: Create one Dockerfile. Use entrypoint logic or Kubernetes command/args to determine if the container starts as the Web Server, the Backend API, or the Heavy Worker.

Communication Flow:

Backend receives an API request and pushes a JSON job object into a Redis List (the queue).

Heavy Worker uses a blocking pop (BRPOP) to pull jobs from the Redis List.

Heavy Worker performs a simulated heavy task (e.g., a 10-second timer), then updates the PostgreSQL database row to status: 'completed'.

Heavy Worker then sends a Redis Pub/Sub message to a channel named job_updates.

Backend subscribes to job_updates and logs the completion (ready for WebSocket implementation).

Kubernetes Manifests (Minikube Target):

Separate Deployments for Frontend, Backend, and Heavy Task.

A Horizontal Pod Autoscaler (HPA) for the Heavy Task deployment targeting 50% CPU utilization.

Services: LoadBalancer (or NodePort) for Frontend, ClusterIP for Backend, Redis, and Postgres.

ConfigMaps/Secrets: For DB credentials and Redis URLs.

3. Coding Tasks
Project Structure: Create a monorepo structure.

Backend API: Create a /dispatch endpoint that creates a DB entry and pushes to Redis.

Worker Logic: Create the worker loop with DB update and Redis Publish logic.

K8s YAML: Generate the deployment.yaml, service.yaml, hpa.yaml, and pvc.yaml for local testing.
