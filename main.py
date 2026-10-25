from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional
from agents import run_summarizer_agent, run_recommender_agent, run_gemini_interviewer

app = FastAPI(title="SquadUp Gemini Agents Service")

class SummarizeRequest(BaseModel):
    transcript: str

class RecommendPayload(BaseModel):
    viewer_profile: dict
    candidates: list[dict]
    event_context: dict

class InterviewTurnRequest(BaseModel):
    history: list[dict]

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "squadup-agents"}

@app.post("/recommend")
def get_recommendations(payload: RecommendPayload):
    """
    POST /recommend contract endpoint: reranks candidates with reasons.
    """
    reranked = run_recommender_agent(
        viewer_profile=payload.viewer_profile,
        candidates=payload.candidates,
        event_context=payload.event_context
    )
    return {"recommendations": reranked}

@app.post("/internal/interview-summary")
def summarize_interview(req: SummarizeRequest):
    """
    Turns an interview transcript into profile summary and traits.
    """
    result = run_summarizer_agent(req.transcript)
    return result

@app.post("/api/interview-turn")
def interview_turn(req: InterviewTurnRequest):
    """
    Handles turn-by-turn interview logic.
    """
    return run_gemini_interviewer(req.history)

@app.websocket("/ws/interview")
async def interview_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for Gemini Live Voice / Text interview.
    """
    await websocket.accept()
    try:
        await websocket.send_json({
            "type": "agent_utterance",
            "text": "Hi! Welcome to SquadUp. What kind of team or event are you looking to join today?"
        })
        
        while True:
            data = await websocket.receive_json()
            user_text = data.get("text", "")
            
            if user_text:
                response_text = f"Got it. Regarding '{user_text}', how many hours per week are you planning to commit?"
                await websocket.send_json({
                    "type": "agent_utterance",
                    "text": response_text
                })
    except WebSocketDisconnect:
        print("Interview WebSocket disconnected.")