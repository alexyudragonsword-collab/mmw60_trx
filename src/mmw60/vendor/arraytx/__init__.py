# Vendored from array_tx@5815c5a7ea43143fd58502d4894ac840b5b5fb86: src/arraytx/__init__.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""array_tx: behavioral simulation of multi-element array transmitters.

Each element is one vendored polar_tx chain; this package adds the array
layer (mutual coupling inside the chain, true-bandwidth beam squint,
array-level DPD) and reads every acceptance metric in the far field.
"""

__version__ = "0.1.0"

from .config import ArrayConfig, config_from_dict, default_config, form_fields, load_config  # noqa: E402
from .sim import ArrayResult, ArraySim  # noqa: E402

__all__ = ["ArrayConfig", "ArrayResult", "ArraySim", "config_from_dict", "default_config",
           "form_fields", "load_config", "__version__"]
