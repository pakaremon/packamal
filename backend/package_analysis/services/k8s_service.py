from kubernetes import client, config
import logging
import uuid
import os
import re

logger = logging.getLogger(__name__)

# Try to import Django settings, but handle case where Django might not be initialized
try:
    from django.conf import settings as django_settings
    DJANGO_AVAILABLE = True
except ImportError:
    DJANGO_AVAILABLE = False
    django_settings = None

MAX_K8S_RESOURCE_NAME_LENGTH = 253
MAX_PACKAGE_NAME_LENGTH = 200
DEFAULT_PACKAGE_NAME = "pkg"
NPM_SCOPE_PREFIX = "@"

class K8sService:
    def __init__(self):
        self.is_local = True
        try:
            config.load_incluster_config()
            logging.info("Loaded in-cluster Kubernetes config")
            self.is_local = False
        except config.ConfigException:
            config.load_kube_config()
            logging.info("Loaded local kubeconfig (Minikube)")
            self.is_local = True

        self.batch_v1 = client.BatchV1Api()
        self.core_v1 = client.CoreV1Api()
        self.namespace = os.environ.get("K8S_NAMESPACE", "packamal")
        self.analysis_node_selector = self._parse_node_selector(
            os.environ.get("ANALYSIS_NODE_SELECTOR", "")
        )
        self.sandbox_dynamic_analysis_image = os.environ.get("SANDBOX_DYNAMIC_ANALYSIS_IMAGE", "docker.io/pakaremon/dynamic-analysis")

    @staticmethod
    def _parse_node_selector(selector: str) -> dict:
        """
        Parse a comma-separated node selector string (key=value,key2=value2) into a dict.
        Returns an empty dict if the input is blank or invalid.
        """
        if not selector:
            return {}
        node_selector = {}
        for item in selector.split(","):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key and value:
                node_selector[key] = value
        return node_selector

    @staticmethod
    def _remove_npm_scope_prefix(name: str) -> str:
        """Remove leading @ from npm scoped package names."""
        return name.lstrip(NPM_SCOPE_PREFIX)

    @staticmethod
    def _replace_invalid_characters(name: str) -> str:
        """Replace invalid characters with hyphens and convert to lowercase."""
        return re.sub(r'[^a-z0-9.-]', '-', name.lower())

    @staticmethod
    def _normalize_separators(name: str) -> str:
        """Replace multiple consecutive hyphens or dots with a single hyphen."""
        return re.sub(r'[-.]+', '-', name)

    @staticmethod
    def _ensure_alphanumeric_boundaries(name: str) -> str:
        """Remove leading and trailing hyphens/dots to ensure alphanumeric boundaries."""
        return name.strip('-.')

    @staticmethod
    def _ensure_non_empty(name: str) -> str:
        """Return default name if empty after sanitization."""
        return name if name else DEFAULT_PACKAGE_NAME

    @staticmethod
    def _truncate_to_max_length(name: str) -> str:
        """Truncate name to maximum allowed length."""
        if len(name) <= MAX_PACKAGE_NAME_LENGTH:
            return name
        truncated = name[:MAX_PACKAGE_NAME_LENGTH]
        return truncated.rstrip('-.')

    @staticmethod
    def _sanitize_for_k8s_name(name: str) -> str:
        """
        Sanitize a package name to be RFC 1123 compliant for Kubernetes resource names.
        
        Kubernetes resource names must:
        - Consist of lowercase alphanumeric characters, '-' or '.'
        - Start and end with an alphanumeric character
        - Be at most 253 characters (we'll truncate if needed)
        
        Args:
            name: Package name (e.g., "@babel/core", "django_utils")
            
        Returns:
            Sanitized name safe for Kubernetes (e.g., "babel-core", "django-utils")
        """
        sanitized = K8sService._remove_npm_scope_prefix(name)
        sanitized = K8sService._replace_invalid_characters(sanitized)
        sanitized = K8sService._normalize_separators(sanitized)
        sanitized = K8sService._ensure_alphanumeric_boundaries(sanitized)
        sanitized = K8sService._ensure_non_empty(sanitized)
        sanitized = K8sService._truncate_to_max_length(sanitized)
        return sanitized

    def run_analysis(self, ecosystem, package_name, task_id, package_version="latest"):
        # Generate a unique job name using sanitized package name
        # The original package_name is preserved for the analysis command args
        job_id = str(uuid.uuid4())[:8]
        sanitized_package_name = self._sanitize_for_k8s_name(package_name)
        job_name = f"analysis-{sanitized_package_name}-{job_id}"

        # resources = client.V1ResourceRequirements(
        #     requests={"cpu": "100m", "memory": "2Gi"},  # Reduced CPU request to fit available resources (250m = 0.25 CPU)
        #     limits={"cpu": "1.5", "memory": "4Gi"},     # Can burst up to 2 CPUs if available
        # )

        resources = client.V1ResourceRequirements(
            # Requests: what the scheduler must be able to allocate.
            # Keep this lower to fit on small analysis node pools and to avoid namespace quotas.
            requests={"cpu": "200m", "memory": "2Gi"},
            # Limits: allow some burst, but keep under typical per-node capacity.
            limits={"cpu": "800m", "memory": "4.6Gi"},
        )

        env_vars = [
            # Single internal callback base URL.
            # Go worker will append /done/ or /timeout/ automatically.
            client.V1EnvVar(
                name="INTERNAL_API_BASE_URL",
                value=os.environ.get("INTERNAL_API_BASE_URL", "http://backend:8000/api/v1/internal/callback")
            ),
            client.V1EnvVar(
                name="TASK_ID",
                value=str(task_id)  # Kubernetes requires string values for env vars
            ),
            # Tier-1 Graceful Timeout: maximum execution time for the Go worker itself.
            # Format: Go time.ParseDuration, e.g. "30m", "1h".
            client.V1EnvVar(
                name="ANALYSIS_TIMEOUT",
                value=os.environ.get("ANALYSIS_TIMEOUT", "30m")
            ),
            # INTERNAL_API_TOKEN must be injected from the Kubernetes Secret to ensure
            # the heavy worker can authenticate back to the backend API.
            client.V1EnvVar(
                name="INTERNAL_API_TOKEN",
                value_from=client.V1EnvVarSource(
                    secret_key_ref=client.V1SecretKeySelector(
                        name="packamal-secrets",
                        key="INTERNAL_API_TOKEN"
                    )
                ),
            ),
            # Configure podman to work in Kubernetes environment
            # Explicitly set cgroupfs manager since systemd is not available in containers
            # and podman's auto-detection would try to use systemd
            client.V1EnvVar(
                name="PODMAN_CGROUP_MANAGER",
                value="cgroupfs"
            ),
            client.V1EnvVar(
                name="CONTAINERS_CONF",
                value="/dev/null"  # Use default podman config
            ),
        ]

        # NOTE: Only dynamic analysis results are saved to /results/ (PVC for persistence).
        # Other result types (file writes, static analysis, analyzed packages) are omitted.
        volume_mounts = [
            client.V1VolumeMount(name="container-data", mount_path="/var/lib/containers"),
            client.V1VolumeMount(name="results", mount_path="/results"),
        ]
        # Define the container with your specific command and arguments
        # For local development, use local image; for production, use registry image
        analysis_image = os.environ.get("ANALYSIS_IMAGE", "packamal-go-worker-analysis:local")
        logger.info(f"Using analysis image: {analysis_image}")
        
        # Use IfNotPresent to leverage node's local image cache
        # The image-preloader DaemonSet ensures the heavy dynamic-analysis image
        # (10GB) is pre-pulled to every node, so analysis jobs start instantly
        # using the cached image instead of downloading over the network
        # NOTE: If image doesn't exist locally, it will try to pull from registry
        # For ACR images, ensure the node pool has proper authentication configured
        # IMPORTANT:
        # We frequently rebuild/push images with the same tag during testing (e.g. ":v1").
        # If we keep IfNotPresent, nodes may keep running a cached old image.
        # Default to Always so fixes in go-worker-analysis are picked up immediately.
        pull_policy = os.environ.get("ANALYSIS_IMAGE_PULL_POLICY", "Always")
        
        container = client.V1Container(
            name="analysis-worker",
            image=analysis_image,
            image_pull_policy=pull_policy,
            command=["analyze"], # The binary name
            args=[
                # Only save dynamic analysis results to /results/
                # Contract: worker writes to this bucket/prefix using TASK_ID as the deterministic key.
                # Prefer ANALYSIS_DYNAMIC_BUCKET_URL, otherwise fall back to RESULTS_BUCKET_URL.
                "-dynamic-bucket",
                os.environ.get(
                    "ANALYSIS_DYNAMIC_BUCKET_URL",
                    os.environ.get("RESULTS_BUCKET_URL", "file:///results/"),
                ),
                "-ecosystem", ecosystem,
                "-package", package_name,
                "-version", package_version,
                "-sandbox-image", self.sandbox_dynamic_analysis_image,
                "-mode", "dynamic",
                "-nopull",
            ],
            # for testing use /bin/bash sleep in 60 minutes
            # command=["/bin/bash"],
            # args=["-c", "sleep 3600"],
            env=env_vars,
            security_context=client.V1SecurityContext(privileged=True),
            resources=resources,
            volume_mounts=volume_mounts,
        )

        # Results storage mode:
        # - "pvc": persist results via a PVC (default; may Multi-Attach fail across nodes with RWO disks)
        # - "emptyDir": ephemeral per-pod storage (best for testing / avoids PD attach)
        results_volume_mode = os.environ.get("ANALYSIS_RESULTS_VOLUME_MODE", "pvc").strip().lower()
        results_pvc_name = os.environ.get("ANALYSIS_RESULTS_PVC_NAME", "analysis-results-pvc").strip()

        results_volume = (
            client.V1Volume(
                name="results",
                empty_dir=client.V1EmptyDirVolumeSource(),
            )
            if results_volume_mode in ("emptydir", "empty_dir", "tmp", "gcs", "gs")
            else client.V1Volume(
                name="results",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name=results_pvc_name
                ),
            )
        )

        # PRELOADER INIT CONTAINER:
        # Instead of running a DaemonSet on every node to pre-pull the 10GB
        # dynamic-analysis image, we use an initContainer in the analysis Job.
        #
        # This initContainer:
        # - Mounts the host's containerd socket
        # - Installs crictl
        # - Runs `crictl pull docker.io/pakaremon/dynamic-analysis:latest`
        #
        # As a result, whenever a new analysis node scales up and a Job lands
        # on it, the initContainer pulls the heavy image into the node's
        # containerd cache before the main analysis container starts.
        preloader_image = os.environ.get("ANALYSIS_PRELOADER_IMAGE", "alpine:3.18")

        preloader_init_container = client.V1Container(
            name="preloader",
            image=preloader_image,
            command=["/bin/sh", "-c"],
            args=[
                (
                    "set -e;"
                    " apk add --no-cache curl;"
                    " curl -L https://github.com/kubernetes-sigs/cri-tools/releases/download/"
                    "v1.28.0/crictl-v1.28.0-linux-amd64.tar.gz"
                    " | tar -xz -C /usr/local/bin;"
                    ' echo "🚀 Preloading dynamic-analysis image on node...";'
                    " crictl pull docker.io/pakaremon/dynamic-analysis:latest;"
                    ' echo "✅ Preload complete";'
                )
            ],
            security_context=client.V1SecurityContext(privileged=True),
            volume_mounts=[
                client.V1VolumeMount(
                    name="containerd-sock",
                    mount_path="/run/containerd/containerd.sock",
                ),
            ],
            resources=client.V1ResourceRequirements(
                requests={"cpu": "50m", "memory": "128Mi"},
                limits={"cpu": "500m", "memory": "512Mi"},
            ),
        )

        volumes = [
            # NESTED CONTAINER SUPPORT: Use hostPath to share node's container image cache
            # so podman can access the pre-pulled dynamic-analysis image.
            client.V1Volume(
                name="container-data",
                host_path=client.V1HostPathVolumeSource(
                    path="/var/lib/containers",
                    type="DirectoryOrCreate"
                ),
            ),
            # Allow the preloader initContainer to talk directly to containerd
            # on the host in order to pull images into the node-level cache.
            client.V1Volume(
                name="containerd-sock",
                host_path=client.V1HostPathVolumeSource(
                    path="/run/containerd/containerd.sock",
                    type="Socket",
                ),
            ),
            results_volume,
        ]

        # Define the Pod template
        # NOTE: Podman cgroup configuration:
        # - Podman uses --cgroup-manager=cgroupfs (configured via PODMAN_CGROUP_MANAGER env var)
        # - We mount /sys/fs/cgroup from host to allow podman to access the cgroup hierarchy
        # - We also mount a tmpfs at /sys/fs/cgroup/libpod_parent so podman can create
        #   required subdirectories (libpod_parent/conmon/, etc.) that it needs for cgroupfs manager
        # IMPORTANT: Do NOT set hostPID=True for analysis jobs.
        # With hostPID enabled, podman/conmon often fails to move processes into
        # nested cgroups on cgroup v2 (errors writing cgroup.procs / pids.max).
        # Keeping hostPID disabled still allows privileged podman-in-pod usage
        # while avoiding PID/cgroup namespace mismatches.
        # - hostNetwork=False keeps network isolation for security
        tolerations = [
            # Allow scheduling heavy analysis jobs onto a tainted "analysis-pool" node pool:
            #   kubectl taint nodes <node-name> dedicated=analysis:NoSchedule
            client.V1Toleration(
                key="dedicated",
                operator="Equal",
                value="analysis",
                effect="NoSchedule",
            )
            ,
            # GKE Sandbox node pools commonly taint nodes with:
            #   sandbox.gke.io/runtime=gvisor:NoSchedule
            # If your analysis node pool is created with `--sandbox type=gvisor`,
            # the autoscaler will NOT scale up unless pods tolerate this taint.
            client.V1Toleration(
                key="sandbox.gke.io/runtime",
                operator="Equal",
                value="gvisor",
                effect="NoSchedule",
            ),
        ]

        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"app": "analysis-job"}),
            spec=client.V1PodSpec(
                restart_policy="Never",
                # IMPORTANT: Go heavy worker inherits GCP permissions via Workload Identity from this KSA.
                service_account_name="backend-serviceaccount",
                priority_class_name="packamal-app-priority",
                init_containers=[preloader_init_container],
                containers=[container],
                volumes=volumes,
                host_pid=False,
                host_network=False,  # Keep network isolation
                tolerations=tolerations,
                node_selector=self.analysis_node_selector or None,
            )
        )
        # Define the Job specification
        # NOTE: Analysis jobs can take a long time because:
        # 1. The analysis container pulls docker.io/pakaremon/dynamic-analysis:latest at runtime via podman
        # 2. This image pull happens inside the container and can take 10-20+ minutes depending on network speed
        # 3. The actual analysis also takes time depending on package size
        # 
        # OPTIMIZATION: The dynamic-analysis image is pre-loaded on all nodes via the image-preloader DaemonSet
        # (see prd/k8s/13-image-preloader.yaml). This significantly reduces image pull time during analysis.
        
        # Read pod timeout from config (default: 60 minutes = 3600 seconds)
        pod_timeout_seconds = int(os.environ.get("POD_TIMEOUT_SECONDS", "3600"))
        
        job_spec = client.V1JobSpec(
            template=template,
            backoff_limit=0,  # Do not retry if the analysis fails
            ttl_seconds_after_finished=600,  # Cleanup Pod 10 mins after completion
            active_deadline_seconds=pod_timeout_seconds  # Maximum time pod can run (30 minutes default)
        )

        # Create the Job object
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(name=job_name),
            spec=job_spec
        )

        try:
            logger.info(f"Submitting Job {job_name} to K8s...")
            logger.info(f"  Image: {analysis_image}")
            logger.info(f"  ImagePullPolicy: {pull_policy}")
            if results_volume_mode in ("gcs", "gs"):
                logger.info("  Results storage: GCS (no PVC mounted)")
            elif results_volume_mode in ("emptydir", "empty_dir", "tmp"):
                logger.info("  Results volume: emptyDir")
            else:
                logger.info(f"  Results PVC: {results_pvc_name}")
            logger.info(f"  ServiceAccount: backend-serviceaccount")
            self.batch_v1.create_namespaced_job(namespace=self.namespace, body=job)
            logger.info(f"Job {job_name} created successfully")
            return job_name
        except client.exceptions.ApiException as e:
            logger.error(f"K8s API Error creating job {job_name}: {e}")
            logger.error(f"  Status: {e.status}")
            logger.error(f"  Reason: {e.reason}")
            logger.error(f"  Body: {e.body}")
            raise e

    def get_job(self, job_name: str) -> client.V1Job:
        """
        Fetch a single Job by name for status inspection.
        """
        return self.batch_v1.read_namespaced_job(name=job_name, namespace=self.namespace)

    def list_jobs(self, label_selector: str | None = None) -> client.V1JobList:
        """
        List Jobs in the namespace, optionally filtered by label selector
        (e.g. 'app=analysis-job').
        """
        return self.batch_v1.list_namespaced_job(
            namespace=self.namespace,
            label_selector=label_selector,
        )

    def delete_job(self, job_name: str, propagation_policy: str = "Background") -> None:
        """
        Delete a Job and its Pods. Use propagation_policy='Foreground' if you
        need synchronous cleanup semantics during debugging.
        """
        body = client.V1DeleteOptions(propagation_policy=propagation_policy)
        self.batch_v1.delete_namespaced_job(
            name=job_name,
            namespace=self.namespace,
            body=body,
        )

    def list_pods_for_job(self, job_name: str) -> client.V1PodList:
        """
        List Pods belonging to the given Job, useful for status & log scraping.
        """
        label_selector = f"job-name={job_name}"
        return self.core_v1.list_namespaced_pod(
            namespace=self.namespace,
            label_selector=label_selector,
        )

    def list_pods(
        self,
        namespace: str | None = None,
        label_selector: str | None = None,
        field_selector: str | None = None,
    ) -> client.V1PodList:
        """
        List Pods in a namespace, optionally filtered by label/field selectors.

        This is used by periodic maintenance tasks (e.g. eraser zombie cleanup)
        that need to inspect Pods outside the default application namespace.
        """
        return self.core_v1.list_namespaced_pod(
            namespace=namespace or self.namespace,
            label_selector=label_selector,
            field_selector=field_selector,
        )

    def delete_pod(
        self,
        pod_name: str,
        namespace: str | None = None,
        grace_period_seconds: int = 0,
    ) -> None:
        """
        Delete a Pod. For emergency cleanup, set grace_period_seconds=0.
        """
        body = client.V1DeleteOptions(grace_period_seconds=grace_period_seconds)
        self.core_v1.delete_namespaced_pod(
            name=pod_name,
            namespace=namespace or self.namespace,
            body=body,
        )

    def get_pod_logs(self, pod_name: str, container: str | None = None, tail_lines: int | None = 200) -> str:
        """
        Fetch logs from a Pod (optionally a specific container). This is
        particularly useful for debugging 10GB image pull or nested podman
        failures in the analysis jobs.
        """
        return self.core_v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=self.namespace,
            container=container,
            tail_lines=tail_lines,
        )