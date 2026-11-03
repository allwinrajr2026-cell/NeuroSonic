"""Online scene description (cloud vision), provider-independent. See assistant.py.

Local walking guidance (neurosonic/awareness.py, neurosonic/pathguide.py) never imports this package."""
from .assistant import SceneAssistant, compose_speech, filter_text, is_spoken_text_safe
from .base import (BadResponse, NotConfigured, ProviderRateLimited, ProviderTimeout, ProviderUnavailable, Rejected,
                   SceneRequest, VisionError, VisionProvider, parse_scene, scrub)
from .mock import MockProvider
