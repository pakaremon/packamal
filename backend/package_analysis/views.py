from django.shortcuts import render
from django.http import HttpResponse, JsonResponse, HttpResponseNotFound
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.urls import reverse
from django.core.files.storage import FileSystemStorage
from django.db import transaction
import json
import logging
import traceback
import os
import subprocess

from .forms import PackageSubmitForm
from .helper import Helper
from .report_generator import Report
from .models import AnalysisTask, Package
from .src.py2src.py2src.url_finder import URLFinder
from .utils import PURLParser, validate_purl_format
from .api_utils import json_success, json_error, api_handler
from .auth import require_api_key, require_internal_api_token
from .services.task_service import TaskService
from .services.package_version_service import PackageVersionService
from .services.result_storage_service import ResultStorageService
from .services.report_artifact_storage_service import ReportArtifactStorageService
from .view_constants import (
    STATUS_QUEUED,
    STATUS_PROCESSING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
    HTTP_STATUS_BAD_REQUEST,
    HTTP_STATUS_NOT_FOUND,
    HTTP_STATUS_METHOD_NOT_ALLOWED,
    HTTP_STATUS_INTERNAL_SERVER_ERROR,
    HTTP_STATUS_CREATED,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    DEFAULT_PAGE_NUMBER,
    ERROR_CATEGORY_RESULTS_NOT_FOUND,
    ERROR_CATEGORY_QUEUE_ERROR,
    ERROR_CATEGORY_CALLBACK_ERROR,
    DEFAULT_RESULTS_VOLUME,
    DEFAULT_MOUNT_PATH,
    CELERY_QUEUE_ANALYSIS,
    ECOSYSTEM_PYPI,
    JSON_FILE_EXTENSION,
    ACTIVE_TASK_WINDOW_HOURS,
    RACE_CONDITION_CHECK_MINUTES,
)

logger = logging.getLogger(__name__)


# Legacy functions removed - reports are now served via GCS URLs in artifacts field


# Legacy result reading functions removed - results are now served via GCS URLs

def _extract_form_data(form):
    """Extract package information from validated form."""
    return (
        form.cleaned_data['package_name'],
        form.cleaned_data['package_version'],
        form.cleaned_data['ecosystem']
    )


def _handle_form_post(request, template_name, analysis_function, response_key):
    """Handle POST request with form validation and analysis execution."""
    if request.method != 'POST':
        form = PackageSubmitForm()
        return render(request, template_name, {'form': form})
    
    form = PackageSubmitForm(request.POST)
    if not form.is_valid():
        form = PackageSubmitForm()
        return render(request, template_name, {'form': form})
    
    package_name, package_version, ecosystem = _extract_form_data(form)
    results = analysis_function(package_name, package_version, ecosystem)
    return JsonResponse({response_key: results})


def dashboard(request):
    form = PackageSubmitForm()
    return render(request, 'package_analysis/dashboard.html', {'form': form})


def contact(request):
    return render(request, 'package_analysis/homepage/contact.html')


def homepage(request):
    return render(request, 'package_analysis/homepage/homepage.html')




def _queue_celery_task(task):
    """Queue task via Celery."""
    from .tasks import run_dynamic_analysis
    return run_dynamic_analysis.apply_async(
        args=[task.id],
        queue=CELERY_QUEUE_ANALYSIS
    )


def dynamic_analysis(request):
    """
    Dynamic analysis endpoint - Legacy UI endpoint.
    Note: Please use the analyze_api endpoint for programmatic access.
    """
    if request.method != 'POST':
        form = PackageSubmitForm()
        return render(request, 'package_analysis/analysis/dynamic_analysis.html', {'form': form})
    
    return JsonResponse({
        "status": "error",
        "error": "Please use the /api/analyze endpoint with PURL format"
    }, status=HTTP_STATUS_BAD_REQUEST) 

