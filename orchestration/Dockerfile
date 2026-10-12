# Airflow 3 for GridPulse. Tasks run in their own images (extractor, dbt) via DockerOperator
# locally and KubernetesPodOperator on EKS (phase B2), so this image carries only Airflow,
# its providers and the DAG files. Provider versions come from Airflow's constraints file.
FROM apache/airflow:slim-3.3.2-python3.12@sha256:a54e7bd6c4d7a17e55cd14b0ead257877b8f8111680d2692cbdba2ff32bd3ff3
LABEL com.gridpulse.project=gridpulse com.gridpulse.component=orchestration
ARG AIRFLOW_VERSION=3.3.2
ARG CONSTRAINTS=https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-3.12.txt
USER airflow
RUN pip install --no-cache-dir "apache-airflow[postgres,docker]==${AIRFLOW_VERSION}" --constraint "${CONSTRAINTS}"
# Baked in for deployments (an image tag pins exactly which DAG code ran); mounted over locally.
COPY --chown=airflow:root orchestration/dags /opt/airflow/dags
COPY --chown=airflow:root orchestration/tests /opt/airflow/tests
