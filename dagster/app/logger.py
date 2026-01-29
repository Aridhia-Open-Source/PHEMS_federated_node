from typing import Any, Mapping
from typing_extensions import Self

import boto3
import dagster as dg
from dagster._serdes import ConfigurableClassData
from boto3.session import Session # NOQA
from dagster_aws.s3.compute_log_manager import S3ComputeLogManager

# TODO: REMOVE THIS PRINT AFTER TESTING
print("S3ComputeLogManagerExtended MODULE LOADED")


class S3ComputeLogManagerExtended(S3ComputeLogManager):
    """
    Extends S3ComputeLogManager to support static AWS credentials.

    Adds:
        - `access_key`: AWS access key ID
        - `secret_key`: AWS secret access key
    """

    def __init__(
        self,
        bucket,
        local_dir=None,
        inst_data=None,
        prefix="dagster",
        use_ssl=True,
        verify=True,
        verify_cert_path=None,
        endpoint_url=None,
        skip_empty_files=False,
        upload_interval=None,
        upload_extra_args=None,
        show_url_only=False,
        region=None,
        access_key=None,
        secret_key=None,
    ):
        super().__init__(
            bucket=bucket,
            local_dir=local_dir,
            inst_data=inst_data,
            prefix=prefix,
            use_ssl=use_ssl,
            verify=verify,
            verify_cert_path=verify_cert_path,
            endpoint_url=endpoint_url,
            skip_empty_files=skip_empty_files,
            upload_interval=upload_interval,
            upload_extra_args=upload_extra_args,
            show_url_only=show_url_only,
            region=region,
        )

        boto3_session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        self._s3_session = boto3_session.client(
            "s3",
            use_ssl=use_ssl,
            endpoint_url=endpoint_url,
            verify=False if not verify else verify_cert_path,
        )

    @classmethod
    def config_type(cls):
        """Extend Dagster config schema with access/secret keys."""
        return {
            **super().config_type(),
            "access_key": dg.Field(dg.StringSource, is_required=False),
            "secret_key": dg.Field(dg.StringSource, is_required=False),
        }

    @classmethod
    def from_config_value(
        cls, inst_data: ConfigurableClassData, config_value: Mapping[str, Any]
    ) -> Self:
        return cls(inst_data=inst_data, **config_value)
