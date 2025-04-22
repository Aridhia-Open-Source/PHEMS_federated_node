#!/bin/sh

deleteEntity(){
    echo "Checking for $1"
    kubectl get "$1" -n "$2" -o json | jq -r --arg date "$date" \
        '.items[].metadata | select(.labels.delete_by != null and (.labels.delete_by | strptime("%Y%m%d") | strftime("%Y-%m-%d")) <= ( $date | strptime("%Y-%m-%d") | strftime("%Y-%m-%d"))) | .name' | \
        xargs kubectl delete "$1" -n "$2" || echo "Nothing to delete"
}

date=$(date +%Y-%m-%d -d "${CLEANUP_AFTER_DAYS} days ago")
deleteEntity pods "${NAMESPACE}"
deleteEntity pvc "${NAMESPACE}"
deleteEntity pv "${NAMESPACE}"
find "${RESULTS_PATH}/" -type d -mtime "+${CLEANUP_AFTER_DAYS}" -name '*' -print0 | xargs -r0 rm -r --
