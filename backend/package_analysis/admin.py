from django.contrib import admin
from django.utils.html import format_html
from django.template.defaultfilters import truncatechars
from .models import Package, APIKey, AnalysisTask

# ==========================================
# 1. API KEY ADMIN
# ==========================================
@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ('name', 'key_masked', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)
    
    def get_readonly_fields(self, request, obj=None):
        return ['key', 'created_at'] if obj else []

    def key_masked(self, obj):
        return f"{obj.key[:8]}..." if obj.key else "-"
    key_masked.short_description = "API Key Prefix"

# ==========================================
# 2. PACKAGE ADMIN
# ==========================================
@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ('id', 'ecosystem', 'package_name', 'package_version')
    list_filter = ('ecosystem',)
    search_fields = ('package_name', 'package_version')

# ==========================================
# 3. ANALYSIS TASK ADMIN (Tối giản nhất)
# ==========================================
@admin.register(AnalysisTask)
class AnalysisTaskAdmin(admin.ModelAdmin):
    # Chỉ giữ lại các cột thực sự quan trọng ở trang danh sách
    list_display = ('id', 'purl_preview', 'status_badge', 'download_report', 'duration', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('purl', 'job_id', 'error_message')
    
    readonly_fields = ('created_at', 'completed_at', 'job_id', 'error_log_viewer')

    fieldsets = (
        ('Basic Info', {
            'fields': ('api_key', 'purl', 'status')
        }),
        ('Result', {
            'fields': ('report_blob_url',)
        }),
        ('K8s Debugging', {
            'fields': ('job_id', 'created_at', 'completed_at', 'error_log_viewer'),
            'classes': ('collapse',) # Thu gọn phần này lại cho đỡ rối
        }),
    )

    def purl_preview(self, obj):
        return truncatechars(obj.purl, 40)
    purl_preview.short_description = "PURL"

    # Hiển thị nút tải file trực tiếp nếu có URL
    def download_report(self, obj):
        if obj.report_blob_url:
            return format_html(
                '<a href="{}" target="_blank" style="background: #2563eb; color: white; padding: 4px 10px; border-radius: 4px; text-decoration: none; font-weight: bold; font-size: 10px;">⬇ DOWNLOAD</a>',
                obj.report_blob_url
            )
        return format_html('<span style="color: #9ca3af;">No Report</span>')
    download_report.short_description = "Report"

    def status_badge(self, obj):
        colors = {
            'completed': ('#dcfce7', '#166534'), # Green
            'failed': ('#fee2e2', '#991b1b'),    # Red
            'processing': ('#dbeafe', '#1e40af'), # Blue
            'queued': ('#fef9c3', '#854d0e'),     # Yellow
            'timeout': ('#f3e8ff', '#6b21a8'),    # Purple
        }
        bg, text = colors.get(obj.status, ('#f3f4f6', '#374151'))
        return format_html(
            '<span style="background: {}; color: {}; padding: 4px 12px; border-radius: 20px; font-weight: bold; font-size: 10px;">{}</span>',
            bg, text, obj.get_status_display().upper()
        )
    status_badge.short_description = "Status"

    def duration(self, obj):
        if obj.completed_at and obj.created_at:
            diff = obj.completed_at - obj.created_at
            return f"{int(diff.total_seconds())}s"
        return "-"

    def error_log_viewer(self, obj):
        if not obj.error_message:
            return "No errors."
        return format_html(
            '<pre style="background: #1a1a1a; color: #f87171; padding: 10px; border-radius: 4px; font-size: 11px; max-height: 200px; overflow: auto;">{}</pre>',
            obj.error_message
        )
    error_log_viewer.short_description = "Error Log"