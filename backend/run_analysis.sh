#!/bin/bash

# Docker volume names (override with env vars if needed)
RESULTS_VOLUME=${RESULTS_VOLUME:-"analysis_results"}
STATIC_RESULTS_VOLUME=${STATIC_RESULTS_VOLUME:-"analysis_static_results"}
FILE_WRITE_RESULTS_VOLUME=${FILE_WRITE_RESULTS_VOLUME:-"analysis_write_results"}
ANALYZED_PACKAGES_VOLUME=${ANALYZED_PACKAGES_VOLUME:-"analysis_analyzed_packages"}
LOGS_VOLUME=${LOGS_VOLUME:-"analysis_logs"}
STRACE_LOGS_VOLUME=${STRACE_LOGS_VOLUME:-"analysis_strace_logs"}
CONTAINER_VOLUME=${CONTAINER_VOLUME:-"analysis_container_data"}

# for pretty printing
LINE="-----------------------------------------"

function print_usage {
	echo "Usage: $0 [-dryrun] [-fully-offline] <analyze args...>"
	echo
	echo $LINE
	echo "Script options"
	echo "  -dryrun"
	echo "    	prints commmand that would be executed and exits"
	echo "  -fully-offline"
	echo "    	completely disables network access for the container runtime"
	echo "    	Analysis will only work when using -local <pkg path> and -nopull."
	echo "    	(see also: -offline)"
	echo "  -nointeractive"
	echo "          disables TTY input and prevents allocating pseudo-tty"
	echo $LINE
	echo
}

function print_package_details {
	echo "Ecosystem:                $ECOSYSTEM"
	echo "Package:                  $PACKAGE"
	echo "Version:                  $VERSION"
	if [[ $LOCAL -eq 1 ]]; then
		LOCATION="$PKG_PATH"
	else
		LOCATION="remote"
	fi

	echo "Location:                 $LOCATION"
}

function print_results_dirs {
	echo "Dynamic analysis results volume: $RESULTS_VOLUME"
	echo "Static analysis results volume:  $STATIC_RESULTS_VOLUME"
	echo "File write results volume:       $FILE_WRITE_RESULTS_VOLUME"
	echo "Analyzed package volume:         $ANALYZED_PACKAGES_VOLUME"
	echo "Debug logs volume:               $LOGS_VOLUME"
	echo "Strace logs volume:              $STRACE_LOGS_VOLUME"
}


args=("$@")

HELP=0
DRYRUN=0
LOCAL=0
DOCKER_OFFLINE=0
INTERACTIVE=1

ECOSYSTEM=""
PACKAGE=""
VERSION=""
PKG_PATH=""
MOUNTED_PKG_PATH=""

i=0
while [[ $i -lt $# ]]; do
	case "${args[$i]}" in
		"-dryrun")
			DRYRUN=1
			unset "args[i]" # this argument is not passed to analysis image
			;;
		"-fully-offline")
			DOCKER_OFFLINE=1
			unset "args[i]" # this argument is not passed to analysis image
			;;
		"-nointeractive")
			INTERACTIVE=0
			unset "args[i]" # this argument is not passed to analysis image
			;;
		"-help")
			HELP=1
			;;
		"-local")
			# need to create a mount to pass the package archive to the docker image
			LOCAL=1
			i=$((i+1))
			# -m preserves invalid/non-existent paths (which will be detected below)
			PKG_PATH=$(realpath -m "${args[$i]}")
			if [[ -z "$PKG_PATH" ]]; then
				echo "-local specified but no package path given"
				exit 255
			fi
			PKG_FILE=$(basename "$PKG_PATH")
			MOUNTED_PKG_PATH="/$PKG_FILE"
			# need to change the path passed to analysis image to the mounted one
			# which is stripped of host path info
			args[$i]="$MOUNTED_PKG_PATH"
			;;
		"-ecosystem")
			i=$((i+1))
			ECOSYSTEM="${args[$i]}"
			;;
		"-package")
			i=$((i+1))
			PACKAGE="${args[$i]}"
			;;
		"-version")
			i=$((i+1))
			VERSION="${args[$i]}"
			;;
	esac
	i=$((i+1))
done

