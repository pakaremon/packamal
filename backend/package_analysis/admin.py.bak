from django.contrib import admin
from .models import Package, ReportDynamicAnalysis, APIKey, AnalysisTask
# Register your models here.

class PackageAdmin(admin.ModelAdmin):
    list_display = ('package_name', 'package_version', 'ecosystem')

# class ReportDynamicAnalysisAdmin(admin.ModelAdmin):
#     list_display = ('package', 'report')

class APIKeyAdmin(admin.ModelAdmin):
    list_display = ('name', 'key', 'is_active', 'rate_limit_per_hour', 'created_at', 'last_used')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'key')
    readonly_fields = ('key', 'created_at', 'last_used')

class AnalysisTaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'purl', 'status', 'ecosystem', 'package_name', 'package_version', 'api_key', 'created_at', 'completed_at', 'has_report')
    list_filter = ('status', 'ecosystem', 'created_at', 'completed_at')
    search_fields = ('purl', 'package_name', 'package_version', 'api_key__name', 'job_id')
    readonly_fields = ('id', 'created_at', 'started_at', 'completed_at', 'error_details_preview')
    exclude = ('error_details',)  # Exclude large JSONField from direct display
    list_per_page = 50  # Limit items per page to improve performance
    ordering = ('-created_at',)  # Order by most recent first
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'purl', 'package_name', 'package_version', 'ecosystem', 'status', 'api_key')
        }),
        ('Timing', {
            'fields': ('created_at', 'started_at', 'completed_at', 'timeout_minutes', 'last_heartbeat')
        }),
        ('Job Management', {
            'fields': ('priority', 'job_id', 'container_id')
        }),
        ('Results', {
            # Removed 'report' field to prevent loading huge 37MB+ JSONField (system_calls array)
            # The report relationship exists but is not displayed to avoid memory issues
            # Use has_report column in list view or download_url to access report data
            'fields': ('download_url',)
        }),
        ('Error Information', {
            'fields': ('error_message', 'error_category', 'error_details_preview'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        """Optimize queryset with select_related and defer large fields to prevent timeout."""
        qs = super().get_queryset(request)
        # Always select_related on lightweight api_key
        qs = qs.select_related('api_key')
        
        # Always defer error_details to prevent loading huge JSONField into memory
        # It will be loaded on-demand when error_details_preview accesses it
        # This prevents loading the entire JSONField for all objects in list view
        qs = qs.defer('error_details')
        
        # Note: We intentionally avoid select_related('report', 'report__package') 
        # because report.report is a huge JSONField that can cause memory issues.
        # The OneToOneField relationship will load the report lazily when accessed,
        # which is acceptable for individual change views but avoids eager loading
        # the huge JSONField for all tasks in list views.
        return qs
    
    def error_details_preview(self, obj):
        """Show a preview of error_details instead of full JSON to prevent timeout."""
        # Check if error_details exists without loading it if deferred
        # Accessing obj.error_details will trigger DB query if deferred, but only once
        try:
            # Use hasattr to check if attribute exists without triggering query
            # But Django's deferred fields still need to be accessed
            error_details = obj.error_details if hasattr(obj, 'error_details') else None
            if not error_details:
                return "No error details"
            
            import json
            error_str = json.dumps(error_details, indent=2)
            # Limit to first 1000 characters to prevent rendering huge JSON fields
            # This limits display, but the full JSON is still loaded into memory temporarily
            # To truly optimize, we'd need to use database-level substring, but this helps
            if len(error_str) > 1000:
                return f"{error_str[:1000]}...\n\n[Truncated - Full error details available in database]"
            return error_str
        except (TypeError, ValueError) as e:
            return f"Error displaying details: {str(e)}"
        except Exception as e:
            # Handle case where field might be deferred and causes issues
            return f"Error loading details: {str(e)}"
    
    error_details_preview.short_description = 'Error Details (Preview)'
    
    def has_report(self, obj):
        """Display whether task has a report without loading the huge JSONField."""
        # Returns boolean so Django admin can render checkmark/cross icons
        return bool(obj.report_id)
    has_report.short_description = 'Has Report'
    has_report.boolean = True

admin.site.register(Package, PackageAdmin)
# admin.site.register(ReportDynamicAnalysis, ReportDynamicAnalysisAdmin)
admin.site.register(APIKey, APIKeyAdmin)
admin.site.register(AnalysisTask, AnalysisTaskAdmin)