def malcontent(request):
    """Run malcontent analysis."""
    return _handle_form_post(
        request,
        'package_analysis/analysis/malcontent.html',
        Helper.run_malcontent,
        "malcontent_report"
    )


def lastpymile(request):
    """Run lastpymile analysis."""
    return _handle_form_post(
        request,
        'package_analysis/analysis/lastpymile.html',
        Helper.run_lastpymile,
        "lastpymile_report"
    )


def bandit4mal(request):
    """Run bandit4mal analysis."""
    return _handle_form_post(
        request,
        'package_analysis/analysis/bandit4mal.html',
        Helper.run_bandit4mal,
        "bandit4mal_report"
    )


def find_typosquatting(request):
    """Find typosquatting candidates."""
    return _handle_form_post(
        request,
        'package_analysis/analysis/typosquatting.html',
        Helper.run_oss_squats,
        "typosquatting_candidates"
    )

def task_status(request, task_id):
    """
    Legacy UI endpoint to check task status.
    Note: Please use /api/tasks/<task_id> for programmatic access.
    """
    try:
        task = AnalysisTask.objects.get(id=task_id)
        
        response_data = {
            'task_id': task.id,
            'status': task.status,
            'purl': task.purl,
            'created_at': task.created_at.isoformat() if task.created_at else None,
        }
        
        if task.completed_at:
            response_data['completed_at'] = task.completed_at.isoformat()
        
        if task.status == STATUS_COMPLETED and task.report_blob_url:
            response_data['report_blob_url'] = task.report_blob_url
        
        if task.status == STATUS_FAILED:
            response_data['error_message'] = task.error_message if task.error_message else 'Unknown error'
        
        return JsonResponse(response_data)
        
    except AnalysisTask.DoesNotExist:
        return JsonResponse({
            'error': 'Task not found',
            'task_id': task_id
        }, status=HTTP_STATUS_NOT_FOUND)


def _find_source_urls_for_pypi(package_name, package_version, ecosystem):
    """Find source URLs for PyPI packages."""
    return Helper.run_py2src(package_name, package_version, ecosystem)


def _find_source_urls_for_other_ecosystems(package_name, package_version, ecosystem):
    """Find source URLs for non-PyPI packages."""
    urls = Helper.run_oss_find_source(package_name, package_version, ecosystem)
    sources = []
    for url in urls:
        if url and URLFinder.test_url_working(URLFinder.normalize_url(url)):
            sources.append(URLFinder.real_github_url(url))
    return list(set(sources))


def find_source_code(request):
    """Find source code URLs for a package."""
    if request.method != 'POST':
        form = PackageSubmitForm()
        return render(request, 'package_analysis/analysis/findsource.html', {'form': form})
    
    form = PackageSubmitForm(request.POST)
    if not form.is_valid():
        form = PackageSubmitForm()
        return render(request, 'package_analysis/analysis/findsource.html', {'form': form})
    
    package_name, package_version, ecosystem = _extract_form_data(form)
    
    if ecosystem == ECOSYSTEM_PYPI:
        sources = _find_source_urls_for_pypi(package_name, package_version, ecosystem)
    else:
        sources = _find_source_urls_for_other_ecosystems(package_name, package_version, ecosystem)
    
    return JsonResponse({'source_urls': sources})


def upload_sample(request):
    """Upload and analyze a sample file."""
    if request.method != 'POST' or 'file' not in request.FILES:
        return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=HTTP_STATUS_BAD_REQUEST)
    
    file = request.FILES['file']
    # Always use a local temp directory for uploaded samples so this works even when MEDIA is on GCS.
    upload_tmp_dir = os.environ.get("UPLOAD_TMP_DIR", "/tmp/uploads")
    fs = FileSystemStorage(location=upload_tmp_dir)
    filename = fs.save(file.name, file)
    uploaded_file_path = fs.path(filename)
    
    try:
        ecosystem = request.POST.get('ecosystem')
        package_name = request.POST.get('package_name')
        package_version = request.POST.get('package_version')
        
        reports = Helper.handle_uploaded_file(uploaded_file_path, package_name, package_version, ecosystem)
        return JsonResponse({"dynamic_analysis_report": reports})
    finally:
        fs.delete(filename)


