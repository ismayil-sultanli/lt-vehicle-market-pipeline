FROM apache/airflow:3.4.0-python3.11

# The pipeline gets its own virtualenv: dbt and Airflow pin conflicting
# versions of shared libraries, and Airflow only needs to shell out to it.
USER root
RUN python -m venv /opt/lvm-venv && chown -R airflow /opt/lvm-venv
USER airflow

COPY --chown=airflow pyproject.toml README.md constraints.txt /opt/project/
COPY --chown=airflow src /opt/project/src
# PIP_USER is switched off explicitly: the base image may enable user installs,
# which pip refuses inside a virtualenv.
RUN PIP_USER=false /opt/lvm-venv/bin/pip install --no-cache-dir "/opt/project[s3]" \
    -c /opt/project/constraints.txt

# Baked in so the image runs on its own; docker-compose mounts both for development.
COPY --chown=airflow dbt /opt/project/dbt
COPY --chown=airflow airflow/dags /opt/airflow/dags

ENV LVM_PROJECT_DIR=/opt/project \
    LVM_BIN=/opt/lvm-venv/bin \
    LVM_DATA_DIR=/opt/project/data
