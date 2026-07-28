"""
Router wrapper for webhook endpoint backward compatibility.
"""

from app.api.endpoints.webhook import router

__all__ = ["router"]
