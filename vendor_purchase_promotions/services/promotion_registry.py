import logging


_logger = logging.getLogger(__name__)
_CALCULATORS = {}


def register_calculator(calculator):
    profile = calculator.profile
    if not profile:
        raise ValueError('A vendor calculator must define a profile.')
    _CALCULATORS[profile] = calculator
    _logger.info(
        '[VPP_REGISTRY] calculator_registered profile=%s calculator=%s',
        profile,
        calculator.__class__.__name__,
    )
    return calculator


def get_calculator(profile):
    calculator = _CALCULATORS.get(profile)
    if not calculator:
        raise ValueError(f"No vendor calculator is registered for profile '{profile}'.")
    return calculator

