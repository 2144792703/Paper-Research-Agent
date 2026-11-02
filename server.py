from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio
from graph.graph_compile import graph

app = FastAPI(title="论文研究报告 Agent")

class ResearchRequest(BaseModel):
    topic: str
    papers: int = 5
    max_retries: int = 2

@app.post("/research")
async def research(req: ResearchRequest):
    async def event_stream():
        yield f"event: progress\ndata: {{\"step\": \"start\", \"topic\": \"{req.topic}\"}}\n\n"

        result = await asyncio.to_thread(
            graph.invoke,
            {"topic": req.topic, "critique_times": req.max_retries, "keep_papers": req.papers}
        )

        yield f"event: done\ndata: {{\"report\": \"{result.get('summary', '')[:2000]}\"}}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.get("/health")
def health():
    return {"status": "ok"}

