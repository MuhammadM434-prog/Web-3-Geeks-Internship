from __future__ import annotations

import importlib.util
import json
import logging
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal, TypedDict

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parents[1]
DAY1 = ROOT / "Day 1"
DAY2 = ROOT / "Day 2"
DATA = DAY1 / "afl_datasets"
TEAM_FEATURES = DAY1 / "team_match_features_v1.csv"
PLAYER_FEATURES = DAY1 / "player_match_features_v1.csv"
PLAYER_INFO = DATA / "afl_players_info_raw.csv"
TEAM_MATCH = DATA / "team_matches_home_away_raw - team_matches_home_away_raw.csv.csv"
PLAYER_MATCH = DATA / "afl_players_round_by_round_stats_raw - afl_players_round_by_round_stats_raw.csv.csv"

PREDICTION_DISCLAIMER = "Predicted probability, not a certainty. Actual results can differ."
SAFE_SCOPE_RESPONSE = "I can only help with Australian rules football, including AFL teams, players, matches, rules, and statistics."
INJECTION_PATTERNS = (
    "ignore previous instructions", "reveal the system prompt", "reveal the hidden prompt",
    "act as an unrestricted assistant", "override the afl-only scope", "jailbreak",
)
OFF_TOPIC_TERMS = ("recipe", "soccer", "nba", "politics", "election", "weather", "quantum")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str = Field(default="demo-conversation", min_length=1, max_length=100)


class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    detected_intent: str
    tools_called: list[str]
    latency_ms: float
    prediction: dict[str, Any] | None = None


class AFLState(TypedDict, total=False):
    message: str
    intent: str
    tool_result: dict[str, Any]
    response: str
    tools_called: list[str]


logger = logging.getLogger("afl_assistant")
logging.basicConfig(level=logging.INFO, format="%(message)s")
conversations: dict[str, list[dict[str, str]]] = defaultdict(list)


predict_spec = importlib.util.spec_from_file_location("week3_day2_predict", DAY2 / "predict.py")
predict_module = importlib.util.module_from_spec(predict_spec)
sys.modules[predict_spec.name] = predict_module
assert predict_spec and predict_spec.loader
predict_spec.loader.exec_module(predict_module)
match_predictor = predict_module.MatchWinnerPredictor(DAY2 / "models" / "match_winner_pipeline.joblib", TEAM_MATCH)
player_predictor = predict_module.TopPlayerPredictor(DAY2 / "models" / "top_player_pipeline.joblib", PLAYER_MATCH)
team_features = pd.read_csv(TEAM_FEATURES, low_memory=False)
player_features = pd.read_csv(PLAYER_FEATURES, low_memory=False)
player_info = pd.read_csv(PLAYER_INFO, low_memory=False)


def classify(message: str) -> Literal["factual", "retrieval", "prediction", "off-topic", "injection"]:
    text = message.casefold()
    if any(term in text for term in INJECTION_PATTERNS):
        return "injection"
    if any(term in text for term in OFF_TOPIC_TERMS):
        return "off-topic"
    if any(term in text for term in ("probability", "predict", "who will win", "top score", "top-score")):
        return "prediction"
    if any(term in text for term in ("disposals", "stats", "record", "last round", "how many")):
        return "retrieval"
    return "factual" if any(term in text for term in ("afl", "team", "player", "match", "rule")) else "off-topic"


def latest_fixture() -> dict[str, Any]:
    home = match_predictor.history[match_predictor.history["home_away"].astype("string").str.upper().eq("H")]
    row = home.sort_values(["match_date", "id"]).iloc[-1]
    return {"date": row["match_date"].strftime("%Y-%m-%d"), "home_team": str(row["team_name"]), "away_team": str(row["opponent"]), "round": str(row["round"]), "venue": str(row["venue"])}


def prediction_result(message: str) -> dict[str, Any]:
    fixture = latest_fixture()
    mentioned = [team for team in match_predictor.teams if str(team).casefold() in message.casefold()]
    if len(mentioned) >= 2:
        fixture["home_team"], fixture["away_team"] = mentioned[:2]
    if any(term in message.casefold() for term in ("top score", "top-score", "top player")):
        rankings = player_predictor.predict_top_player(team=fixture["home_team"], opponent=fixture["away_team"], date=fixture["date"], stat_type="fantasy_points", top_k=3, round_name=fixture["round"])
        total = sum(float(row["predicted_fantasy_points"]) for row in rankings) or 1.0
        return {"type": "top_player_prediction", "fixture": fixture, "rankings": rankings, "player": str(rankings[0]["player_id"]), "confidence": round(float(rankings[0]["predicted_fantasy_points"]) / total, 3)}
    prediction = match_predictor.predict_match_winner(fixture["home_team"], fixture["away_team"], fixture["date"], venue=fixture["venue"], round_name=fixture["round"])
    probability = prediction["home_win_probability"] if prediction["winner"] == prediction["home_team"] else prediction["away_win_probability"]
    return {"type": "match_prediction", "fixture": fixture, "winner": prediction["winner"], "probability": probability, "prediction": prediction}


