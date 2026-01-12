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
from .models import AnalysisTask, ReportDynamicAnalysis, Package
from .src.py2src.py2src.url_finder import URLFinder
from .utils import PURLParser, validate_purl_format
from .api_utils import json_success, json_error, api_handler
from .auth import require_api_key, require_internal_api_token
from .services.report_service import ReportService, normalize_package_name_for_storage
from .services.task_service import TaskService
from .services.package_version_service import PackageVersionService
from .view_constants import (
    STATUS_RECEIVED,
    STATUS_QUEUED,
    STATUS_PROCESSING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
    # Legacy status constants for backward compatibility
    STATUS_RUNNING,
    STATUS_PENDING,
    STATUS_SUBMITTED,
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


def download_professional_report(request, ecosystem, package_name, package_version):
    """Serve professional report JSON directly from Redis by key."""
    report_blob = ReportService.get_report_from_redis(ecosystem, package_name, package_version)
    if not report_blob:
        return HttpResponseNotFound("Report not found or expired")
    return HttpResponse(report_blob, content_type="application/json")


def save_report_to_database(report_data):
    """Save report data to database."""
    ReportService.save_report_to_database(report_data)


def _read_results_from_docker_volume(package_name):
    """Read analysis results from Docker volume for local development."""
    results_volume = os.getenv("RESULTS_VOLUME", DEFAULT_RESULTS_VOLUME)
    result_file_name = package_name.lower() + JSON_FILE_EXTENSION
    
    docker_cmd = [
        "docker", "run", "--rm",
        "-v", f"{results_volume}:/results",
        "alpine",
        "cat", f"/results/{result_file_name}",
    ]
    
    try:
        result = subprocess.run(docker_cmd, check=True, capture_output=True, text=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running Docker command: {e}, stderr: {e.stderr}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON from Docker result: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error reading results via Docker: {e}")
        return None


def _read_results_from_filesystem(package_name):
    """Read analysis results from filesystem for production (Kubernetes PVC)."""
    mount_path = os.getenv("MOUNT_PATH", DEFAULT_MOUNT_PATH)
    result_file_name = package_name.lower() + JSON_FILE_EXTENSION
    results_file = os.path.join(mount_path, result_file_name)
    
    try:
        with open(results_file, "r") as file:
            return json.load(file)
    except FileNotFoundError:
        logger.error(f"Results file not found: {results_file}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON from {results_file}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error reading results from mount path: {e}")
        return None


def read_results_from_mount_path(package_name):
    """Read analysis results based on execution mode.
    
    Uses ExecutionConfig to determine whether to read from Docker volume (local)
    or filesystem (K8s/production).
    """
    from .config import ExecutionConfig
    
    if ExecutionConfig.should_use_filesystem_results():
        return _read_results_from_filesystem(package_name)
    return _read_results_from_docker_volume(package_name)

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
        priority=task.priority,
        queue=CELERY_QUEUE_ANALYSIS
    )


def _create_and_queue_task(package_name, package_version, ecosystem):
    """Create analysis task and queue it."""
    task = AnalysisTask.objects.create(
        package_name=package_name,
        package_version=package_version,
        ecosystem=ecosystem,
        status=STATUS_QUEUED
    )
    _queue_celery_task(task)
    return task


def dynamic_analysis(request):
    """Dynamic analysis endpoint - ASYNC with Celery."""
    if request.method != 'POST':
        form = PackageSubmitForm()
        return render(request, 'package_analysis/analysis/dynamic_analysis.html', {'form': form})
    
    form = PackageSubmitForm(request.POST)
    if not form.is_valid():
        form = PackageSubmitForm()
        return render(request, 'package_analysis/analysis/dynamic_analysis.html', {'form': form})
    
    try:
        package_name, package_version, ecosystem = _extract_form_data(form)
        task = _create_and_queue_task(package_name, package_version, ecosystem)
        return JsonResponse({
            "status": "pending",
            "task_id": task.id,
            "message": "Analysis queued successfully"
        })
    except Exception as e:
        logger.error(f"Error queuing dynamic analysis: {e}")
        return JsonResponse({
            "status": "error",
            "error": str(e)
        }, status=HTTP_STATUS_INTERNAL_SERVER_ERROR) 

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
    API endpoint to check task status for async analysis
    Returns: task status, progress, and results when completed
    """
    try:
        task = AnalysisTask.objects.get(id=task_id)
        
        response_data = {
            'task_id': task.id,
            'status': task.status,  # queued, running, completed, failed
            'package_name': task.package_name,
            'package_version': task.package_version,
            'ecosystem': task.ecosystem,
            'created_at': task.created_at.isoformat() if task.created_at else None,
        }
        
        if task.started_at:
            response_data['started_at'] = task.started_at.isoformat()
        
        if task.completed_at:
            response_data['completed_at'] = task.completed_at.isoformat()
            if task.duration_seconds:
                response_data['duration_seconds'] = task.duration_seconds
        
        if task.worker_id:
            response_data['worker_id'] = task.worker_id
        
        if task.status == STATUS_COMPLETED and task.result:
            response_data['dynamic_analysis_report'] = task.result
        
        if task.status == STATUS_FAILED:
            response_data['error_message'] = task.error_message if hasattr(task, 'error_message') else 'Unknown error'
        
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
    fs = FileSystemStorage()
    filename = fs.save(file.name, file)
    uploaded_file_url = fs.url(filename)
    
    try:
        ecosystem = request.POST.get('ecosystem')
        package_name = request.POST.get('package_name')
        package_version = request.POST.get('package_version')
        
        reports = Helper.handle_uploaded_file(uploaded_file_url, package_name, package_version, ecosystem)
        return JsonResponse({"dynamic_analysis_report": reports})
    finally:
        fs.delete(filename)


def submit_sample(request):
    """Submit sample for analysis - redirects to dynamic_analysis."""
    if request.method == 'POST':
        form = PackageSubmitForm(request.POST)
        if form.is_valid():
            package_name, package_version, ecosystem = _extract_form_data(form)
            task = _create_and_queue_task(package_name, package_version, ecosystem)
            return JsonResponse({
                "status": "pending",
                "task_id": task.id,
                "message": "Analysis queued successfully"
            })
        return JsonResponse({"status": "error", "error": "Invalid form data"}, status=HTTP_STATUS_BAD_REQUEST)
    
    form = PackageSubmitForm()
    return render(request, 'package_analysis/dashboard.html', {'form': form})


def report_detail(request, report_id):
    '''Report detail analysis result of the package'''
    report = ReportDynamicAnalysis.objects.get(pk=report_id)
    return render(request, 'package_analysis/report_detail.html', {'report': report})

def get_all_report(request):
    """Get all analysis reports."""
    reports = ReportDynamicAnalysis.objects.all()
    results = {
        report.id: {
            'id': report.id,
            'package_name': report.package.package_name,
            'package_version': report.package.package_version,
            'ecosystem': report.package.ecosystem,
            'time': report.time,
        }
        for report in reports
    }
    return JsonResponse(results)

def get_report(request, report_id):
    report = ReportDynamicAnalysis.objects.get(pk=report_id)
    results = {
        'package_name': report.package.package_name,
        'package_version': report.package.package_version,
        'ecosystem': report.package.ecosystem,
        'time': report.time,
        'report_data': report.report,
    }
    return JsonResponse(results)

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


def get_predicted_download_url(request, package_name, package_version, ecosystem):
    """Get the predicted download URL for the final JSON report."""
    download_path = ReportService.build_download_path(ecosystem, package_name, package_version)
    return request.build_absolute_uri(download_path)


def _parse_purl_request(request):
    """Parse and validate PURL from request body."""
    data = json.loads(request.body)
    purl = data.get('purl')
    priority = data.get('priority', 0)
    
    if not purl:
        return None, None, json_error(
            request, error='Missing PURL', message='PURL parameter is required', status=HTTP_STATUS_BAD_REQUEST
        )
    
    if not validate_purl_format(purl):
        return None, None, json_error(
            request, error='Invalid PURL format', 
            message='PURL must be a valid package URL starting with pkg:', status=HTTP_STATUS_BAD_REQUEST
        )
    
    try:
        package_name, package_version, ecosystem = PURLParser.extract_package_info(purl)
        return (purl, priority, package_name, package_version, ecosystem), None
    except ValueError as e:
        return None, None, json_error(
            request, error='PURL parsing failed', message=str(e), status=HTTP_STATUS_BAD_REQUEST
        )


def _build_completed_task_response(completed_task, request):
    """Build response for completed task."""
    download_url, report_metadata = ReportService.save_professional_report(completed_task, request)
    return JsonResponse({
        'task_id': completed_task.id,
        'status': STATUS_COMPLETED,
        'result_url': download_url,
        'report_metadata': report_metadata,
        'message': 'Analysis already exists (cached result)'
    })


def _build_active_task_response(active_task, package_name, package_version, ecosystem, request):
    """Build response for active task."""
    predicted_download_url = get_predicted_download_url(request, package_name, package_version, ecosystem)
    status_url = request.build_absolute_uri(reverse('task_status_api', args=[active_task.id]))
    
    return json_success(request, {
        'task_id': active_task.id,
        'status': active_task.status,
        'status_url': status_url,
        'result_url': predicted_download_url,
        'message': f'Analysis already {active_task.status}'
    })


def _find_completed_task_for_purl(purl):
    """Find a completed task for the given PURL."""
    return AnalysisTask.objects.filter(
        purl=purl,
        status=STATUS_COMPLETED,
        report__isnull=False
    ).order_by('-completed_at').first()


def _find_active_tasks_for_purl(purl):
    """Find active tasks for the given PURL."""
    return AnalysisTask.objects.filter(
        purl=purl,
        status__in=[STATUS_PROCESSING, STATUS_QUEUED, STATUS_RECEIVED],
        created_at__gte=timezone.now() - timezone.timedelta(hours=ACTIVE_TASK_WINDOW_HOURS)
    ).order_by('-created_at')


def _extract_purl_data(request):
    """Extract and validate PURL data from request."""
    data = json.loads(request.body)
    purl = data.get('purl')
    priority = data.get('priority', 0)
    
    if not purl:
        return None, None, None, json_error(
            request, error='Missing PURL', message='PURL parameter is required', status=HTTP_STATUS_BAD_REQUEST
        )
    
    if not validate_purl_format(purl):
        return None, None, None, json_error(
            request, error='Invalid PURL format', 
            message='PURL must be a valid package URL starting with pkg:', status=HTTP_STATUS_BAD_REQUEST
        )
    
    try:
        package_name, package_version, ecosystem = PURLParser.extract_package_info(purl)
        return purl, priority, (package_name, package_version, ecosystem), None
    except ValueError as e:
        return None, None, None, json_error(
            request, error='PURL parsing failed', message=str(e), status=HTTP_STATUS_BAD_REQUEST
        )




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
        priority = data.get('priority', 0)
        
        if not purl:
            return json_error(request, error='Missing PURL', message='PURL parameter is required', status=HTTP_STATUS_BAD_REQUEST)
        
        if not validate_purl_format(purl):
            return json_error(request, error='Invalid PURL format', message='PURL must be a valid package URL starting with pkg:', status=HTTP_STATUS_BAD_REQUEST)
        
        try:
            package_name, package_version, ecosystem = PURLParser.extract_package_info(purl)
        except ValueError as e:
            return json_error(request, error='PURL parsing failed', message=str(e), status=HTTP_STATUS_BAD_REQUEST)
        
        completed_task = AnalysisTask.objects.filter(
            purl=purl,
            status=STATUS_COMPLETED,
            report__isnull=False
        ).order_by('-completed_at').first()
        
        if completed_task:
            logger.debug(f"Found completed task {completed_task.id} for PURL: {purl}")
            download_url, report_metadata = ReportService.save_professional_report(completed_task, request)
            return JsonResponse({
                'task_id': completed_task.id,
                'status': STATUS_COMPLETED,
                'result_url': download_url,
                'report_metadata': report_metadata,
                'message': 'Analysis already exists (cached result)'
            })
        
        existing_active_tasks = AnalysisTask.objects.filter(
            purl=purl,
            status__in=[STATUS_PROCESSING, STATUS_QUEUED, STATUS_RECEIVED],
            created_at__gte=timezone.now() - timezone.timedelta(hours=ACTIVE_TASK_WINDOW_HOURS)
        ).order_by('-created_at')
        
        active_task = existing_active_tasks.first()
        if active_task:
            return _build_active_task_response(active_task, package_name, package_version, ecosystem, request)
        
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
            package_name=package_name,
            package_version=package_version,
            ecosystem=ecosystem,
            status=STATUS_RECEIVED,
            priority=priority,
        )
        
        logger.debug(f"Created new task {task.id} for PURL: {purl}")
        
        try:
            TaskService.queue_task(task)
            celery_task = _queue_celery_task(task)
            
            logger.info(f"Queued task {task.id} via Celery (Celery ID: {celery_task.id})")
            
            status_url = request.build_absolute_uri(reverse('task_status_api', args=[task.id]))
            predicted_download_url = get_predicted_download_url(request, package_name, package_version, ecosystem)

            return json_success(request, {
                'task_id': task.id,
                'status': STATUS_QUEUED,
                'status_url': status_url,
                'result_url': predicted_download_url,
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
    API endpoint to check analysis task status
    """
    try:
        task = AnalysisTask.objects.get(id=task_id)

        expected_download_url = get_predicted_download_url(request, task.package_name, task.package_version, task.ecosystem)
        response_data = {
            'task_id': task.id,
            'purl': task.purl,
            'status': task.status,
            'created_at': task.created_at.isoformat(),
            'expected_download_url': expected_download_url,
            'package_name': task.package_name,
            'package_version': task.package_version,
            'ecosystem': task.ecosystem,
            'priority': task.priority,
            'timeout_minutes': task.timeout_minutes,
            'container_id': task.container_id,
            'last_heartbeat': task.last_heartbeat.isoformat() if task.last_heartbeat else None
        }
        
        if task.started_at:
            response_data['started_at'] = task.started_at.isoformat()
            
            if task.status == STATUS_PROCESSING:
                remaining_time = task.get_remaining_time_minutes()
                response_data['remaining_time_minutes'] = remaining_time
                response_data['is_timed_out'] = task.is_timed_out()
        
        if task.completed_at:
            response_data['completed_at'] = task.completed_at.isoformat()
        
        if task.error_message:
            response_data['error_message'] = task.error_message
            response_data['error_category'] = task.error_category
            if task.error_details:
                response_data['error_details'] = task.error_details
        
        if task.status == STATUS_COMPLETED and task.report:
            response_data['result_url'] = request.build_absolute_uri(
                reverse('get_report', args=[task.report.id])
            )
            if task.download_url:
                response_data['download_url'] = task.download_url
                # Also provide report metadata if available
                try:
                    import os
                    from django.conf import settings
                    if task.download_url:
                        # Extract filename from download URL
                        filename = os.path.basename(task.download_url)
                        save_dir = getattr(settings, 'MEDIA_ROOT', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'media'))
                        # Try to find the file and get its metadata
                        for root, dirs, files in os.walk(os.path.join(save_dir, 'reports')):
                            if filename in files:
                                file_path = os.path.join(root, filename)
                                response_data['report_metadata'] = {
                                    'filename': filename,
                                    'size_bytes': os.path.getsize(file_path),
                                    'created_at': task.completed_at.isoformat() if task.completed_at else None,
                                    'download_url': task.download_url,
                                    'folder_structure': os.path.relpath(root, save_dir) + '/'
                                }
                                break
                except Exception as e:
                    logger.warning(f"Could not generate report metadata: {e}")
        
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
            'package_name': t.package_name,
            'package_version': t.package_version,
            'ecosystem': t.ecosystem,
            'priority': t.priority,
            'result_url': (request.build_absolute_uri(reverse('get_report', args=[t.report.id])) if t.report else None),
            'download_url': t.download_url,
            'error_message': t.error_message if t.error_message else None,
            'error_category': t.error_category if t.error_category else None,
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


