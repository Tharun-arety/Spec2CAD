"""Single product import boundary for the CadQuery package.

Legacy executor, selector and measurement modules receive the kernel namespace
through this facade while they are folded into the adapter incrementally.
"""

import cadquery as cq

__all__ = ["cq"]