def retrieval_result(message: str) -> dict[str, Any]:
    text = message.casefold()
    names = sorted(player_info["player_name"].dropna().unique(), key=len, reverse=True)
    player = next((name for name in names if name.casefold() in text), None)
    if player and any(term in text for term in ("disposal", "last round", "most recent")):
        ids = set(player_info.loc[player_info["player_name"].eq(player), "id"].astype(int))
        rows = player_features[player_features["player_id"].isin(ids)].copy()
        rows["match_date"] = pd.to_datetime(rows["match_date"], errors="coerce")
        row = rows.sort_values(["match_date", "round"]).iloc[-1]
        disposals = int(pd.to_numeric(row["disposals"], errors="coerce") or 0)
        answer = f"{player} recorded {disposals} disposals in round {int(row['round'])} against {row['opponent']} on {row['match_date'].date().isoformat()}."
        return {"answer": answer, "source": "player_match_features_v1.csv", "tool": "player_last_match_lookup"}
    raise ValueError("Please provide a supported player name and statistic request.")


def format_prediction(result: dict[str, Any]) -> str:
    if result["type"] == "match_prediction":
        return f"{result['winner']} is the model's estimated winner with a {float(result['probability']):.0%} predicted probability. {PREDICTION_DISCLAIMER}"
    return f"{result['player']} ranks first with {float(result['confidence']):.0%} predicted ranking confidence. {PREDICTION_DISCLAIMER}"


def classify_node(state: AFLState) -> dict[str, Any]:
    return {"intent": classify(state["message"]), "tools_called": []}


def answer_node(state: AFLState) -> dict[str, Any]:
    intent = state["intent"]
    if intent == "off-topic":
        return {"response": SAFE_SCOPE_RESPONSE}
    if intent == "injection":
        return {"response": "This request attempted to override the AFL-only scope and was blocked."}
    if intent == "factual":
        return {"response": "This AFL question can be answered from grounded context."}
    return {}


def prediction_node(state: AFLState) -> dict[str, Any]:
    result = prediction_result(state["message"])
    return {"tool_result": result, "response": format_prediction(result), "tools_called": ["day2_predictor"]}


def retrieval_node(state: AFLState) -> dict[str, Any]:
    result = retrieval_result(state["message"])
    return {"tool_result": result, "response": result["answer"], "tools_called": ["day3_structured_retrieval"]}


def route(state: AFLState) -> str:
    return state["intent"] if state["intent"] in {"prediction", "retrieval"} else "answer"


graph_builder = StateGraph(AFLState)
graph_builder.add_node("classify", classify_node)
graph_builder.add_node("answer", answer_node)
graph_builder.add_node("prediction", prediction_node)
graph_builder.add_node("retrieval", retrieval_node)
graph_builder.add_edge(START, "classify")
graph_builder.add_conditional_edges("classify", route, {"answer": "answer", "prediction": "prediction", "retrieval": "retrieval"})
graph_builder.add_edge("answer", END)
graph_builder.add_edge("prediction", END)
graph_builder.add_edge("retrieval", END)
afl_graph = graph_builder.compile()


api = FastAPI(title="AFL Assistant API", version="1.0.0")


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "afl-assistant"}


@api.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    started = time.perf_counter()
    conversations[request.conversation_id].append({"role": "user", "content": request.message})
    try:
        result = afl_graph.invoke({"message": request.message})
    except Exception as error:
        logger.exception(json.dumps({"event": "chat_request_failed", "conversation_id": request.conversation_id}))
        raise HTTPException(status_code=400, detail=str(error)) from error
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    response = result.get("response", "No response was generated.")
    conversations[request.conversation_id].append({"role": "assistant", "content": response})
    fields = {"event": "chat_request_completed", "query": request.message, "detected_intent": result["intent"], "tools_called": result.get("tools_called", []), "latency_ms": latency_ms, "conversation_id": request.conversation_id}
    logger.info(json.dumps(fields))
    return ChatResponse(response=response, conversation_id=request.conversation_id, detected_intent=result["intent"], tools_called=result.get("tools_called", []), latency_ms=latency_ms, prediction=result.get("tool_result") if result["intent"] == "prediction" else None)


@api.get("/", response_class=HTMLResponse)
def ui() -> str:
    return """<!doctype html><html><body><h1>AFL Assistant</h1><div id='chat'></div><input id='q' placeholder='Ask about AFL'><button onclick='send()'>Send</button><script>const id=crypto.randomUUID();async function send(){const q=document.querySelector('#q');const message=q.value;q.value='';const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,conversation_id:id})});const d=await r.json();document.querySelector('#chat').innerHTML+=`<p><b>You:</b> ${message}</p><p><b>AFL Assistant:</b> ${d.response}</p>`}</script></body></html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(api, host="127.0.0.1", port=8000)
