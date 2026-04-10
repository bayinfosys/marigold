"""Usage tracking and metrics.

ModelUsageStats is defined here rather than in api/models.py so that
handler modules and shared infrastructure can import it without depending
on the API layer.
"""

import json
import logging
import os
from datetime import datetime

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Usage stats model
# ---------------------------------------------------------------------------


class ModelUsageStats(BaseModel):
    """Timing and resource statistics for one inference request.

    Not all fields are relevant for all model types; token counts are zero
    for image-in/image-out models.
    """

    duration:     float = Field(..., description="total process duration in seconds")
    inference:    float = Field(..., description="model inference duration in seconds")
    input_tokens: int   = Field(0,   description="number of input tokens")
    output_tokens: int  = Field(0,   description="number of output tokens")
    memory_usage: int   = Field(..., description="peak process memory in KB")
