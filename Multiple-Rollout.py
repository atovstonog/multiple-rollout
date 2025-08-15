import subprocess
import json
import time
import sys
import redis
import os

### Static vars
### Setting default rollout state
isRollout = False

### Name of the rollout service
service = str(sys.argv[1])

### K8s variables
namespace = os.environ["NAMESPACE"]
kubectlConfig = os.environ["K8S_KUBECONFIG"]

### Current Jenkins build number
jenkinsBuildNumber = os.environ["BUILD_NUMBER"]

### Commit hash of the GitOps repository
commitHashGitOps = os.environ["COMMIT_HASH_GITOPS"]

### Argocd varibales
argocdApiKey = os.environ["ARGOCD_KEY"]
argocdApplication = os.environ["ARGOCD_APP_PROJECT_NAME"]
argocdServer = os.environ["ARGOCD_SERVER"]

### Local vars for Redis keys
redisKeyTtl = 3600

# Declare a dictionary to store container information
containersMap = {}

# Setting connection to the redis
redis = redis.Redis(host='redis', port=6379, db=0)

### Defining default current rollout state
currentRolloutState = {}

### Defining static states. Last variable is dynamic and come from os environment variable
rolloutStateSkip0 = {
  "applicationSyncStatus": "Synced",
  "applicationHealthStatus": "Healthy",
  "applicationOperationStatePhase": "Succeeded",
  "applicationSyncRevision": commitHashGitOps
}

rolloutStateSkip1 = {
  "applicationSyncStatus": "Synced",
  "applicationHealthStatus": "Healthy",
  "applicationOperationStatePhase": "Running",
  "applicationSyncRevision": commitHashGitOps
}

rolloutStateFail0 = {
  "applicationSyncStatus": "Synced",
  "applicationHealthStatus": "Degraded",
  "applicationOperationStatePhase": "Failed",
  "applicationSyncRevision": commitHashGitOps
}

rolloutState0 = {
  "applicationSyncStatus": "OutOfSync",
  "applicationHealthStatus": "Suspended",
  "applicationOperationStatePhase": "Running",
  "applicationSyncRevision": commitHashGitOps
}

rolloutState1 = {
  "applicationSyncStatus": "Synced",
  "applicationHealthStatus": "Suspended",
  "applicationOperationStatePhase": "Running",
  "applicationSyncRevision": commitHashGitOps
}


