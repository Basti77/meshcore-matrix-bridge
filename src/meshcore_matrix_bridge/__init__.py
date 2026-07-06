"""meshcore-matrix-bridge — bridge between a MeshCore Companion node and Matrix."""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("meshcore-matrix-bridge")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0.dev0"
