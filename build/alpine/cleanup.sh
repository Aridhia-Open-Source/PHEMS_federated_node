#!/bin/sh

find "${RESULTS_PATH}" -type d -mtime "+${CLEANUP_AFTER_DAYS}" -name '*' -print0 | xargs -r0 rm -r --
kubectl delete pods -n "${NAMESPACE}" -l "delete_by=$(date +%Y%m%d)"
kubectl delete pvc -n "${NAMESPACE}" -l "delete_by=$(date +%Y%m%d)"
kubectl delete pv -n "${NAMESPACE}" -l "delete_by=$(date +%Y%m%d)"