def submit_sample(request):
    """
    Submit sample for analysis - Legacy UI endpoint.
    Note: Please use the /api/analyze endpoint for programmatic access.
    """
    if request.method == 'POST':
        return JsonResponse({
            "status": "error",
            "error": "Please use the /api/analyze endpoint with PURL format"
        }, status=HTTP_STATUS_BAD_REQUEST)
    
    form = PackageSubmitForm()
    return render(request, 'package_analysis/dashboard.html', {'form': form})


# def report_detail(request, report_id):
#     '''Report detail analysis result of the package'''
#     report = ReportDynamicAnalysis.objects.get(pk=report_id)
#     return render(request, 'package_analysis/report_detail.html', {'report': report})

# def get_all_report(request):
#     """Get all analysis reports."""
#     reports = ReportDynamicAnalysis.objects.all()
#     results = {
#         report.id: {
#             'id': report.id,
#             'package_name': report.package.package_name,
#             'package_version': report.package.package_version,
#             'ecosystem': report.package.ecosystem,
#             'verdict': report.verdict,
#             'score': report.score,
#             'created_at': report.created_at.isoformat() if report.created_at else None,
#         }
#         for report in reports
#     }
#     return JsonResponse(results)

# def get_report(request, report_id):
#     report = ReportDynamicAnalysis.objects.get(pk=report_id)
#     results = {
#         'package_name': report.package.package_name,
#         'package_version': report.package.package_version,
#         'ecosystem': report.package.ecosystem,
#         'verdict': report.verdict,
#         'score': report.score,
#         'artifacts': report.artifacts,
#         'bucket_path': report.bucket_path,
#         'created_at': report.created_at.isoformat() if report.created_at else None,
#     }
#     return JsonResponse(results)

def analyzed_samples(request):
    '''List of analyzed samples, sorted by id'''

    packages = Package.objects.all().order_by('-id')

    return render(request, 'package_analysis/analyzed_samples.html', {'packages': packages})

def get_wolfi_packages(request):
    """Get list of Wolfi packages."""
    return JsonResponse(Helper.get_wolfi_packages())


def get_maven_packages(request):
    """Get list of Maven packages."""
    return JsonResponse(Helper.get_maven_packages())


def get_rust_packages(request):
    """Get list of Rust packages."""
    return JsonResponse(Helper.get_rust_packages())


def get_pypi_packages(request):
    """Get list of PyPI packages."""
    return JsonResponse(Helper.get_pypi_packages())


def get_npm_packages(request):
    """Get list of npm packages."""
    return JsonResponse(Helper.get_npm_packages())


def get_packagist_packages(request):
    """Get list of Packagist packages."""
    return JsonResponse(Helper.get_packagist_packages())


def get_rubygems_packages(request):
    """Get list of RubyGems packages."""
    return JsonResponse(Helper.get_rubygems_packages())

def _validate_package_name(request):
    """Validate package name from request."""
    package_name = request.GET.get('package_name')
    if not package_name:
        return None, JsonResponse({'error': 'Package name is required'}, status=HTTP_STATUS_BAD_REQUEST)
    return package_name, None


def get_rubygems_versions(request):
    """Get versions for a RubyGems package."""
    package_name, error_response = _validate_package_name(request)
    if error_response:
        return error_response
    versions = PackageVersionService.get_rubygems_versions(package_name)
    return JsonResponse({"versions": versions})


def get_packagist_versions(request):
    """Get versions for a Packagist package."""
    package_name, error_response = _validate_package_name(request)
    if error_response:
        return error_response
    versions = PackageVersionService.get_packagist_versions(package_name)
    return JsonResponse({"versions": versions})


