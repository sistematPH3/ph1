from datetime import datetime, timezone, timedelta

# Venezuela usa fijo UTC-4 (sin horario de verano desde 2007).
TZ_VENEZUELA = timezone(timedelta(hours=-4))


def current_ve_time():
    """Devuelve la hora actual de Venezuela (America/Caracas) como datetime naive."""
    return datetime.now(TZ_VENEZUELA).replace(tzinfo=None)


def utc_a_ve(dt_utc_naive):
    """Convierte un datetime naive UTC (como se guardan en BD) a hora de Venezuela naive."""
    if dt_utc_naive is None:
        return None
    return dt_utc_naive.replace(tzinfo=timezone.utc).astimezone(TZ_VENEZUELA).replace(tzinfo=None)


def ve_a_utc(dt_ve_naive):
    """Convierte un datetime naive de Venezuela a UTC naive (formato de storage)."""
    if dt_ve_naive is None:
        return None
    return dt_ve_naive.replace(tzinfo=TZ_VENEZUELA).astimezone(timezone.utc).replace(tzinfo=None)