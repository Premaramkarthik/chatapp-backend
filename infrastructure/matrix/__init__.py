"""Matrix Synapse integration package."""

from infrastructure.matrix.admin import SynapseAdminClient, synapse_admin_client
from infrastructure.matrix.health import MatrixHealthResult, matrix_health

__all__ = [
    "MatrixHealthResult",
    "SynapseAdminClient",
    "matrix_health",
    "synapse_admin_client",
]
