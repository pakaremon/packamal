# Setup Blob Storage (Google Cloud Storage) cho PackaMal (Static/Media + Analysis Results)

Tài liệu này hướng dẫn bạn tạo **Google Cloud Storage (GCS) bucket** (đóng vai trò “blob/object storage”) và cấu hình để:

- **Backend (Django)** upload **static** lên GCS bằng `collectstatic` và dùng GCS làm nơi serve static/media.
- **Go heavy worker** upload **dynamic analysis results** lên GCS theo key cố định: `<task_id>/report.json`.
- **Backend/Celery** đọc lại kết quả từ GCS để xử lý và lưu DB.

> Repo này đang dùng **Workload Identity** (không dùng JSON key file trong pod).

---

## 0) Chuẩn bị biến môi trường (local)

Bạn cần:
- `PROJECT_ID`: GCP project id
- `REGION`: ví dụ `us-central1`
- `NAMESPACE`: namespace k8s, ví dụ `packamal`

Ví dụ:

```bash
export PROJECT_ID="k8s-packamal"
export REGION="us-central1"
export NAMESPACE="packamal-dv"
```

---

## 1) Tạo GCS bucket(s)

### 1.1 Chọn cách dùng bucket

Bạn có thể dùng **1 bucket chung** với các prefix:
- `static/`
- `media/`
- `dynamic-results/`
- `report-artifacts/`

Hoặc tách ra nhiều bucket. Repo hiện đang cấu hình theo hướng **1 bucket chung**.

### 1.2 Tạo bucket

Ví dụ tạo bucket tên `packamal-${PROJECT_ID}`:

```bash
export BUCKET="packamal-${PROJECT_ID}"
gcloud storage buckets create "gs://${BUCKET}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --uniform-bucket-level-access
```

### 1.3 Khuyến nghị bật versioning + lifecycle

```bash
gcloud storage buckets update "gs://${BUCKET}" --versioning
```

Lifecycle (ví dụ xoá object cũ sau 30 ngày, tuỳ nhu cầu):

```bash
cat > lifecycle.json << 'EOF'
{
  "rule": [
    { "action": { "type": "Delete" }, "condition": { "age": 30 } }
  ]
}
EOF
gcloud storage buckets update "gs://${BUCKET}" --lifecycle-file=lifecycle.json
```

---

## 2) Cấp quyền cho Workload Identity (bắt buộc)

Repo dùng:
- **KSA (Kubernetes ServiceAccount)**: `backend-serviceaccount`
- **GSA (Google Service Account)**: `packamal-gke@${PROJECT_ID}.iam.gserviceaccount.com`

Bạn có thể xem mapping trong:
- `prd/gke/04-kubernetes-manifests/11-rbac.yaml`

### 2.1 Tạo GSA (nếu chưa có)

```bash
gcloud iam service-accounts create "packamal-gke" \
  --project="${PROJECT_ID}" \
  --display-name="PackaMal GKE Workload Identity"
```

### 2.2 Cho phép KSA impersonate GSA

```bash
gcloud iam service-accounts add-iam-policy-binding \
  "packamal-gke@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="${PROJECT_ID}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:${PROJECT_ID}.svc.id.goog[${NAMESPACE}/backend-serviceaccount]"
```

### 2.3 Cấp quyền ghi/đọc GCS cho GSA

Tối thiểu để upload object: `roles/storage.objectCreator`.
Nếu cần overwrite/delete object: `roles/storage.objectAdmin`.

Khuyến nghị nhanh (dev/test):

```bash
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:packamal-gke@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

> Prod: bạn có thể giảm quyền xuống `objectCreator` + `objectViewer` tuỳ use-case.

---

## 3) Cấu hình YAML trong repo để dùng GCS

### 3.1 Cập nhật ConfigMap `packamal-config`

Sửa file:
- `prd/gke/04-kubernetes-manifests/base/01-config.yaml`

Các biến quan trọng:
- `GCS_BUCKET_NAME`: bucket cho Django static/media
- `RESULTS_BUCKET_URL`: base prefix cho backend đọc raw dynamic results
- `ANALYSIS_DYNAMIC_BUCKET_URL`: base prefix cho Go worker upload raw dynamic results
- `REPORT_ARTIFACTS_BUCKET_URL`: nơi backend lưu report payload (optional)

Ví dụ cấu hình (đã có trong repo):

```yaml
GCS_BUCKET_NAME: "packamal-${PROJECT_ID}"
GCS_STATIC_LOCATION: "static"
GCS_MEDIA_LOCATION: "media"

