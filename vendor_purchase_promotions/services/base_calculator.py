from abc import ABC, abstractmethod


class VendorCalculator(ABC):
    """Small calculation contract used by vendor-specific strategies."""

    profile = 'generic'

    @abstractmethod
    def calculate_unit(self, **values):
        raise NotImplementedError

