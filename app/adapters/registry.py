import logging
from urllib.parse import urlparse
from .base import BasePortalAdapter
from .blackhatworld import BlackHatWorldAdapter
from .cracked_st import CrackedStAdapter
from .hard_tm import HardTmAdapter
from .niflheim import NiflheimAdapter
from .zxpk import ZxpkAdapter

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """
    Registro centralizado de adaptadores de portales.
    Permite a cada integrante del semillero registrar su portal desacoplado.
    """

    def __init__(self):
        self._adapters: dict[str, BasePortalAdapter] = {}

    def register(self, adapter: BasePortalAdapter) -> None:
        name = adapter.name.lower().strip()
        self._adapters[name] = adapter
        logger.info(f"Adaptador registrado para portal: '{name}'")

    def get(self, portal_name: str) -> BasePortalAdapter | None:
        return self._adapters.get(portal_name.lower().strip())

    def list_portals(self) -> list[str]:
        return list(self._adapters.keys())

    def detect_portal_by_url(self, url: str) -> str | None:
        """
        Infiere el portal en base al dominio o hostname de la URL.
        """
        try:
            domain = urlparse(url).netloc.lower()
            for name, adapter in self._adapters.items():
                adapter_domain = urlparse(adapter.base_url).netloc.lower()
                if adapter_domain and adapter_domain in domain:
                    return name
                # Casos como 'hard-tm' -> 'hard_tm', 'cracked.st' -> 'cracked_st'
                clean_hyphen = name.replace("_", "-")
                clean_dot = name.replace("_", ".")
                if clean_hyphen in domain or clean_dot in domain or name in domain:
                    return name
        except Exception:
            pass
        return None


# Instancia global y registro de adaptadores por defecto
registry = AdapterRegistry()
registry.register(NiflheimAdapter())
registry.register(BlackHatWorldAdapter())
registry.register(ZxpkAdapter())
registry.register(HardTmAdapter())
registry.register(CrackedStAdapter())

