"""
Ley de mezcla compartida por la reproducción en vivo y la exportación.

Estas reglas vivían duplicadas en `playback_engine._audio_callback` y en
`stem_manager.export_mix`, y las dos copias ya habían divergido: la exportación
no aplicaba el volumen maestro, así que el WAV exportado salía con un nivel
distinto del que se estaba escuchando. Con una sola definición, lo que se oye y
lo que se guarda no pueden volver a separarse.
"""

import math
from typing import Dict, Tuple


def any_soloed(all_params: Dict[str, dict]) -> bool:
    """True si hay al menos un stem en solo, lo que silencia a los demás."""
    return any(p.get('soloed', False) for p in all_params.values())


def is_audible(params: dict, solo_active: bool) -> bool:
    """Decide si un stem suena, aplicando mute y solo en ese orden."""
    if params.get('muted', False):
        return False
    if solo_active and not params.get('soloed', False):
        return False
    return True


def stem_gains(params: dict) -> Tuple[float, float]:
    """
    Ganancias (izquierda, derecha) por ley de potencia constante.

    pan va de -1 (izquierda) a +1 (derecha); en el centro ambos canales reciben
    cos(pi/4) ≈ 0.707, de modo que la potencia percibida se mantiene al panear.
    """
    vol = float(params.get('volume', 1.0))
    pan = float(params.get('pan', 0.0))
    angle = (pan + 1.0) * (math.pi / 4.0)
    return vol * math.cos(angle), vol * math.sin(angle)
