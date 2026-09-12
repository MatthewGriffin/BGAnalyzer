# SPDX-License-Identifier: AGPL-3.0-only
# Research translation of AndroidAPS AutotuneCore.kt basal section.
# Upstream commit and file hashes: ../aaps/manifest.json. License: ../aaps/LICENSE.txt.
# Not imported by BGAnalyzer and not approved for treatment recommendations.
from datetime import datetime
from decimal import Decimal
from math import floor, isfinite
from zoneinfo import ZoneInfo


def round_to(value, step):
    if not isfinite(value):
        raise ValueError('Nonfinite reference input/output is unsupported')
    return float(Decimal(floor(value / step + 0.5)) * Decimal(str(step))) if value else 0.0


def tune_basal(previous, pump, isf, minimum, maximum, glucose, zone):
    if len(previous)!=24 or len(pump)!=24 or isf<=0 or minimum<=0 or maximum<minimum:
        raise ValueError('Explicit hourly profiles, ISF and bounds required')
    if any(not isfinite(x) or x<0 for x in previous+pump):raise ValueError('Invalid rates')
    if any(ms==0 or not isfinite(dev) for ms,dev in glucose):raise ValueError('Missing date/deviation')
    hours=[(datetime.fromtimestamp(ms/1000,ZoneInfo(zone)).hour,dev) for ms,dev in glucose]
    result=list(previous)
    for hour in range(24):
        deviations=round_to(sum(dev for h,dev in hours if h==hour),0.001)
        needed=round_to(0.2*deviations/isf,0.01)
        prior=[(hour+offset)%24 for offset in (-3,-2,-1)]
        if needed>0:
            for h in prior:result[h]=round_to(result[h]+needed/3,0.001)
        elif needed<0:
            total=sum(result[h] for h in prior)
            if total==0:raise ValueError('Zero three-hour basal denominator is unsupported')
            ratio=1+needed/total
            for h in prior:result[h]=round_to(result[h]*ratio,0.001)
    for hour in range(24):
        if result[hour]>pump[hour]*maximum:result[hour]=pump[hour]*maximum
        elif result[hour]<pump[hour]*minimum:result[hour]=pump[hour]*minimum
        result[hour]=round_to(result[hour],0.001)
    last=0
    for hour in range(24):
        if previous[hour]==result[hour]:
            following=next((h for h in range(hour,24) if previous[h]!=result[h]),23)
            result[hour]=round_to(0.8*previous[hour]+0.1*result[last]+0.1*result[following],0.001)
        else:last=hour
    return result
