from datetime import datetime, timezone, timedelta

# Venezuela usa fijo UTC-4 (sin horario de verano desde 2007).
TZ_VENEZUELA = timezone(timedelta(hours=-4))


def current_ve_time():
    """Devuelve la hora actual de Venezuela (America/Caracas) como datetime naive."""
    return datetime.now(TZ_VENEZUELA).replace(tzinfo=None)