def get_npm_versions(request):
    """Get versions for an npm package."""
    package_name, error_response = _validate_package_name(request)
    if error_response:
        return error_response
    versions = PackageVersionService.get_npm_versions(package_name)
    return JsonResponse({"versions": versions})


def get_pypi_versions(request):
    """Get versions for a PyPI package."""
    package_name, error_response = _validate_package_name(request)
    if error_response:
        return error_response
    versions = PackageVersionService.get_pypi_versions(package_name)
    return JsonResponse({"versions": versions})


# Legacy function removed - reports are now served via GCS URLs in artifacts field


# Legacy PURL parsing function removed - logic moved inline to analyze_api



def _build_active_task_response(active_task, request):
    """Build response for active task."""
    status_url = request.build_absolute_uri(reverse('task_status_api', args=[active_task.id]))
    
    return json_success(request, {
        'task_id': active_task.id,
        'status': active_task.status,
        'status_url': status_url,
        'message': f'Analysis already {active_task.status}'
    })


def _find_completed_task_for_purl(purl):
    """Find a completed task for the given PURL."""
    return AnalysisTask.objects.filter(
        purl=purl,
        status=STATUS_COMPLETED,
    ).order_by('-completed_at').first()





# Legacy PURL extraction function removed - logic moved inline to analyze_api




@csrf_exempt
@require_api_key
@api_handler
def analyze_api(request):
    """
    API endpoint to analyze packages via PURL
    Accepts POST requests with PURL in JSON body
    Returns analysis task ID and result URL
    Uses queue system to ensure only one container runs at a time
    """
    if request.method != 'POST':
        return json_error(request, error='Method not allowed', message='Only POST requests are supported', status=HTTP_STATUS_METHOD_NOT_ALLOWED)
    
    try:
        data = json.loads(request.body)
        purl = data.get('purl')
        
        if not purl:
            return json_error(request, error='Missing PURL', message='PURL parameter is required', status=HTTP_STATUS_BAD_REQUEST)
        
        if not validate_purl_format(purl):
            return json_error(request, error='Invalid PURL format', message='PURL must be a valid package URL starting with pkg:', status=HTTP_STATUS_BAD_REQUEST)
        
        completed_task = AnalysisTask.objects.filter(
            purl=purl,
            status=STATUS_COMPLETED,
        ).order_by('-completed_at').first()
        
        
        if completed_task:
            logger.debug(f"Found completed task {completed_task.id} for PURL: {purl}")
            status_url = request.build_absolute_uri(reverse('task_status_api', args=[completed_task.id]))
            return JsonResponse({
                'task_id': completed_task.id,
                'status': STATUS_COMPLETED,
                'status_url': status_url,
                'message': 'Analysis already exists'
            })
        
        existing_active_tasks = AnalysisTask.objects.filter(
            purl=purl,
            status__in=[STATUS_PROCESSING, STATUS_QUEUED],
            created_at__gte=timezone.now() - timezone.timedelta(hours=ACTIVE_TASK_WINDOW_HOURS)
        ).order_by('-created_at')
        
        active_task = existing_active_tasks.first()
        if active_task:
            return _build_active_task_response(active_task, request)
        
        last_check = existing_active_tasks.filter(
            created_at__gte=timezone.now() - timezone.timedelta(minutes=RACE_CONDITION_CHECK_MINUTES)
        ).first()
        
        if last_check:
            return json_success(request, {
                'task_id': last_check.id,
                'status': last_check.status,
                'message': f'Analysis already {last_check.status} (race condition prevented)'
            })
        


        task = AnalysisTask.objects.create(
            api_key=request.api_key,
            purl=purl,
            status=STATUS_QUEUED,
        )
        
        logger.debug(f"Created new task {task.id} for PURL: {purl}")
        
        try:
            TaskService.queue_task(task)
            celery_task = _queue_celery_task(task)
            
            logger.info(f"Queued task {task.id} via Celery (Celery ID: {celery_task.id})")
            
            status_url = request.build_absolute_uri(reverse('task_status_api', args=[task.id]))

            return json_success(request, {
                'task_id': task.id,
                'status_url': status_url,
                'message': 'Analysis queued successfully'
            }, status=HTTP_STATUS_CREATED)
            
        except Exception as e:
            logger.error(f"Failed to queue analysis task {task.id}: {e}", exc_info=True)
            task.status = STATUS_FAILED
            task.error_message = str(e)
            task.error_category = ERROR_CATEGORY_QUEUE_ERROR
            task.completed_at = timezone.now()
            task.save()
            return json_error(request, error='Failed to queue analysis', message=str(e), status=HTTP_STATUS_INTERNAL_SERVER_ERROR)
    
    except Exception as e:
        return json_error(request, error='Internal server error', message=str(e), status=HTTP_STATUS_INTERNAL_SERVER_ERROR)


