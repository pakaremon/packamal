from kubernetes import client, config
import logging
import uuid
import os

logger = logging.getLogger(__name__)

# Try to import Django settings, but handle case where Django might not be initialized
try:
    from django.conf import settings as django_settings
    DJANGO_AVAILABLE = True
except ImportError:
    DJANGO_AVAILABLE = False
    django_settings = None

class K8sService:
    def __init__(self):
        self.is_local = True
        try:
            config.load_incluster_config()
            logging.info("Loaded in-cluster Kubernetes config (AKS)")
        except config.ConfigException:
            config.load_kube_config()
            logging.info("Loaded local kubeconfig (Minikube)")
            self.is_local = True

        self.batch_v1 = client.BatchV1Api()
        self.namespace = "packamal"

    def run_analysis(self, ecosystem, package_name, task_id, package_version="latest"):
        # Generate a unique job name
        job_id = str(uuid.uuid4())[:8]
        job_name = f"analysis-{package_name.replace('_', '-')}-{job_id}"

        resources = client.V1ResourceRequirements(
            requests={"cpu": "1", "memory": "4Gi"},  # Reduced CPU request to fit available resources
            limits={"cpu": "2", "memory": "4Gi"},     # Can burst up to 2 CPUs if available
        )

        env_vars = [
            client.V1EnvVar(
                name="API_URL",
                value= os.environ.get("API_URL", "http://backend:8000/api/v1/internal/callback/done/")
            ),
            client.V1EnvVar(
                name="TASK_ID",
                value= str(task_id)  # Kubernetes requires string values for env vars
            ),
            client.V1EnvVar(
                name="INTERNAL_API_TOKEN",
                value=os.environ.get(
                    "INTERNAL_API_TOKEN",
                    getattr(django_settings, "INTERNAL_API_TOKEN", "packamal-auth-token") if DJANGO_AVAILABLE else "packamal-auth-token"
                )
            ),
            # Configure podman to work in Kubernetes environment
            # Use systemd cgroup manager if available, otherwise cgroupfs
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
            # Mount cgroup filesystem for podman to manage cgroups properly
            # This allows podman to access and manage cgroups for nested containers
            client.V1VolumeMount(
                name="sys-fs-cgroup", 
                mount_path="/sys/fs/cgroup", 
                read_only=False
            ),
            # Keep /tmp and /straceLogs for runtime temporary files during analysis
            client.V1VolumeMount(name="logs", mount_path="/tmp"),
            client.V1VolumeMount(name="strace-logs", mount_path="/straceLogs"),
        ]
        # Define the container with your specific command and arguments
        # For local development, use local image; for production, use registry image
        analysis_image = os.environ.get("ANALYSIS_IMAGE", "packamal-go-worker-analysis:local")
        # For local development, use IfNotPresent to use local image
        # For production, use Always to always pull latest from registry
        pull_policy = "IfNotPresent" if self.is_local else "Always"
        
        container = client.V1Container(
            name="analysis-worker",
            image=analysis_image,
            image_pull_policy=pull_policy,
            command=["analyze"], # The binary name
            args=[
                # Only save dynamic analysis results to /results/
                "-dynamic-bucket", "file:///results/",
                # Execution log also goes to /results/ (optional, can be omitted if not needed)
                # "-execution-log-bucket", "file:///results/",
                # Omit file-writes-bucket, static-bucket, and analyzed-pkg-bucket
                # to skip saving those results
                "-ecosystem", ecosystem,
                "-package", package_name,
                "-version", package_version,
                "-mode", "dynamic",
                "-nopull",
            ],
            env=env_vars,
            security_context=client.V1SecurityContext(privileged=True),
            resources=resources,
            volume_mounts=volume_mounts,
        )

        volumes = [
            # Use hostPath to access the pre-loaded images from the DaemonSet
            # This allows podman to use the images cached on the node by image-preloader DaemonSet
            client.V1Volume(
                name="container-data",
                host_path=client.V1HostPathVolumeSource(
                    path="/var/lib/containers",
                    type="DirectoryOrCreate"
                ),
            ),
            # Persistent storage for main analysis results
            client.V1Volume(
                name="results",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name="analysis-results-pvc"
                ),
            ),
            # Mount cgroup filesystem from host to allow podman to manage cgroups
            # This is required for podman to work properly in Kubernetes pods
            client.V1Volume(
                name="sys-fs-cgroup",
                host_path=client.V1HostPathVolumeSource(
                    path="/sys/fs/cgroup",
                    type="Directory"
                ),
            ),
            # Temporary storage volumes (emptyDir) for runtime temporary files
            # These are cleared when the pod terminates
            client.V1Volume(
                name="logs",
                empty_dir=client.V1EmptyDirVolumeSource()
            ),
            client.V1Volume(
                name="strace-logs",
                empty_dir=client.V1EmptyDirVolumeSource()
            ),
        ]

        # Define the Pod template
        # NOTE: Podman cgroup configuration:
        # - Podman uses --cgroup-manager=cgroupfs (hardcoded in analysis binary)
        # - We mount /sys/fs/cgroup from host to allow podman to manage cgroups
        # - If you see "device or resource busy" errors, the node may need cgroup delegation enabled
        # - For AKS: Ensure nodes have cgroup v2 delegation enabled (node-level configuration)
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"app": "analysis-job"}),
            spec=client.V1PodSpec(
                restart_policy="Never", 
                containers=[container],
                volumes=volumes,
                host_pid=True, # closest equivalent to --cgroupns=host
                host_network=False,  # Keep network isolation
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
        job_spec = client.V1JobSpec(
            template=template,
            backoff_limit=0,  # Do not retry if the analysis fails
            ttl_seconds_after_finished=300 # Cleanup Pod 5 mins after completion
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
            self.batch_v1.create_namespaced_job(namespace=self.namespace, body=job)
            return job_name
        except client.exceptions.ApiException as e:
            logger.error(f"K8s API Error: {e}")
            raise e