RESULTS_BUCKET_URL: "gs://packamal-${PROJECT_ID}/dynamic-results/"
ANALYSIS_DYNAMIC_BUCKET_URL: "gs://packamal-${PROJECT_ID}/dynamic-results/"
REPORT_ARTIFACTS_BUCKET_URL: "gs://packamal-${PROJECT_ID}/report-artifacts/"

ANALYSIS_RESULTS_VOLUME_MODE: "gcs"
```

> Lưu ý: repo cũng có `prd/gke/processed-k8s/...` là bản đã “render”. Nếu bạn đang apply bằng `apply-gke.sh` thì nó dùng `processed-k8s`. Bạn cần đảm bảo `processed-k8s/base/01-config.yaml` cũng khớp, hoặc regenerate processed manifests theo pipeline của bạn.

### 3.2 Đảm bảo backend/worker pods dùng đúng KSA

Backend deployment:
- `prd/gke/04-kubernetes-manifests/apps/05-backend.yaml` có `serviceAccountName: backend-serviceaccount`

Go heavy worker job (tạo từ backend code):
- Backend tạo job với `service_account_name="backend-serviceaccount"` trong `backend/package_analysis/services/k8s_service.py`

---

## 4) Cách hoạt động sau khi setup

### 4.1 Django static/media (GCS)

- Khi pod backend start, initContainer chạy:
  - `python manage.py collectstatic --noinput`
- Vì `GCS_BUCKET_NAME` đã set, Django dùng `django-storages` để upload static lên:
  - `gs://<bucket>/static/...`
- `STATIC_URL`/`MEDIA_URL` được set về:
  - `https://storage.googleapis.com/<bucket>/static/`
  - `https://storage.googleapis.com/<bucket>/media/`

Frontend **không mount PVC** để serve static/media nữa; browser sẽ tải trực tiếp từ GCS URL (hoặc Cloud CDN nếu bạn gắn custom domain).

### 4.2 Dynamic analysis results (Go heavy worker → GCS → backend)

- Backend tạo K8s job cho worker và truyền:
  - `-dynamic-bucket gs://<bucket>/dynamic-results/`
  - env `TASK_ID=<task_id>`
- Worker upload kết quả về object:
  - `gs://<bucket>/dynamic-results/<task_id>/report.json`
- Worker callback `/done/` về backend.
- Backend đọc lại JSON từ GCS bằng `RESULTS_BUCKET_URL` + `task_id`.
- Backend generate report và lưu DB (và optional lưu artifact report lên `REPORT_ARTIFACTS_BUCKET_URL`).

---

## 5) Deploy / Apply manifests

Nếu bạn apply bản processed:

```bash
cd /home/packamal
./prd/gke/apply-gke.sh
```

---

## 6) Verify nhanh sau khi deploy

### 6.1 Check env trên pod backend

```bash
kubectl -n "${NAMESPACE}" exec deploy/backend -- printenv | egrep 'GCS_BUCKET_NAME|RESULTS_BUCKET_URL|ANALYSIS_DYNAMIC_BUCKET_URL|REPORT_ARTIFACTS_BUCKET_URL'
```

### 6.2 Check object đã được upload lên GCS

Sau khi chạy 1 analysis task, kiểm tra:

```bash
gcloud storage ls "gs://${BUCKET}/dynamic-results/"
```

Bạn sẽ thấy folder `<task_id>/report.json`.

### 6.3 Test quyền GCS của Workload Identity (khuyến nghị)

Chạy 1 pod debug dùng `backend-serviceaccount` rồi thử upload object. (Bạn cần một image có `gcloud` hoặc `gsutil`.)

Ý tưởng:
- Nếu upload ok → worker cũng ok (vì dùng cùng KSA/GSA).

---

## 7) Các lỗi thường gặp

- **403 AccessDenied** khi worker upload:
  - Thiếu IAM role trên bucket cho GSA hoặc thiếu binding `workloadIdentityUser`.
- **Backend callback thành công nhưng “No results found”**:
  - `RESULTS_BUCKET_URL` và `ANALYSIS_DYNAMIC_BUCKET_URL` không khớp prefix.
  - Worker ghi path khác contract (phải là `<task_id>/report.json`).
- **Static/media không load**:
  - Bucket chưa public (nếu bạn đang dùng `storage.googleapis.com` trực tiếp).
  - Hoặc bạn cần Cloud CDN + signed URL tuỳ yêu cầu security.