@csrf_exempt
@api_handler
def task_status_api(request, task_id):
    """
    API endpoint to check analysis task status.
    
    - If status != 'completed': Return status only
    - If status == 'completed': Return status AND artifacts (GCS URLs)
    """
    try:
        task = AnalysisTask.objects.get(id=task_id)

        response_data = {
            'task_id': task.id,
            'purl': task.purl,
            'status': task.status,
            'created_at': task.created_at.isoformat(),
        }
        
        if task.completed_at:
            response_data['completed_at'] = task.completed_at.isoformat()
        
        if task.error_message:
            response_data['error_message'] = task.error_message
        
        # If completed, return the artifacts (GCS URLs)
        if task.status == STATUS_COMPLETED and task.report_blob_url:
            response_data['report_blob_url'] = task.report_blob_url

        return json_success(request, response_data)
        
    except AnalysisTask.DoesNotExist:
        return json_error(request, error='Task not found', message='Analysis task not found or access denied', status=404)
   


def configure(request):
    return render(request, "package_analysis/configureSubmit.html")

def analyze(request):
    return render(request, "package_analysis/analyzing.html")

def results(request):
    return render(request, "package_analysis/reports.html")




@csrf_exempt
@require_api_key
@api_handler
def list_tasks_api(request):
    """
    Paginated list of analysis tasks for the caller's API key.
    Query params: page (default 1), page_size (default 20, max 100), status
    """
    if request.method != 'GET':
        return json_error(request, error='Method not allowed', message='Only GET requests are supported', status=405)

    try:
        page = int(request.GET.get('page', '1'))
        page_size = min(100, max(1, int(request.GET.get('page_size', '20'))))
    except ValueError:
        return json_error(request, error='Invalid pagination', message='page and page_size must be integers', status=400)

    status_filter = request.GET.get('status')
    qs = AnalysisTask.objects.filter(api_key=request.api_key).order_by('-created_at')
    if status_filter:
        qs = qs.filter(status=status_filter)

    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size
    items = [
        {
            'task_id': t.id,
            'purl': t.purl,
            'status': t.status,
            'created_at': t.created_at.isoformat(),
            'status_url': request.build_absolute_uri(reverse('task_status_api', args=[t.id])),
            'error_message': t.error_message if t.error_message else None,
        }
        for t in qs[start:end]
    ]

    return json_success(request, {
        'items': items,
        'page': page,
        'page_size': page_size,
        'total': total,
    })


def _extract_task_id_from_request(request):
    """Extract task_id from request body (JSON or form data)."""
    if request.content_type and 'application/json' in request.content_type:
        try:
            data = json.loads(request.body)
            return data.get('task_id')
        except (json.JSONDecodeError, ValueError):
            pass
    return request.POST.get('task_id')


# Legacy helper functions removed - results are now served via GCS URLs


