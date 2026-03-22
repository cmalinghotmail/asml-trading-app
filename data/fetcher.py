"""Gedeelde yfinance hulpfuncties.

Alle bestanden in dit project halen koersdata op via yfinance. De gemeenschappelijke
logica (MultiIndex-afvlakking, verwijdering van de huidige onvolledige dag, lege-check)
staat hier op één plek.
"""

import datetime

import pandas as pd
import yfinance as yf


def _sanitize(df: pd.DataFrame, exclude_today: bool = True) -> pd.DataFrame | None:
    """Vereenvoudig MultiIndex-kolommen en verwijder optioneel de huidige dag."""
    if df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if exclude_today and df.index[-1].date() >= datetime.date.today():
        df = df.iloc[:-1]
    return df if not df.empty else None


def fetch_daily(ticker: str, period: str = "5d", exclude_today: bool = True) -> pd.DataFrame | None:
    """Download dagelijkse OHLCV-data. Geeft None terug bij lege of mislukte data."""
    df = yf.download(ticker, period=period, interval="1d",
                     auto_adjust=True, progress=False)
    return _sanitize(df, exclude_today=exclude_today)


def fetch_intraday(ticker: str, interval: str = "1m") -> pd.DataFrame | None:
    """Download intraday OHLCV-data voor vandaag. Huidige dag wordt NIET verwijderd."""
    df = yf.download(ticker, period="1d", interval=interval,
                     auto_adjust=True, progress=False)
    return _sanitize(df, exclude_today=False)


def extract_prev_week_hl(df: pd.DataFrame) -> dict:
    """Bereken prev-week High/Low uit een dagelijks DataFrame.

    Geeft lege dict terug als er onvoldoende historische weken zijn.
    """
    today = datetime.date.today()
    df2 = df.copy()
    df2["iso_week"] = [d.isocalendar()[1] for d in df2.index.date]
    df2["iso_year"] = [d.year             for d in df2.index.date]
    cur_week = today.isocalendar()[1]
    cur_year = today.year
    past = df2[
        (df2["iso_year"] < cur_year) |
        ((df2["iso_year"] == cur_year) & (df2["iso_week"] < cur_week))
    ]
    if past.empty:
        return {}
    lw = past["iso_week"].iloc[-1]
    ly = past["iso_year"].iloc[-1]
    wd = past[(past["iso_week"] == lw) & (past["iso_year"] == ly)]
    return {
        "prev_week_high":  round(float(wd["High"].max()), 2),
        "prev_week_low":   round(float(wd["Low"].min()),  2),
        "prev_week_label": f"Week {lw}",
    }
