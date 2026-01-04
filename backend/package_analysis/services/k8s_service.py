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
        self.core_v1 = client.CoreV1Api()
        self.namespace = "packamal"
        self.sandbox_dynamic_analysis_image = os.environ.get("SANDBOX_DYNAMIC_ANALYSIS_IMAGE", "docker.io/pakaremon/dynamic-analysis")

    def run_analysis(self, ecosystem, package_name, task_id, package_version="latest"):
        # Generate a unique job name
        job_id = str(uuid.uuid4())[:8]
        job_name = f"analysis-{package_name.replace('_', '-')}-{job_id}"

        resources = client.V1ResourceRequirements(
            requests={"cpu": "100m", "memory": "2Gi"},  # Reduced CPU request to fit available resources (250m = 0.25 CPU)
            limits={"cpu": "2", "memory": "4Gi"},     # Can burst up to 2 CPUs if available
        )

        env_vars = [
            client.V1EnvVar(
                name="API_URL",
                value=os.environ.get("API_URL", "http://backend:8000/api/v1/internal/callback/done/")
            ),
            client.V1EnvVar(
                name="TASK_ID",
                value=str(task_id)  # Kubernetes requires string values for env vars
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
        pull_policy = "IfNotPresent"
        
        container = client.V1Container(
            name="analysis-worker",
            image=analysis_image,
            image_pull_policy=pull_policy,
            command=["analyze"], # The binary name
            args=[
                # Only save dynamic analysis results to /results/
                "-dynamic-bucket", "file:///results/",
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

        volumes = [
            # NESTED CONTAINER SUPPORT: Use hostPath to share node's container image cache
            # The image-preloader DaemonSet pre-pulls the 10GB dynamic-analysis image
            # into /var/lib/containers on each node. By mounting this same path as hostPath,
            # the analysis job's podman can access the pre-pulled image instantly without
            # re-downloading 10GB over the network. This enables Docker-in-Docker (podman)
            # to use the node's existing image cache.
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
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"app": "analysis-job"}),
            spec=client.V1PodSpec(
                restart_policy="Never",
                service_account_name="backend-serviceaccount",
                containers=[container],
                volumes=volumes,
                host_pid=False,
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
            logger.info(f"  Image: {analysis_image}")
            logger.info(f"  ImagePullPolicy: {pull_policy}")
            logger.info(f"  PVC: analysis-results-pvc")
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