@csrf_exempt
@require_internal_api_token
@api_handler
def job_completed_api(request):
    """
    API endpoint called by K8s worker when job completes.
    
    Supports multiple phases and formats:
    
    PHASE 1 (Current - Single File):
    {
        "task_id": "<id>",
        "status": "completed" or "failed",
        "reason": "balabala",
    }
    
    

    
    Backend automatically detects which phase based on file existence.
    """
    if request.method != 'POST':
        return json_error(
            request,
            error='Method not allowed',
            message='Only POST requests are supported',
            status=HTTP_STATUS_METHOD_NOT_ALLOWED
        )

    try:
        data = json.loads(request.body)
        task_id = data.get('task_id')
        
        if not task_id:
            return json_error(
                request,
                error='Missing task_id',
                message='task_id parameter is required',
                status=HTTP_STATUS_BAD_REQUEST
            )
    except json.JSONDecodeError:
        return json_error(
            request,
            error='Invalid JSON',
            message='Request body must be valid JSON',
            status=HTTP_STATUS_BAD_REQUEST
        )
    
    try:
        return _handle_job_completion(request, task_id)
    except AnalysisTask.DoesNotExist:
        return _handle_task_not_found(request, task_id)
    except Exception as error:
        return _handle_completion_error(request, task_id, error)


def _handle_job_completion(request, task_id: int):
    """Handles job completion with transaction and triggers."""
    with transaction.atomic():
        task = _lock_task_for_completion(task_id)

        # 1. Guard Clauses: Handle special cases early to avoid deep nesting
        if _should_skip_completion(task):
            return _create_skip_response(request, task)

        if _is_already_completed(task):
            _schedule_next_analysis()
            return _create_already_completed_response(request, task_id)

        # 2. Logic: Process the artifacts
        blob_url, bucket_path = _ensure_artifacts_available(task, task_id)
        
        if not blob_url:
            _mark_task_failed_on_error(task, "Artifacts not found")
            _cleanup_k8s_job_if_exists(task, task_id)
            _schedule_next_analysis()
            return _create_completion_error_response(
                request, task_id, FileNotFoundError("Analysis failed - no artifacts found in GCS")
            )

        # 3. Success Path: Clear and focused
        _make_completed_task(task, blob_url, bucket_path)
        _cleanup_k8s_job_if_exists(task, task_id)
        _schedule_next_analysis()
        
        return _create_success_response(request, task_id)

def _lock_task_for_completion(task_id: int):
    """Locks task row for atomic update."""
    return AnalysisTask.objects.select_for_update().get(id=task_id)


def _should_skip_completion(task: AnalysisTask) -> bool:
    """Checks if task completion should be skipped."""
    return task.status not in [STATUS_PROCESSING, STATUS_COMPLETED]


def _is_already_completed(task: AnalysisTask) -> bool:
    """Checks if task already completed with report."""
    return task.status == STATUS_COMPLETED and task.report_blob_url


def _create_skip_response(request, task: AnalysisTask):
    """Creates response for skipped completion."""
    logger.warning(f"Task {task.id} in status '{task.status}', skipping")
    return json_success(request, {
        'message': f'Task already in status: {task.status}',
        'task_id': task.id,
        'status': task.status
    })


def _create_already_completed_response(request, task_id: int):
    """Creates response for already completed task."""
    logger.info(f"Task {task_id} already completed with report")
    return json_success(request, {
        'message': 'Task already completed',
        'task_id': task_id,
        'status': STATUS_COMPLETED
    })


def _ensure_artifacts_available(task, task_id: int):
    return _construct_missing_artifacts_data(task, task_id)


def _construct_missing_artifacts_data(task, task_id: int):
    """
    Constructs missing artifacts URLs and bucket path.
    
    Phase 1: Simple path {task_id}/report.json
    Avoids URL encoding issues with package names.
    """
    from .services.gcs_artifacts_service import GCSArtifactsService
    
    gcs_service = GCSArtifactsService()
    
    blob_url = _construct_artifacts_urls(gcs_service, task_id)
    bucket_path = _construct_bucket_path(gcs_service, task_id)
    
    return blob_url, bucket_path


