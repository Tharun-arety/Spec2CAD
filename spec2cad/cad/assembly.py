"""Assembly public API; kernel work remains isolated in cad.executor."""

from spec2cad.cad.executor import AssemblyCheck, AssemblyResult, execute_assembly

__all__ = ["AssemblyCheck", "AssemblyResult", "execute_assembly"]
