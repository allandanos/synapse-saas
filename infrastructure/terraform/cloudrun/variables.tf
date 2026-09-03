# Variables live in main.tf next to their consumers for a single-file read.
# This file exists to hold tfvars documentation for the apply command:
#
#   terraform apply -var='project_id=my-project' \
#                   -var='database_url=postgresql+asyncpg://…' \
#                   -var='secret_key=…' \
#                   -var='api_image=asia-southeast1-docker.pkg.dev/my-project/synapse/api:1' \
#                   -var='web_origin=https://console.example.com'
#
# Prefer a terraform.tfvars file (gitignored) over -var flags for real runs.