if [[ $# -eq 0 ]]; then
	HELP=1
fi

DOCKER_OPTS=("run" "--cgroupns=host" "--privileged" "--rm" "--cpus=2.0" "--memory=4g")

# Ensure Docker volumes exist
function ensure_volume() {
	local vol="$1"
	if ! docker volume inspect "$vol" >/dev/null 2>&1; then
		docker volume create "$vol" >/dev/null
	fi
}

ensure_volume "$RESULTS_VOLUME"
ensure_volume "$STATIC_RESULTS_VOLUME"
ensure_volume "$FILE_WRITE_RESULTS_VOLUME"
ensure_volume "$ANALYZED_PACKAGES_VOLUME"
ensure_volume "$LOGS_VOLUME"
ensure_volume "$STRACE_LOGS_VOLUME"
ensure_volume "$CONTAINER_VOLUME"

DOCKER_MOUNTS=("-v" "$CONTAINER_VOLUME:/var/lib/containers" "-v" "$RESULTS_VOLUME:/results" "-v" "$STATIC_RESULTS_VOLUME:/staticResults" "-v" "$FILE_WRITE_RESULTS_VOLUME:/writeResults" "-v" "$LOGS_VOLUME:/tmp" "-v" "$ANALYZED_PACKAGES_VOLUME:/analyzedPackages" "-v" "$STRACE_LOGS_VOLUME:/straceLogs")

ANALYSIS_IMAGE=docker.io/pakaremon/analysis

ANALYSIS_ARGS=("analyze" "-dynamic-bucket" "file:///results/" "-file-writes-bucket" "file:///writeResults/" "-static-bucket" "file:///staticResults/" "-analyzed-pkg-bucket" "file:///analyzedPackages/" "-execution-log-bucket" "file:///results")

# Add the remaining command line arguments
ANALYSIS_ARGS=("${ANALYSIS_ARGS[@]}" "${args[@]}")

if [[ $HELP -eq 1 ]]; then
	print_usage
fi

if [[ $INTERACTIVE -eq 1 ]]; then
	DOCKER_OPTS+=("-ti")
fi

if [[ $LOCAL -eq 1 ]]; then
	LOCATION="$PKG_PATH"

	# mount local package file in root of docker image
	DOCKER_MOUNTS+=("-v" "$PKG_PATH:$MOUNTED_PKG_PATH")
else
	LOCATION="remote"
fi

if [[ $DOCKER_OFFLINE -eq 1 ]]; then
	DOCKER_OPTS+=("--network" "none")
fi

if [[ -n "$ECOSYSTEM" && -n "$PACKAGE" ]]; then
	PACKAGE_DEFINED=1
else
	PACKAGE_DEFINED=0
fi

if [[ $PACKAGE_DEFINED -eq 1 ]]; then
	echo $LINE
	echo "Package Details"
	print_package_details
	echo $LINE
fi

# If dry run, just print the command and exit
if [[ $DRYRUN -eq 1 ]]; then
	echo "Analysis command (dry run)"
	echo
	echo docker "${DOCKER_OPTS[@]}" "${DOCKER_MOUNTS[@]}" "$ANALYSIS_IMAGE" "${ANALYSIS_ARGS[@]}"

	echo
	exit 0
fi

# Else continue execution
if [[ $PACKAGE_DEFINED -eq 1 ]]; then
	echo "Analysing package"
	echo
fi

if [[ $LOCAL -eq 1 ]] && [[ ! -f "$PKG_PATH" || ! -r "$PKG_PATH" ]]; then
	echo "Error: path $PKG_PATH does not refer to a file or is not readable"
	echo
	exit 1
fi

sleep 1 # Allow time to read info above before executing

# mkdir -p "$RESULTS_DIR"
# mkdir -p "$STATIC_RESULTS_DIR"
# mkdir -p "$FILE_WRITE_RESULTS_DIR"
# mkdir -p "$ANALYZED_PACKAGES_DIR"
# mkdir -p "$LOGS_DIR"
# mkdir -p "$STRACE_LOGS_DIR"
# print the command that would be executed
echo "Executing command:"
echo docker "${DOCKER_OPTS[@]}" "${DOCKER_MOUNTS[@]}" "$ANALYSIS_IMAGE" "${ANALYSIS_ARGS[@]}"

# docker "${DOCKER_OPTS[@]}" "${DOCKER_MOUNTS[@]}" "$ANALYSIS_IMAGE" "${ANALYSIS_ARGS[@]}"

DOCKER_EXIT_CODE=$?

if [[ $PACKAGE_DEFINED -eq 1 ]]; then
echo
echo $LINE
	if [[ $DOCKER_EXIT_CODE -eq 0 ]]; then
		echo "Finished analysis"
		echo
		print_package_details
		print_results_dirs
	else
		echo "Analysis failed"
		echo
		echo "docker process exited with code $DOCKER_EXIT_CODE"
		echo
		print_package_details
	fi

echo $LINE
fi

exit $DOCKER_EXIT_CODE
