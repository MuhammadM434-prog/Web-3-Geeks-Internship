"""Callable interfaces for the Week 3 Day 2 AFL prediction models.

The module wraps the trained sklearn pipelines produced by Week3Day2Tasks(1).ipynb.
It intentionally computes prediction-time features only from matches played before
(the requested) target date, matching the notebook's leakage-safe feature design.

Expected layout:
    predict.py
    models/
        match_winner_pipeline.joblib
        top_player_pipeline.joblib
    afl_datasets/
        team_matches_home_away_raw - team_matches_home_away_raw.csv.csv
        afl_players_round_by_round_stats_raw - afl_players_round_by_round_stats_raw.csv.csv

You may override paths with the constructor arguments if your project layout differs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import joblib
import numpy as np
import pandas as pd


MATCH_FEATURES = [
    "year",
    "home_recent_form_5",
    "away_recent_form_5",
    "home_days_rest",
    "away_days_rest",
    "home_team",
    "away_team",
    "venue",
    "round",
]

PLAYER_FEATURES = [
    "year",
    "prior_avg_fantasy_5",
    "prior_avg_disposals_5",
    "prior_avg_goals_5",
    "prior_games",
    "team",
    "opponent",
    "round",
]


def _canonical_name(value: str, values: list[Any], label: str) -> Any:
    """Return the training-data spelling for a team name, case-insensitively."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty name.")
    cleaned = value.strip().casefold()
    matches = [item for item in values if str(item).strip().casefold() == cleaned]
    if not matches:
        raise ValueError(f"Unknown {label} '{value}'. Check the training-data names.")
    return matches[0]


def _validated_date(value: Any, minimum: pd.Timestamp, maximum: pd.Timestamp) -> pd.Timestamp:
    """Parse a date and enforce the validated range of the training history."""
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError("date must be a valid date such as '2025-05-18'.")
    parsed = pd.Timestamp(parsed)
    if parsed < minimum or parsed > maximum:
        raise ValueError(
            f"date must be between {minimum.date()} and {maximum.date()} "
            "because the fitted model has no validated data outside that range."
        )
    return parsed