def _construct_artifacts_urls(gcs_service, task_id: int):
    """
    Constructs artifacts URL for Phase 1.
    
    Phase 1: Simple path {task_id}/report.json
    Worker uploads single file to avoid complexity.
    """
    if gcs_service.check_single_result_exists(task_id):
        logger.info(f"Task {task_id}: Found single result file at {task_id}/report.json")
        single_url = gcs_service.get_single_result_url(task_id)
        return single_url
    
    logger.warning(f"Task {task_id}: No artifacts found at {task_id}/report.json")
    return None


def _construct_bucket_path(gcs_service, task_id: int):
    """Constructs bucket path: {task_id}/"""
    return gcs_service.get_bucket_path(task_id)


def _make_completed_task(task: AnalysisTask, blob_url: str, bucket_path: str):
    """Creates report and marks task as completed."""

    task.report_blob_url = blob_url
    
    task.status = STATUS_COMPLETED
    task.completed_at = timezone.now()
    task.save()
    
    logger.info(f"Task {task.id} completed successfully via worker callback")
    return task



def _cleanup_k8s_job_if_exists(task: AnalysisTask, task_id: int):
    """Cleans up K8s job if task has job_id."""
    if not task.job_id:
        return
    
    try:
        from .services.k8s_service import K8sService
        from .tasks import _cleanup_completed_task
        
        k8s_service = K8sService()
        _cleanup_completed_task(task, k8s_service)
    except Exception as cleanup_error:
        logger.warning(f"Failed to cleanup K8s job for task {task_id}: {cleanup_error}")


def _schedule_next_analysis():
    """Schedules next analysis task on transaction commit."""
    from .tasks import check_and_trigger_next_analysis
    transaction.on_commit(lambda: check_and_trigger_next_analysis.delay())


def _create_success_response(request, task_id: int):
    """Creates successful completion response."""
    return json_success(request, {
        'message': 'Job completed successfully',
        'task_id': task_id,
        'status': STATUS_COMPLETED
    })

def _create_completion_error_response(request, task_id: int, error: Exception):
    return json_error(
        request,
        error='Completion error',
        message=f'Error processing job completion for task {task_id}: {error}',
        status=HTTP_STATUS_INTERNAL_SERVER_ERROR
    )


def _handle_task_not_found(request, task_id: int):
    """Handles case when task not found."""
    return json_error(
        request,
        error='Task not found',
        message=f'Analysis task {task_id} not found',
        status=HTTP_STATUS_NOT_FOUND
    )


def _handle_completion_error(request, task_id: int, error: Exception):
    """Handles errors during job completion."""
    logger.error(f"Error processing job completion for task {task_id}: {error}")
    logger.error(traceback.format_exc())
    
    _mark_task_failed_on_error(task_id, error)
    
    return json_error(
        request,
        error='Internal server error',
        message=str(error),
        status=HTTP_STATUS_INTERNAL_SERVER_ERROR
    )


def _mark_task_failed_on_error(task_id: int, error: Exception):
    """Marks task as failed when error occurs during completion."""
    try:
        task = AnalysisTask.objects.get(id=task_id)
        task.status = STATUS_FAILED
        task.error_message = str(error)
        task.completed_at = timezone.now()
        task.save()
    except Exception:
        pass


