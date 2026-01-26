#!/usr/bin/env bash
set -euo pipefail

unset AWS_DEFAULT_PROFILE

export AWS_BUCKET_NAME="dagster"
export AWS_ACCESS_KEY_ID="minioadmin"
export AWS_SECRET_ACCESS_KEY="minioadmin"
export AWS_DEFAULT_REGION="us-east-1"
export AWS_ENDPOINT_URL="http://localhost:9000"

aws s3 ls "s3://$AWS_BUCKET_NAME/" \
  --endpoint-url "$AWS_ENDPOINT_URL" \
  --no-verify-ssl \
  --recursive


# list all buckets
# aws s3 

# aws s3 get file
# filepath="f9896ce9-0a72-4916-9f23-248c9f4f4d3e/simulated_data_centre_1/simulated_data_centre_1.json"
# echo "Copying S3 content $filepath
# aws s3 cp \
#     "s3://$AWS_BUCKET_NAME/artifacts/$filepath" \
#     "./data/simulated_data_centre_1.json" \
#     --endpoint-url "$AWS_ENDPOINT_URL"


# list s3 objects and group with file counts per directory prefix
# echo "Listing S3 bucket contents at s3://$AWS_BUCKET_NAME/artifacts/ ..."
# aws s3 ls "s3://$AWS_BUCKET_NAME/artifacts/" \
#     --endpoint-url "$AWS_ENDPOINT_URL" \
#     --recursive
    # awk '
    # {
    #     # Extract directory prefix (up to the last slash)
    #     match($4, /^(artifacts\/[^\/]+)/, m)
    #     if (m[1] != "") {
    #         prefix = m[1]
    #         count[prefix]++
    #         # Store timestamp and size of last file for display (arbitrary choice)
    #         ts[prefix]=$1" "$2
    #         size[prefix]=$3
    #     }
    # }
    # END {
    #     for (p in count) {
    #         printf "%s %12d %s (%d files)\n", ts[p], size[p], p, count[p]
    #     }
    # }' | sort

# echo "Removing all objects from S3 bucket at s3://$AWS_BUCKET_NAME/artifacts/ ...""
# aws s3 rm s3://$AWS_BUCKET_NAME/artifacts/ \
#     --endpoint-url "$AWS_ENDPOINT_URL" \p
#     --recursive