class MatchWinnerPredictor:
    """Predict the winner of a home/away match.

    Parameters
    ----------
    pipeline_path:
        Path to ``match_winner_pipeline.joblib``.
    team_csv:
        Day 1 team-match CSV used to reconstruct leakage-safe recent-form/rest features.
    """

    def __init__(self, pipeline_path: str | Path, team_csv: str | Path):
        self.pipeline = joblib.load(pipeline_path)
        history = pd.read_csv(team_csv, low_memory=False)
        history["match_date"] = pd.to_datetime(history["match_date"], errors="coerce")
        history = history[history["result"].isin(["W", "L"])].copy()
        history["team_win_flag"] = (history["result"] == "W").astype(int)
        history = history.dropna(subset=["match_date"])

        # Match exactly the notebook's one-row-per-match home perspective history.
        history["match_key"] = (
            history["match_date"].dt.strftime("%Y-%m-%d")
            + "|" + history["team_name"].astype("string")
            + "|" + history["opponent"].astype("string")
            + "|" + history["round"].astype("string")
        )
        history = history.sort_values(["team_name", "match_date", "id"])
        history["recent_form_5"] = (
            history.groupby("team_name")["team_win_flag"]
            .transform(lambda x: x.shift(1).rolling(5, min_periods=1).mean())
        )
        history["days_rest"] = history.groupby("team_name")["match_date"].diff().dt.days
        self.history = history
        self.teams = list(history["team_name"].dropna().unique())
        self.minimum_date = history["match_date"].min()
        self.maximum_date = history["match_date"].max()
        self.default_round = history["round"].mode().iloc[0]

    def _form_and_rest(self, team: Any, target_date: pd.Timestamp) -> tuple[float, float]:
        prior = self.history[
            (self.history["team_name"] == team)
            & (self.history["match_date"] < target_date)
        ].sort_values(["match_date", "id"])
        form = prior["team_win_flag"].tail(5).mean() if not prior.empty else 0.5
        rest = (target_date - prior["match_date"].iloc[-1]).days if not prior.empty else 7
        return float(form), float(rest)

    def predict_match_winner(
        self,
        team_a: str,
        team_b: str,
        date: Any,
        venue: Optional[str] = None,
        round_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return winner and home/away win probabilities.

        ``team_a`` is treated as the home team and ``team_b`` as the away team.
        """
        target_date = _validated_date(date, self.minimum_date, self.maximum_date)
        home = _canonical_name(team_a, self.teams, "team_a")
        away = _canonical_name(team_b, self.teams, "team_b")
        if home == away:
            raise ValueError("team_a and team_b must be different teams.")

        home_form, home_rest = self._form_and_rest(home, target_date)
        away_form, away_rest = self._form_and_rest(away, target_date)

        if venue is None:
            venues = self.history.loc[
                self.history["team_name"].astype("string").str.strip() == str(home).strip(),
                "venue",
            ].dropna()
            venue = venues.mode().iloc[0] if not venues.empty else self.history["venue"].mode().iloc[0]

        row = pd.DataFrame([{
            "year": target_date.year,
            "home_recent_form_5": home_form,
            "away_recent_form_5": away_form,
            "home_days_rest": home_rest,
            "away_days_rest": away_rest,
            "home_team": home,
            "away_team": away,
            "venue": venue,
            "round": self.default_round if round_name is None else round_name,
        }])[MATCH_FEATURES]

        probability = float(self.pipeline.predict_proba(row)[0, 1])
        winner = home if probability >= 0.5 else away
        return {
            "home_team": str(home).strip(),
            "away_team": str(away).strip(),
            "winner": str(winner).strip(),
            "home_win_probability": round(probability, 6),
            "away_win_probability": round(1.0 - probability, 6),
            "date": target_date.strftime("%Y-%m-%d"),
        }


class TopPlayerPredictor:
    """Predict fantasy points and rank eligible players within a match."""

    def __init__(self, pipeline_path: str | Path, player_csv: str | Path):
        self.pipeline = joblib.load(pipeline_path)
        history = pd.read_csv(player_csv, low_memory=False)
        history["match_date"] = pd.to_datetime(history["match_date"], errors="coerce")
        history["player_id"] = history["player_id"].astype("string")
        history["team"] = history["team"].astype("string")
        history["opponent"] = history["opponent"].astype("string")
        history["fantasy_points"] = pd.to_numeric(history["fantasy_points"], errors="coerce")
        history = history.dropna(subset=["match_date", "fantasy_points", "player_id"])
        history["game_key"] = (
            history["match_date"].dt.strftime("%Y-%m-%d")
            + "|" + history[["team", "opponent"]].apply(lambda r: "|".join(sorted(r)), axis=1)
            + "|" + history["round"].astype("string")
        )
        history = history.sort_values(["player_id", "match_date", "id"])

        for source_column, feature_name in [
            ("fantasy_points", "prior_avg_fantasy_5"),
            ("disposals", "prior_avg_disposals_5"),
            ("goals", "prior_avg_goals_5"),
        ]:
            prior_values = history.groupby("player_id")[source_column].shift(1)
            history[feature_name] = prior_values.groupby(history["player_id"]).transform(
                lambda x: x.rolling(5, min_periods=1).mean()
            )
        history["prior_games"] = history.groupby("player_id").cumcount()

        self.history = history
        self.teams = list(history["team"].dropna().unique())
        self.match_ids = set(history["game_key"].dropna())
        self.minimum_date = history["match_date"].min()
        self.maximum_date = history["match_date"].max()

    def _features(self, player_id: Any, team: Any, opponent: Any,
                  target_date: pd.Timestamp, round_name: Any) -> dict[str, Any]:
        prior = self.history[
            (self.history["player_id"] == player_id)
            & (self.history["match_date"] < target_date)
        ].sort_values(["match_date", "id"])
        if prior.empty:
            raise ValueError(f"No prior history for player '{player_id}'.")
        recent = prior.tail(5)
        return {
            "year": target_date.year,
            "prior_avg_fantasy_5": recent["fantasy_points"].mean(),
            "prior_avg_disposals_5": recent["disposals"].mean(),
            "prior_avg_goals_5": recent["goals"].mean(),
            "prior_games": len(prior),
            "team": team,
            "opponent": opponent,
            "round": round_name,
        }

    def predict_top_player(
        self,
        match_id: Optional[str] = None,
        team: Optional[str] = None,
        opponent: Optional[str] = None,
        date: Any = None,
        stat_type: str = "fantasy_points",
        top_k: int = 5,
        round_name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return the top-k players ranked by predicted fantasy points.

        Provide either an existing ``match_id`` or ``team``, ``opponent`` and ``date``.
        """
        if stat_type not in {"fantasy_points", "fantasy", "score"}:
            raise ValueError("Unsupported stat_type. This pipeline supports 'fantasy_points'.")
        if not isinstance(top_k, int) or top_k < 1:
            raise ValueError("top_k must be a positive integer.")

        if match_id is not None:
            if match_id not in self.match_ids:
                raise ValueError("Unknown match_id. Pass a game_key from player-match data.")
            current = self.history[self.history["game_key"] == match_id]
            target_date = pd.Timestamp(current["match_date"].iloc[0])
            round_name = current["round"].iloc[0]
            candidates = current[["player_id", "team", "opponent"]].drop_duplicates()
        else:
            if team is None or opponent is None or date is None:
                raise ValueError("Provide match_id, or provide team, opponent, and date.")
            target_date = _validated_date(date, self.minimum_date, self.maximum_date)
            team = _canonical_name(team, self.teams, "team")
            opponent = _canonical_name(opponent, self.teams, "opponent")
            if team == opponent:
                raise ValueError("team and opponent must be different teams.")
            round_name = self.history["round"].mode().iloc[0] if round_name is None else round_name
            candidates = self.history[
                (self.history["team"] == team)
                & (self.history["match_date"] < target_date)
            ][["player_id", "team"]].drop_duplicates("player_id")
            candidates["opponent"] = opponent

        if candidates.empty:
            raise ValueError("No eligible player history is available for this request.")

        rows, player_ids = [], []
        for candidate in candidates.itertuples(index=False):
            try:
                rows.append(self._features(candidate.player_id, candidate.team,
                                            candidate.opponent, target_date, round_name))
                player_ids.append(candidate.player_id)
            except ValueError:
                continue

        if not rows:
            raise ValueError("No eligible players have history before the requested date.")

        predictions = self.pipeline.predict(pd.DataFrame(rows)[PLAYER_FEATURES])
        ranked = pd.DataFrame({
            "player_id": player_ids,
            "predicted_fantasy_points": predictions,
        }).sort_values(
            ["predicted_fantasy_points", "player_id"], ascending=[False, True]
        ).head(top_k)
        ranked["rank"] = range(1, len(ranked) + 1)
        return ranked[["rank", "player_id", "predicted_fantasy_points"]].to_dict("records")


# ---------------------------------------------------------------------------
# Convenience functions: simple interfaces suitable for LangChain/LangGraph.
# ---------------------------------------------------------------------------

_DEFAULT_ROOT = Path(__file__).resolve().parent
_DEFAULT_MODELS = _DEFAULT_ROOT / "models"
_DEFAULT_DATA = _DEFAULT_ROOT / "afl_datasets"

_match_predictor: Optional[MatchWinnerPredictor] = None
_player_predictor: Optional[TopPlayerPredictor] = None


def _get_match_predictor() -> MatchWinnerPredictor:
    global _match_predictor
    if _match_predictor is None:
        _match_predictor = MatchWinnerPredictor(
            _DEFAULT_MODELS / "match_winner_pipeline.joblib",
            _DEFAULT_DATA / "team_matches_home_away_raw - team_matches_home_away_raw.csv.csv",
        )
    return _match_predictor


def _get_player_predictor() -> TopPlayerPredictor:
    global _player_predictor
    if _player_predictor is None:
        _player_predictor = TopPlayerPredictor(
            _DEFAULT_MODELS / "top_player_pipeline.joblib",
            _DEFAULT_DATA / "afl_players_round_by_round_stats_raw - afl_players_round_by_round_stats_raw.csv.csv",
        )
    return _player_predictor


def predict_match_winner(team_a: str, team_b: str, date: Any,
                         venue: Optional[str] = None,
                         round_name: Optional[str] = None) -> dict[str, Any]:
    """Agent-tool friendly match-winner function."""
    return _get_match_predictor().predict_match_winner(team_a, team_b, date, venue, round_name)


def predict_top_player(match_id: Optional[str] = None, team: Optional[str] = None,
                       opponent: Optional[str] = None, date: Any = None,
                       stat_type: str = "fantasy_points", top_k: int = 5,
                       round_name: Optional[str] = None) -> list[dict[str, Any]]:
    """Agent-tool friendly top-player ranking function."""
    return _get_player_predictor().predict_top_player(
        match_id, team, opponent, date, stat_type, top_k, round_name
    )


if __name__ == "__main__":
    print("predict.py loaded successfully. Import predict_match_winner or predict_top_player.")
