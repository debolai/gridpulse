# Airflow 3 for GridPulse. Tasks run in their own images (extractor, dbt, agent) via
# DockerOperator locally and KubernetesPodOperator on k3d/EKS, so this image carries only
# Airflow, its providers, Cosmos and the DAG files. Provider versions come from Airflow's
# constraints file; Cosmos isn't in it, so it is pinned here.
# Build from the repo root after the transform image (its dbt manifest is copied in):
#   docker build -f orchestration/Dockerfile --build-arg TRANSFORM_IMAGE=gridpulse/transform:<tag> .
ARG TRANSFORM_IMAGE=gridpulse/transform:local
FROM ${TRANSFORM_IMAGE} AS dbt

FROM apache/airflow:slim-3.3.2-python3.12@sha256:a54e7bd6c4d7a17e55cd14b0ead257877b8f8111680d2692cbdba2ff32bd3ff3
LABEL com.gridpulse.project=gridpulse com.gridpulse.component=orchestration
ARG AIRFLOW_VERSION=3.3.2
ARG COSMOS_VERSION=1.15.1
ARG CONSTRAINTS=https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-3.12.txt
USER airflow
RUN pip install --no-cache-dir \
      "apache-airflow[postgres,docker,cncf.kubernetes,slack]==${AIRFLOW_VERSION}" \
      "astronomer-cosmos==${COSMOS_VERSION}" \
      --constraint "${CONSTRAINTS}"
# The dbt graph Cosmos renders and the weather stations the NOAA DAG loads (one source of truth).
COPY --from=dbt --chown=airflow:root /app/transform/target/manifest.json /opt/airflow/dbt/manifest.json
COPY --chown=airflow:root transform/seeds/ba_weather_stations.csv /opt/airflow/dbt/ba_weather_stations.csv
# Baked in for deployments (an image tag pins exactly which DAG code ran); mounted over locally.
COPY --chown=airflow:root orchestration/dags /opt/airflow/dags
COPY --chown=airflow:root orchestration/tests /opt/airflow/tests
