# Full Catalog recovery provenance

Historical Project Manager Docker diagnostics are restored from exact Git blobs from commit 174318df1cb739a816553b7ccd3ec0851fe79f2f:

- project_manager_tools.py: ec9b99ee46f41f9da4c783a3bb1e1f53c5202663
- project_manager_operations.py: 5ecbb59c19b02157b3aef6cb68d6ce29d5c2958c

Do not modify these historical source files to add current container prefixes. Configure PROJECT_DOCKER_ALLOWED_PREFIXES in the isolated candidate runtime environment instead.

Production cutover is not authorized by this recovery checkpoint.