def _process_analysis_results(task, results):
    """Process analysis results and generate report."""
    report_data = Report.generate_report(results)
    report_payload = {
        "packages": {
            "package_name": task.package_name,
            "package_version": task.package_version,
            "ecosystem": task.ecosystem,
        },
        "report": report_data,
    }
    ReportService.save_report_to_database(report_payload)
    return ReportDynamicAnalysis.objects.latest('id')


def _calculate_task_duration(task):
    """Calculate task duration in seconds."""
    if task.started_at:
        return (timezone.now() - task.started_at).total_seconds()
    return None


def _finalize_task_completion(task, latest_report, duration, download_url):
    """Finalize task completion with all metadata."""
    task.status = STATUS_COMPLETED
    task.completed_at = timezone.now()
    task.report = latest_report
    if duration is not None and hasattr(task, 'duration_seconds'):
        task.duration_seconds = duration
    if download_url:
        task.download_url = download_url
    task.save()


def _handle_missing_results(request, task, task_id):
    """Handle case where results are not found."""
    task.status = STATUS_FAILED
    task.error_message = 'No results found in mount path'
    task.error_category = ERROR_CATEGORY_RESULTS_NOT_FOUND
    task.completed_at = timezone.now()
    task.save()
    return json_error(
        request,
        error='No results found',
        message='Analysis results not found in mount path',
        status=HTTP_STATUS_NOT_FOUND
    )


