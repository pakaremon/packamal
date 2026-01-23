from django.db import models
import secrets
import string

# 1. Package: Giữ nguyên định danh gói
class Package(models.Model):
    package_name = models.CharField(max_length=200)
    package_version = models.CharField(max_length=100)
    ecosystem = models.CharField(max_length=50)

    class Meta:
        unique_together = ('package_name', 'package_version', 'ecosystem')

    def __str__(self):
        return f"{self.ecosystem}/{self.package_name}@{self.package_version}"


# 3. API Key: Giữ nguyên để xác thực
class APIKey(models.Model):
    name = models.CharField(max_length=100)
    key = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def save(self, *args, **kwargs):
        if not self.key:
            alphabet = string.ascii_letters + string.digits
            self.key = ''.join(secrets.choice(alphabet) for _ in range(64))
        super().save(*args, **kwargs)

# 4. AnalysisTask: Đã dọn dẹp sạch sẽ
class AnalysisTask(models.Model):
    STATUS_CHOICES = [
        ('queued', 'Queued'),         # Đã nhận, chờ K8s Job
        ('processing', 'Processing'), # Job đang chạy
        ('completed', 'Completed'),   # Xong, đã có artifacts link
        ('failed', 'Failed'),         # Lỗi code/hệ thống
        ('timeout', 'Timeout'),       # K8s kill do quá giờ
    ]

    # Định danh Task
    id = models.AutoField(primary_key=True)
    api_key = models.ForeignKey(APIKey, on_delete=models.CASCADE, related_name='tasks')
    purl = models.CharField(max_length=500, db_index=True)
    
    # Trạng thái & K8s Tracking (Chỉ giữ lại cái cần thiết nhất)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued', db_index=True)
    job_id = models.CharField(max_length=100, blank=True, null=True, db_index=True, help_text="K8s Job Name")
    
    report_blob_url = models.URLField(blank=True, null=True)
    
    # Metadata thời gian & Lỗi
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Task {self.id}: {self.purl} ({self.status})"

    class Meta:
        ordering = ['-created_at']