### Getting application statuses: Sync, Health, Operation phase and Revision
### Returning object of the vars
def getApplicationStatus(argocdApiKey,argocdServer,argocdApplication,max_retries=4,retry_delay=2):
    for attempt in range(1, max_retries + 1):
        command = [
            "argocd", "app", "get", argocdApplication, "--auth-token", argocdApiKey, "--server", argocdServer, "--output", "json"
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        
        try:
            data = json.loads(result.stdout)
            applicationSyncStatus = data['status']['sync']['status']
            applicationSyncRevision = data['status']['sync']['revision']
            applicationHealthStatus = data['status']['health']['status']
            applicationOperationStatePhase = data['status']['operationState']['phase']
            return {
                    "applicationSyncStatus": applicationSyncStatus,
                    "applicationHealthStatus": applicationHealthStatus,
                    "applicationOperationStatePhase": applicationOperationStatePhase,
                    "applicationSyncRevision": str(applicationSyncRevision[0:7])
                }

        except KeyError as e:
            print(f"KeyError: {e} not found in the response.")
            # Handle the error or exit gracefully.
        except json.JSONDecodeError as e:
            print(f"JSONDecodeError: {e}")
            # Handle the error or exit gracefully.
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            # Handle the error or exit gracefully.
        if attempt < max_retries:
            print(f"Retrying... Attempt {attempt}/{max_retries}")
            time.sleep(retry_delay)
    print(f"Max retries reached. Unable to get application status.")
    return None  # Return None or an appropriate value if retries fail


### Getting application suspended state
### Calling function getApplicationStatus that returning object of the application state vars
### Returning variable that containing object of the vars
def isApplicationSuspended(argocdApiKey,argocdServer,argocdApplication):
    currentRolloutState = getApplicationStatus(argocdApiKey,argocdServer,argocdApplication)
    return currentRolloutState

### Getting current replicaset ID that already deployed
### Returning current stable replicaset ID
def getStableReplicasetId(service):
    # Getting stable RS hash
    command = [
        "kubectl", "--kubeconfig=" + kubectlConfig, "-n", namespace, "get", "rollouts.argoproj.io", service, "-o", "json"
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    data = json.loads(result.stdout)
    stableRsId = data['status']['stableRS']
    return stableRsId

### Getting new replicaset ID that has not rollout yet
### Returning new replicaset ID that not rollouts
def getNewReplicasetId(service):
    # Getting new RS hash
    command = [
        "kubectl", "--kubeconfig=" + kubectlConfig, "-n", namespace, "get", "rollouts.argoproj.io", service, "-o", "json"
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    data = json.loads(result.stdout)
    newRsId = data['status']['currentPodHash']
    return newRsId

### Getting container status that has been deployed in the prerelease state
### Returning variable that contain count of the pod restarts
def getContainerStatus(service,newRsId,max_retries=4,retry_delay=2):
    for attempt in range(1, max_retries + 1):
        command = [
            "kubectl", "--kubeconfig=" + kubectlConfig, "-n", namespace, "get", "pods", "-l", "rollouts-pod-template-hash=" + newRsId, "-o", "json"
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        
        try:
            data = json.loads(result.stdout)
            newContainerStatuses = [pod['status']['containerStatuses'] for pod in data['items']]
            return newContainerStatuses
        
        except KeyError as e:
            print(f"KeyError: {e} not found in the response.")
            # Handle the error or exit gracefully.
        except json.JSONDecodeError as e:
            print(f"JSONDecodeError: {e}")
            # Handle the error or exit gracefully.
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            # Handle the error or exit gracefully.
        if attempt < max_retries:
            print(f"Retrying... Attempt {attempt}/{max_retries}")
            time.sleep(retry_delay)

    print(f"Max retries reached. Unable to get application status.")
    return None  # Return None or an appropriate value if retries fail

### Create a new associative array consisting of the service name and the number of restarts
### Perform a check for a time based on an OS environment variable
### Returning associative array
def createArray(service, newReplicasetId):

    containerStatuses = getContainerStatus(service, newReplicasetId)
    for containers in containerStatuses:
        for container in containers:
            containersMap[container['name']] = str(container['restartCount'])
    return containersMap

### Getting rollout state based on the associative array from function createArray
### Returning isRollout boolean variable
def setRolloutStatus():
    isRollout = False
    for value in containersMap.values():
        if int(value) > 0:
            isRollout = False
            break
        else:
            isRollout = True
    return isRollout

### Setting isRollout state in Redis. The Redis key consists of the current Jenkins build number and the service name
def setRedisKey(service, jenkinsBuildNumber, isRollout):
    redisKey = str(jenkinsBuildNumber) + '-' + service
    redis.set(redisKey, str(isRollout))
    redis.expire(redisKey, redisKeyTtl)

### Getting the isRollout state
def getRedisKey(service, jenkinsBuildNumber):
    redisKey = str(jenkinsBuildNumber) + '-' + service
    result = redis.get(redisKey)
    return result

### Running the main script logic
print("Checking ArgoCD app status")
currentRolloutState = isApplicationSuspended(argocdApiKey,argocdServer,argocdApplication)
stableReplicasetId = getStableReplicasetId(service)
newReplicasetId = getNewReplicasetId(service)

print("Stable RS: " + str(stableReplicasetId))
print("New RS: " + str(newReplicasetId))
print("GitOps revision: " + str(commitHashGitOps))
print(currentRolloutState)

print("Start rollout checks")

### Comparing of states that are defined in variables at the beginning of the script

### Checking that application changed or not
if (currentRolloutState == rolloutStateSkip0 or currentRolloutState == rolloutStateSkip1):
      print("Application not changed")
      isRollout = "Skip"
      print("Setting dummy Redis key")
      setRedisKey(service, jenkinsBuildNumber, isRollout)
else:
    while (currentRolloutState != rolloutState0 and currentRolloutState != rolloutState1):
      currentRolloutState = getApplicationStatus(argocdApiKey,argocdServer,argocdApplication)
      print(currentRolloutState)
      print("********")
      time.sleep(5)
      isRollout = True
      if (currentRolloutState == rolloutStateFail0):
          isRollout = False
          print("Setting Redis key")
          setRedisKey(service, jenkinsBuildNumber, isRollout)
          break
      elif (currentRolloutState == rolloutStateSkip0 or currentRolloutState == rolloutStateSkip1):
          isRollout = "Skip"
          print("Setting Redis key")
          setRedisKey(service, jenkinsBuildNumber, isRollout)
          break
    

### Setting Redis key based on rollout state that getting from previous if statement
    if (isRollout == False or isRollout == "Skip"):
        print("Is rollout: " + str(isRollout))
        print("Setting Redis key")
        setRedisKey(service, jenkinsBuildNumber, isRollout)
    else:
        print("Generating new dictionary")
        createArray(service, newReplicasetId)
        print("Getting rollout state")
        isRollout = setRolloutStatus()
        print("Setting Redis key")
        setRedisKey(service, jenkinsBuildNumber, isRollout)