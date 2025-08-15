# Rollout Status Checker Script

## Description
This Python script automates the process of monitoring and validating application rollouts in a Kubernetes environment managed via **ArgoCD**.  
It is designed to be executed in a **Jenkins pipeline** and uses **Redis** to store the rollout status for later retrieval.

## Features
- **Environment & Pipeline Variables** – Reads Kubernetes, ArgoCD, and Jenkins configuration from environment variables.
- **ArgoCD Status Checks** – Retrieves sync status, health status, operation state, and deployed Git revision from the ArgoCD API.
- **ReplicaSet Identification** – Finds both the stable and newly deployed ReplicaSet IDs for the target service.
- **Rollout Monitoring** – Continuously checks rollout progress until it completes, fails, or is skipped.
- **Container Restart Validation** – Counts container restarts in the new ReplicaSet to detect rollout issues.
- **Redis Integration** – Stores rollout status (`True`, `False`, or `"Skip"`) in Redis with a TTL, keyed by Jenkins build number and service name.
- **Retry Mechanism** – Retries API calls with delays when responses are incomplete or errors occur.
- **Skip Logic** – Skips checks when no application changes are detected.

## Required Environment Variables

- `NAMESPACE` – Kubernetes namespace  
- `K8S_KUBECONFIG` – Path to kubeconfig file  
- `BUILD_NUMBER` – Jenkins build number  
- `COMMIT_HASH_GITOPS` – GitOps commit hash  
- `ARGOCD_KEY` – ArgoCD API key  
- `ARGOCD_APP_PROJECT_NAME` – ArgoCD application name  
- `ARGOCD_SERVER` – ArgoCD server address  

## How It Works

1. Reads configuration and Jenkins build metadata.  
2. Gets the ArgoCD application status.  
3. Retrieves stable and new ReplicaSet IDs.  
4. Monitors application state until it matches rollout success/failure/skip conditions.  
5. Checks container restart counts in the new ReplicaSet.  
6. Stores the rollout result in Redis for use in later pipeline stages.  
