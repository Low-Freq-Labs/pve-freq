"""VM domain API handlers — /api/v1/vm/*.

Provides REST endpoints for virtual machine lifecycle operations.
Maps 1:1 to `freq vm` CLI domain.

Routes registered here will be served by serve.py's HTTP handler.
During migration, existing /api/ routes remain in serve.py.
New v1 routes go here.
"""


def register(routes: dict):
    """Register VM API routes."""
    # New v1 API routes will be added here as features are built
    # Example: routes["/api/v1/vm/list"] = "_api_vm_list"
    pass
