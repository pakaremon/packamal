# Container Registry (Artifact Registry)

## Create Repository
```sh
export PROJECT_ID="k8s-packamal"
export REPO_NAME="packamal-repo"
export REGION="us-central1"

# Xóa nếu đã lỡ tạo sai (cẩn thận: lệnh này xóa sạch ảnh bên trong)
# gcloud artifacts repositories delete $REPO_NAME --location=$REGION --project=$PROJECT_ID --quiet

# Tạo lại kho lưu trữ chuẩn
# gcloud artifacts repositories create $REPO_NAME \
#     --repository-format=docker \
#     --location=$REGION \
#     --description="Production Artifact Registry for Packamal GKE" \
#     --project=$PROJECT_ID

## Configure Docker Auth
```
gcloud auth configure-docker $REGION-docker.pkg.dev
```

```sh
export PROJECT_ID="k8s-packamal"
export REPO_NAME="packamal-repo"
export REGION="us-central1"

export TAG="v1"

# Build & Tag Backend
docker build -t $REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/backend:$TAG /home/packamal/backend

# Build & Tag Frontend
docker build -t $REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/frontend:$TAG /home/packamal/frontend

# Build & Tag Go Worker (Lưu ý đường dẫn context /home/packamal/worker)
docker build -t $REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/go-worker-analysis:$TAG \
    -f /home/packamal/worker/cmd/analyze/Dockerfile /home/packamal/worker

# Push images lên Google Artifact Registry
docker push $REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/backend:$TAG
docker push $REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/frontend:$TAG
docker push $REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/go-worker-analysis:$TAG

```

## Configure files 

```sh
export PROJECT_ID="k8s-packamal"
export REPO_NAME="packamal-repo"
export REGION="us-central1"

export TAG="v1"

export NAMESPACE="packamal-dev"





# 2. Tạo các thư mục tạm để chứa các file đã được thay thế biến theo từng phase
mkdir -p ./prd/gke/processed-k8s/base
mkdir -p ./prd/gke/processed-k8s/data
mkdir -p ./prd/gke/processed-k8s/apps

# 4. Copy kustomization.yaml files to processed directory
cp ./prd/gke/04-kubernetes-manifests/base/kustomization.yaml ./prd/gke/processed-k8s/base/ 2>/dev/null || true
cp ./prd/gke/04-kubernetes-manifests/data/kustomization.yaml ./prd/gke/processed-k8s/data/ 2>/dev/null || true
cp ./prd/gke/04-kubernetes-manifests/apps/kustomization.yaml ./prd/gke/processed-k8s/apps/ 2>/dev/null || true

# 3. Chạy vòng lặp để xử lý từng file theo phase
# Phase 1: Base infrastructure
for f in ./prd/gke/04-kubernetes-manifests/base/*.yaml; do
    [ -f "$f" ] && envsubst < "$f" > "./prd/gke/processed-k8s/base/$(basename "$f")"
done

# Phase 2: Data services
for f in ./prd/gke/04-kubernetes-manifests/data/*.yaml; do
    [ -f "$f" ] && envsubst < "$f" > "./prd/gke/processed-k8s/data/$(basename "$f")"
done

# Phase 3: Application services
for f in ./prd/gke/04-kubernetes-manifests/apps/*.yaml; do
    [ -f "$f" ] && envsubst < "$f" > "./prd/gke/processed-k8s/apps/$(basename "$f")"
done


```sh
gcloud iam service-accounts add-iam-policy-binding \
  "packamal-gke@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="${PROJECT_ID}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:${PROJECT_ID}.svc.id.goog[${NAMESPACE}/backend-serviceaccount]"
```


```sh
# Delete the database pod and PVC
kubectl delete pod -n packamal -l app=database
kubectl delete pvc -n packamal postgres-pvc

# The StatefulSet/Deployment will recreate the pod with a fresh database
# Wait for it to come back up
kubectl get pods -n packamal -w

# Then manually trigger the migrate job again or restart your deployment
```



# 5. Apply toàn bộ lên GKE với migrations tự động
```sh
# Script này tự động:
# - Deploy base infrastructure
# - Deploy databases
# - Chờ database ready
# - ⭐ TỰ ĐỘNG chạy migrations
# - Deploy applications
./prd/gke/apply-gke.sh
```

Hoặc apply từng phase thủ công:
```sh
# Phase 1: Base
kubectl apply -k ./prd/gke/processed-k8s/base

# Phase 2: Data
kubectl apply -k ./prd/gke/processed-k8s/data

# Phase 2.5: Wait for database
kubectl wait --for=condition=ready pod -l app=database -n ${NAMESPACE} --timeout=120s

# Phase 2.7: Run migrations (TỰ ĐỘNG)
kubectl delete job -l component=migration -n ${NAMESPACE} --ignore-not-found=true
envsubst < ./prd/gke/04-kubernetes-manifests/apps/00-django-migrate-job.yaml | kubectl apply -f - -n ${NAMESPACE}
kubectl wait --for=condition=complete --timeout=5m job/django-migrate-${TAG} -n ${NAMESPACE}

# Phase 3: Apps
kubectl apply -k ./prd/gke/processed-k8s/apps
```

```
```sh
export BUCKET="packamal-${PROJECT_ID}"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="allUsers" \
  --role="roles/storage.objectViewer"
```

# check 
```sh
kubectl describe ingress -n ${NAMESPACE} packamal-ingress
```
# Connect to internet 


kubectl get ingress -n ${NAMESPACE}

# create super user
kubectl exec -it -n ${NAMESPACE} deployment/backend -- python manage.py createsuperuser


# Trouble shoot

```sh
kubectl logs -n ${NAMESPACE} deployment/backend -c backend
```

#testing
```sh
kubectl patch configmap packamal-config -n packamal-dev --type merge -p '{"data":{"MAX_CONCURRENT_JOBS":"5"}}'
```

```sh
 kubectl describe configmap packamal-config -n packamal-dev
```

```sh
# Restart the Backend
kubectl rollout restart deployment backend -n packamal-dev

# Restart the Celery Worker
kubectl rollout restart deployment celery-worker -n packamal-dev

# Restart the Celery Beat
kubectl rollout restart deployment celery-beat -n packamal-dev
```

```sh
kubectl exec -it deploy/backend -n packamal-dev -- printenv MAX_CONCURRENT_JOBS
```