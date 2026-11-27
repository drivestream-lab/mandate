"""Temporal workflow definitions. The only package that may import temporalio.workflow.

Workflows call business-service activities by name (ActivityNameType) with the Pydantic
models in src/models/workflow_activity_models.py, never by importing a business service.
"""
