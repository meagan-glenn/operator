from .bdr import BDR_TOOLS
from .calendar import CALENDAR_TOOLS
from .crm import CRM_TOOLS
from .discovery import DISCOVERY_TOOLS
from .gcal import GCAL_TOOLS
from .linkedin import LINKEDIN_TOOLS
from .memory import MEMORY_TOOLS

# The full toolset Operator can use. Group tools by module and combine here.
OPERATOR_TOOLS = (
    CRM_TOOLS + CALENDAR_TOOLS + GCAL_TOOLS + MEMORY_TOOLS + BDR_TOOLS + DISCOVERY_TOOLS + LINKEDIN_TOOLS
)

__all__ = [
    "OPERATOR_TOOLS",
    "CRM_TOOLS",
    "CALENDAR_TOOLS",
    "GCAL_TOOLS",
    "MEMORY_TOOLS",
    "BDR_TOOLS",
    "DISCOVERY_TOOLS",
    "LINKEDIN_TOOLS",
]
