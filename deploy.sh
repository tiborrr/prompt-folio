#!/bin/bash

# Deploy script for prompt-folio
# This script builds the Docker images locally, pushes them to the registry, and syncs config to BRUG_TOT_BRUG

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Configuration
export IMAGE_TAG="v$(date +%Y%m%d%H%M%S)"
export DOCKER_DEFAULT_PLATFORM=linux/amd64

# Helper to get or prompt for env var
get_or_prompt_env() {
    local var_name=$1
    local default_value=$2
    local prompt_text=$3
    
    local current_value=""
    if [ -f .env ]; then
        current_value=$(grep -E "^${var_name}=" .env | cut -d '=' -f 2- | tr -d '"' | tr -d "'")
    fi
    
    # Check if the variable is entirely missing from the file
    if ! grep -q -E "^${var_name}=" .env 2>/dev/null; then
        echo -e "${YELLOW}Missing configuration: ${var_name}${NC}" >&2
        read -p "${prompt_text} [${default_value}]: " user_input
        current_value="${user_input:-$default_value}"
        
        echo "${var_name}=${current_value}" >> .env
        print_success "Saved ${var_name}=${current_value} to .env" >&2
    fi
    
    export "${var_name}=${current_value}"
}

if [ ! -f .env ]; then
    print_warning ".env file not found! We will create one for you."
    touch .env
fi

get_or_prompt_env "REMOTE_HOST" "BRUG_TOT_BRUG" "Enter your SSH Remote Host (e.g., server IP or ~/.ssh/config alias)"
get_or_prompt_env "REMOTE_PATH" "/root/deployments/prompt-folio" "Enter the absolute path on the remote host for deployment"
get_or_prompt_env "DOCKER_REGISTRY" "registry.casteleijn.com" "Enter your Docker Registry URL (leave empty for Docker Hub)"
get_or_prompt_env "DOCKER_IMAGE_NAME" "prompt-folio" "Enter your Docker Image/Repository Name"
get_or_prompt_env "PORT" "3005" "Enter the local port to run the application on"

command_exists() { command -v "$1" >/dev/null 2>&1; }

check_dependencies() {
    print_status "Checking dependencies..."
    if ! command_exists docker; then print_error "Docker is not installed or not in PATH"; exit 1; fi
    if ! command_exists rsync; then print_error "rsync is not installed or not in PATH"; exit 1; fi
    if ! command_exists ssh; then print_error "ssh is not installed or not in PATH"; exit 1; fi
    print_success "All dependencies are available"
}

build_images() {
    print_status "Building Docker images with tag ${IMAGE_TAG}..."
    docker compose build -q
    print_success "Docker images built successfully"
}

push_images() {
    print_status "Pushing Docker images to registry..."
    docker compose push -q
    print_success "Docker images pushed successfully"
}

sync_to_remote() {
    print_status "Syncing configuration to ${REMOTE_HOST}:${REMOTE_PATH}"
    if ! ssh -o ConnectTimeout=10 "${REMOTE_HOST}" "echo 'SSH connection successful'" >/dev/null 2>&1; then
        print_error "Cannot connect to ${REMOTE_HOST}. Please check your SSH configuration."
        exit 1
    fi
    ssh "${REMOTE_HOST}" "mkdir -p ${REMOTE_PATH}/private && chown -R 999:999 ${REMOTE_PATH}/private"
    
    FILES_TO_SYNC=("docker-compose.yml")
    
    rsync -avzR --progress "${FILES_TO_SYNC[@]}" "${REMOTE_HOST}:${REMOTE_PATH}"
    print_success "Successfully synced configuration to ${REMOTE_HOST}:${REMOTE_PATH}"
}

deploy_on_remote() {
    print_status "Deploying on remote server ${REMOTE_HOST}..."
    print_status "Pulling images and starting application with docker compose..."
    ssh "${REMOTE_HOST}" "cd ${REMOTE_PATH} && export IMAGE_TAG=\"${IMAGE_TAG}\" && docker compose pull -q && docker compose up -d"
    
    print_status "Checking running containers..."
    ssh "${REMOTE_HOST}" "cd ${REMOTE_PATH} && docker compose ps"
    
    print_status "Cleaning up dangling images..."
    ssh "${REMOTE_HOST}" "docker image prune -f"
    print_success "Deployment completed on remote server!"
}