@csrf_exempt
@require_internal_api_token
@api_handler
def job_timeout_api(request):
    """
    Internal API endpoint called by the Go worker when analysis times out or fails.

    Expected JSON payload:
      {
        "task_id": "<id>",
        "status": "timeout" | "failed",
        "reason": "<human readable reason>"
      }
    """
    CALLBACK_KEY = 'worker_callback'
    DEFAULT_TIMEOUT_REASON = 'Execution time exceeded'
    ERROR_CATEGORY_TIMEOUT = 'timeout_error'
    ERROR_CATEGORY_WORKER_FAILED = 'worker_failed'
    ALLOWED_STATUSES = {'timeout', 'failed'}

    def _parse_timeout_callback_payload(req):
        if req.content_type and 'application/json' in req.content_type:
            try:
                payload = json.loads(req.body or b'{}')
            except (json.JSONDecodeError, ValueError):
                return None, json_error(
                    req,
                    error='Invalid JSON',
                    message='Request body must be valid JSON',
                    status=HTTP_STATUS_BAD_REQUEST
                )
        else:
            payload = req.POST

        raw_task_id = payload.get('task_id') or _extract_task_id_from_request(req)
        raw_status = (payload.get('status') or '').strip().lower()
        raw_reason = (payload.get('reason') or '').strip()

        if not raw_task_id:
            return None, json_error(
                req,
                error='Missing task_id',
                message='task_id parameter is required',
                status=HTTP_STATUS_BAD_REQUEST
            )

        try:
            parsed_task_id = int(raw_task_id)
        except (TypeError, ValueError):
            return None, json_error(
                req,
                error='Invalid task_id',
                message='task_id must be an integer',
                status=HTTP_STATUS_BAD_REQUEST
            )

        if raw_status not in ALLOWED_STATUSES:
            return None, json_error(
                req,
                error='Invalid status',
                message="status must be 'timeout' or 'failed'",
                status=HTTP_STATUS_BAD_REQUEST
            )

        if raw_status == 'timeout' and not raw_reason:
            raw_reason = DEFAULT_TIMEOUT_REASON

        return (parsed_task_id, raw_status, raw_reason), None

    def _apply_task_failure(task, failure_status, failure_reason):
        if failure_status == 'timeout':
            task.status = STATUS_TIMEOUT
        else:
            task.status = STATUS_FAILED

        task.error_message = failure_reason
        task.completed_at = timezone.now()
        task.save()

    def _cleanup_k8s_job(task, task_id_for_log):
        if not task.job_id:
            return
        try:
            from .services.k8s_service import K8sService
            from .tasks import _cleanup_completed_task
            k8s_service = K8sService()
            _cleanup_completed_task(task, k8s_service)
        except Exception as cleanup_error:
            logger.warning(
                f"Failed to cleanup K8s job for task {task_id_for_log}: {cleanup_error}"
            )

    if request.method != 'POST':
        return json_error(
            request,
            error='Method not allowed',
            message='Only POST requests are supported',
            status=HTTP_STATUS_METHOD_NOT_ALLOWED
        )

    parsed, error_response = _parse_timeout_callback_payload(request)
    if error_response:
        return error_response

    task_id, status, reason = parsed

    try:
        with transaction.atomic():
            def _trigger_next_on_commit():
                from .tasks import check_and_trigger_next_analysis
                transaction.on_commit(lambda: check_and_trigger_next_analysis.delay())

            task = AnalysisTask.objects.select_for_update().get(id=task_id)

            # If task already finalized, don't overwrite.
            if task.status in [STATUS_COMPLETED, STATUS_FAILED, STATUS_TIMEOUT]:
                _trigger_next_on_commit()
                return json_success(request, {
                    'message': f'Task already finalized with status: {task.status}',
                    'task_id': task_id,
                    'status': task.status,
                })

            _apply_task_failure(task, status, reason)
            _cleanup_k8s_job(task, task_id)
            _trigger_next_on_commit()

        logger.warning(
            f"Task {task_id} marked as {status} via worker callback. Reason: {reason}"
        )

        return json_success(request, {
            'message': 'Callback processed',
            'task_id': task_id,
            'status': task.status,
        })

    except AnalysisTask.DoesNotExist:
        return json_error(
            request,
            error='Task not found',
            message=f'Analysis task {task_id} not found',
            status=HTTP_STATUS_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Error processing worker timeout/failed callback for task {task_id}: {e}")
        logger.error(traceback.format_exc())
        return json_error(
            request,
            error='Internal server error',
            message=str(e),
            status=HTTP_STATUS_INTERNAL_SERVER_ERROR
        )