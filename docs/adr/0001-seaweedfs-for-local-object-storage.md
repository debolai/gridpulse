# ADR-0001: Use SeaweedFS, not MinIO, as local S3 storage

Status: Accepted
Date: 2026-10-12

## Context
The plan named MinIO as the local stand-in for S3. When A1 was built, `minio/minio` no longer existed on Docker Hub (404) and Quay had no tags: MinIO stopped publishing community images in 2025. Pinning an old copy would mean running unmaintained software.

## Decision
Use SeaweedFS (`chrislusf/seaweedfs:4.47`, Apache 2.0) in its single-process `mini` mode as the local S3 endpoint. It pre-creates the `gridpulse-local-raw` and `gridpulse-local-lake` buckets on startup.

## Alternatives considered
- Old MinIO image pinned by digest: unmaintained, no security fixes.
- RustFS 1.0: MinIO-compatible, but only reached 1.0 in September 2026.
- Garage: AGPL, and its S3 coverage is narrower.

## Consequences
- Lakekeeper's own minimal example uses SeaweedFS, so the catalog pairing is well trodden.
- Light footprint: about 120 MB RAM idle.
- Nothing outside `local/` refers to the storage product. Code only sees an S3 endpoint, so switching again is a compose-file change.