cleanup_registry() {
    print_status "Cleaning up old images from registry..."
    
    if ! command_exists jq; then
        print_warning "jq is not installed. Skipping registry cleanup."
        return
    fi
    
    local config_file="$HOME/.docker/config.json"
    if [ ! -f "$config_file" ]; then
        print_warning "Docker config not found. Skipping registry cleanup."
        return
    fi
    
    local auth=""
    local creds_store=$(jq -r '.credsStore // empty' "$config_file")
    if [ -n "$creds_store" ] && command_exists "docker-credential-$creds_store"; then
        local creds_json=$(echo "${DOCKER_REGISTRY}" | "docker-credential-$creds_store" get 2>/dev/null || echo "")
        local user=$(echo "$creds_json" | jq -r '.Username // empty')
        local secret=$(echo "$creds_json" | jq -r '.Secret // empty')
        if [ -n "$user" ] && [ -n "$secret" ]; then
            auth=$(echo -n "${user}:${secret}" | base64)
        fi
    fi
    
    if [ -z "$auth" ]; then
        auth=$(jq -r ".auths[\"${DOCKER_REGISTRY}\"].auth // empty" "$config_file")
    fi
    
    if [ -z "$auth" ]; then
        print_warning "No auth token found for ${DOCKER_REGISTRY} in Docker config. Skipping cleanup."
        return
    fi
    
    local repos=("${DOCKER_IMAGE_NAME}")
    local keep=3
    
    for repo in "${repos[@]}"; do
        print_status "Cleaning up ${repo}..."
        local tags_json=$(curl -s -H "Authorization: Basic $auth" "https://${DOCKER_REGISTRY}/v2/${repo}/tags/list")
        
        # Check if tags is null or empty
        local has_tags=$(echo "$tags_json" | jq -e '.tags != null')
        if [ "$has_tags" != "true" ]; then
            continue
        fi
        
        local tags=($(echo "$tags_json" | jq -r '.tags[] | select(. != "latest")' | sort))
        
        if [ ${#tags[@]} -le $keep ]; then
            print_status "Found ${#tags[@]} tags. Keeping all."
            continue
        fi
        
        local delete_count=$((${#tags[@]} - keep))
        for (( i=0; i<$delete_count; i++ )); do
            local tag="${tags[$i]}"
            
            (
                print_status "Deleting old tag: ${tag}"
                
                # Get digest
                local digest=$(curl -s -I -H "Authorization: Basic $auth" \
                    -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
                    -H "Accept: application/vnd.docker.distribution.manifest.list.v2+json" \
                    -H "Accept: application/vnd.oci.image.manifest.v1+json" \
                    -H "Accept: application/vnd.oci.image.index.v1+json" \
                    "https://${DOCKER_REGISTRY}/v2/${repo}/manifests/${tag}" | grep -i "^Docker-Content-Digest:" | awk '{print $2}' | tr -d '\r')
                    
                if [ -n "$digest" ]; then
                    curl -s -X DELETE -H "Authorization: Basic $auth" "https://${DOCKER_REGISTRY}/v2/${repo}/manifests/${digest}" > /dev/null
                    print_success "Deleted ${repo}:${tag}"
                else
                    print_warning "Could not get digest for ${tag}"
                fi
            ) &
            
            # Wait after every 10 requests to avoid rate limits
            if (( (i + 1) % 10 == 0 )); then
                wait
            fi
        done
        wait # Wait for any remaining background jobs
    done
}

show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --no-deploy      Skip automatic deployment (sync only)"
    echo "  --help          Show this help message"
}

SKIP_DEPLOY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-deploy) SKIP_DEPLOY=true; shift ;;
        --help) show_usage; exit 0 ;;
        *) print_error "Unknown option: $1"; show_usage; exit 1 ;;
    esac
done

main() {
    print_status "Starting deployment process..."
    print_status "Target Tag: ${IMAGE_TAG}"
    print_status "Remote: ${REMOTE_HOST}:${REMOTE_PATH}"
    
    check_dependencies
    build_images
    push_images
    sync_to_remote
    
    if [ "$SKIP_DEPLOY" = false ]; then
        deploy_on_remote
    else
        print_status "Manual deployment required. Run the following on ${REMOTE_HOST}:"
        print_status "  1. SSH to ${REMOTE_HOST}"
        print_status "  2. cd ${REMOTE_PATH}"
        print_status "  3. export IMAGE_TAG=\"${IMAGE_TAG}\" && docker compose pull && docker compose up -d"
    fi
    
    cleanup_registry
    print_success "Deployment process completed!"
}

main "$@"
