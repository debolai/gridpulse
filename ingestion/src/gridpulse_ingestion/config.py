"""Runtime settings, read from environment variables (and `.env` when present).

Local defaults point at the compose stack; on AWS the same names are set by the pod spec.
"""

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GRIDPULSE_", env_file=".env", extra="ignore")

    eia_api_key: SecretStr = Field(validation_alias="EIA_API_KEY")
    eia_base_url: str = "https://api.eia.gov/v2"
    eia_page_size: int = Field(default=5000, ge=1, le=5000)
    eia_requests_per_second: float = Field(default=1.0, gt=0)
    eia_max_attempts: int = Field(default=5, ge=1)
    eia_timeout_seconds: float = 60.0

    raw_bucket: str = "gridpulse-local-raw"
    s3_endpoint: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: SecretStr | None = None
    s3_region: str = "us-east-1"

    catalog_type: Literal["rest", "glue"] = "rest"
    catalog_uri: str = "http://lakekeeper:8181/catalog"
    catalog_warehouse: str = "gridpulse"
    raw_namespace: str = "raw"

    def s3_properties(self) -> dict[str, str]:
        """PyIceberg/boto-style S3 properties; empty values fall back to the AWS default chain."""
        props = {"s3.region": self.s3_region}
        if self.s3_endpoint:
            props["s3.endpoint"] = self.s3_endpoint
        if self.s3_access_key and self.s3_secret_key:
            props["s3.access-key-id"] = self.s3_access_key
            props["s3.secret-access-key"] = self.s3_secret_key.get_secret_value()
        return props
