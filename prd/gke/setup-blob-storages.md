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

> **Lưu ý quan trọng khi bạn đổi namespace liên tục (testing):**
> - Workload Identity binding **có chứa namespace** (ví dụ `...svc.id.goog[${NAMESPACE}/backend-serviceaccount]`).
> - Nghĩa là: **mỗi namespace mới** bạn dùng, bạn phải **bind thêm** quyền impersonate cho namespace đó (hoặc dùng chung 1 namespace ổn định).

Ví dụ:

```bash
export PROJECT_ID="k8s-packamal"
export REGION="us-central1"
export NAMESPACE="packamal"
```

Mẹo khi test nhiều namespace:

```bash
# Ví dụ đổi namespace nhanh
export NAMESPACE="packamal-dev-1"
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

#### Nếu bạn đổi namespace thường xuyên (testing)

Bạn có 2 cách:

- **Cách A (khuyến nghị cho test nhanh): dùng 1 GSA cho nhiều namespace**
  - Mỗi namespace mới, bạn chạy lại lệnh ở trên với `NAMESPACE` mới.
  - GSA sẽ có nhiều dòng binding, mỗi dòng tương ứng 1 namespace.

Ví dụ bind thêm cho namespace `packamal-dev-2`:

```bash
gcloud iam service-accounts add-iam-policy-binding \
  "packamal-gke@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="${PROJECT_ID}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:${PROJECT_ID}.svc.id.goog[packamal-dev-2/backend-serviceaccount]"
```

- **Cách B: mỗi namespace dùng 1 GSA riêng**
  - Sạch policy hơn, nhưng tốn công tạo/quan lý nhiều service account.

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

**Quan trọng (Workload Identity vs Signed URL):**

- Với Workload Identity, credentials trong pod thường là dạng token-only (`google.auth.compute_engine.credentials.Credentials`) **không có private key**.
- Vì vậy, nếu storage backend cố tạo **signed URL** cho static/media thì sẽ lỗi kiểu: `AttributeError: you need a private key to sign credentials`.
- Repo đã cấu hình storage backend để **tắt signed URL** (`querystring_auth = False`), và bạn nên serve static/media theo kiểu **public URL hoặc Cloud CDN**.

Frontend **không mount PVC** để serve static/media nữa; browser sẽ tải trực tiếp từ GCS URL (hoặc Cloud CDN nếu bạn gắn custom domain).

#### Nếu browser không load được static (403 Forbidden)

Triệu chứng thường gặp:
- Trang HTML render được nhưng CSS/JS/Image không hiện.
- Network tab thấy request tới `https://storage.googleapis.com/<bucket>/static/...` trả **403**.

Kiểm tra nhanh:

```bash
curl -I "https://storage.googleapis.com/${BUCKET}/static/css/homepage.css"
```

Nếu ra `HTTP/2 403` ⇒ bucket đang **không cho public read**.

**Lưu ý quan trọng:** GCS hiện **không cho IAM Conditions với `allUsers`** (public principal). Vì vậy kiểu “public chỉ theo prefix `static/` bằng condition” có thể bị chặn bởi policy lint.

Bạn có 2 lựa chọn:

**Option A (nhanh nhất cho testing): public READ cho toàn bộ bucket**

```bash
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="allUsers" \
  --role="roles/storage.objectViewer"
```

**Option B (khuyến nghị thực tế): tách bucket STATIC riêng và public toàn bộ bucket static**

- Tạo bucket static riêng, ví dụ:

```bash
export STATIC_BUCKET="packamal-static-${PROJECT_ID}"
gcloud storage buckets create "gs://${STATIC_BUCKET}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --uniform-bucket-level-access
```

- Public read toàn bộ bucket static:

```bash
gcloud storage buckets add-iam-policy-binding "gs://${STATIC_BUCKET}" \
  --member="allUsers" \
  --role="roles/storage.objectViewer"
```

- Set env để backend dùng bucket static riêng:
  - `GCS_STATIC_BUCKET_NAME=${STATIC_BUCKET}`
  - (tuỳ chọn) `GCS_MEDIA_BUCKET_NAME` cho media nếu bạn muốn tách.

> Lưu ý: đây là public read. Production chuẩn thường dùng **Cloud CDN + custom domain** để cache và kiểm soát tốt hơn.

##### Nếu bị chặn bởi Public Access Prevention

Một số bucket bị bật `Public Access Prevention = enforced` sẽ không cho public.

Kiểm tra:

```bash
gcloud storage buckets describe "gs://${BUCKET}" --format="value(iamConfiguration.publicAccessPrevention)"
```

Nếu kết quả là `enforced` thì để test public static bạn có thể tắt:

```bash
gcloud storage buckets update "gs://${BUCKET}" --public-access-prevention=unspecified
```

Sau đó chạy lại lệnh public binding ở trên và verify lại bằng `curl -I`.

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
# Quan trọng: export đúng NAMESPACE bạn đang test trước khi apply
# (apply-gke.sh dùng biến môi trường NAMESPACE ở bước kubectl wait)
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

> NOTE (nếu bạn từng chạy bản worker cũ):
> - Nếu thấy object dạng `gs://<bucket>//dynamic-results/<task_id>/report.json` (double slash) thì đó là do **worker upload key có leading “/”**.
> - Bản worker mới đã normalize prefix để luôn ra chuẩn: `gs://<bucket>/dynamic-results/<task_id>/report.json`.
> - Backend hiện đọc được cả 2 dạng để backward-compatible, nhưng nên migrate object về path chuẩn để dễ quản trị.

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
  - Bucket/prefix `static/` chưa public (sẽ thấy `403` từ `storage.googleapis.com`).
  - Bucket đang bật `Public Access Prevention = enforced`.
  - (Prod) Cân nhắc Cloud CDN + custom domain thay vì public bucket trực tiếp.

