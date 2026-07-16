"""CMS/CRM adapters behind one interface.

The interface (`base.CaseManagementProvider`) and the normalized schema
(`models`) are the moat; each provider adapter is an instance. The
orchestration layer and workers never know which system a firm runs.
"""

from integrations.base import CaseManagementProvider, ProviderError, get_provider_class
from integrations.models import Contact, Lead, Matter, Note, Task

__all__ = [
    "CaseManagementProvider",
    "ProviderError",
    "get_provider_class",
    "Contact",
    "Lead",
    "Matter",
    "Note",
    "Task",
]