@csrf_exempt
@require_internal_api_token
@api_handler
def job_completed_api(request):
    """
    API endpoint called by Go worker when job completes.
    
    Processes results and marks task as completed. Handles race condition
    where watcher may have already marked task as completed - still processes
    results if report doesn't exist yet.
    
    When called, it:
    1. Reads analysis results from mount path
    2. Generates and saves report to database
    3. Creates professional report
    4. Updates task status from 'processing' to 'completed'
    5. Triggers K8s job cleanup
    """
    if request.method != 'POST':
        return json_error(
            request,
            error='Method not allowed',
            message='Only POST requests are supported',
            status=HTTP_STATUS_METHOD_NOT_ALLOWED
        )

    task_id = _extract_task_id_from_request(request)
    if not task_id:
        return json_error(
            request,
            error='Missing task_id',
            message='task_id parameter is required',
            status=400
        )
    
    try:
        with transaction.atomic():
            def _trigger_next_on_commit():
                from .tasks import check_and_trigger_next_analysis
                transaction.on_commit(lambda: check_and_trigger_next_analysis.delay())

            task = AnalysisTask.objects.select_for_update().get(id=task_id)
            
            if task.status not in [STATUS_PROCESSING, STATUS_COMPLETED]:
                logger.warning(
                    f"Task {task_id} is in status '{task.status}', "
                    f"not processing or completed. Skipping."
                )
                return json_success(request, {
                    'message': f'Task already in status: {task.status}',
                    'task_id': task_id,
                    'status': task.status
                })
            
            if task.status == STATUS_COMPLETED and task.report:
                logger.info(f"Task {task_id} already completed with report")
                _trigger_next_on_commit()
                return json_success(request, {
                    'message': 'Task already completed',
                    'task_id': task_id,
                    'status': STATUS_COMPLETED,
                    'download_url': task.download_url
                })
            
            results = read_results_from_mount_path(task.package_name)
            if not results:
                logger.error(f"No results found for task {task_id}")
                return _handle_missing_results(request, task, task_id)
            
            latest_report = _process_analysis_results(task, results)
            duration = _calculate_task_duration(task)
            
            task.report = latest_report
            task.save()
            
            try:
                download_url, report_metadata = ReportService.save_professional_report(task, request)
            except Exception as save_error:
                logger.warning(f"Failed to save professional report for task {task_id}: {save_error}")
                download_url = None
            
            _finalize_task_completion(task, latest_report, duration, download_url)
            
            logger.info(f"Task {task_id} completed successfully via worker callback")
            
            from .services.k8s_service import K8sService
            from .tasks import _cleanup_completed_task
            if task.job_id:
                try:
                    k8s_service = K8sService()
                    _cleanup_completed_task(task, k8s_service)
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup K8s job for task {task_id}: {cleanup_error}")

            _trigger_next_on_commit()
            
            return json_success(request, {
                'message': 'Job completed successfully',
                'task_id': task_id,
                'status': STATUS_COMPLETED,
                'download_url': download_url,
                'report_id': latest_report.id
            })
            
    except AnalysisTask.DoesNotExist:
        return json_error(
            request,
            error='Task not found',
            message=f'Analysis task {task_id} not found',
            status=404
        )
    except Exception as e:
        logger.error(f"Error processing job completion for task {task_id}: {e}")
        logger.error(traceback.format_exc())
        
        try:
            task = AnalysisTask.objects.get(id=task_id)
            task.status = STATUS_FAILED
            task.error_message = str(e)
            task.error_category = ERROR_CATEGORY_CALLBACK_ERROR
            task.completed_at = timezone.now()
            task.save()
        except Exception:
            pass
        
        return json_error(
            request,
            error='Internal server error',
            message=str(e),
            status=HTTP_STATUS_INTERNAL_SERVER_ERROR
        )


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
            task.error_category = ERROR_CATEGORY_TIMEOUT
        else:
            task.status = STATUS_FAILED
            task.error_category = ERROR_CATEGORY_WORKER_FAILED

        task.error_message = failure_reason
        task.completed_at = timezone.now()

        details = task.error_details or {}
        details[CALLBACK_KEY] = {
            'status': failure_status,
            'reason': failure_reason,
            'received_at': timezone.now().isoformat(),
        }
        task.error_details = details
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