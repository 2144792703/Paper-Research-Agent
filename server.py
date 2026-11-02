from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

import asyncio

from graph.graph_compile import graph
from logger import logger

app = FastAPI(title="论文研究报告 Agent")

class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=100)
    papers: int = Field(5, ge=1, le=20)
    max_retries: int = 2

@app.post("/research")
async def research(req: ResearchRequest):
    async def event_stream():
        yield f"event: progress\ndata: {{\"step\": \"start\", \"topic\": \"{req.topic}\"}}\n\n"

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    graph.invoke,
                    {"topic": req.topic, "critique_times": req.max_retries, "keep_papers": req.papers}
                ),
                timeout=180.0
            )
        except asyncio.TimeoutError:
            yield f"event: timeout\ndata: {{\"message\": \"研究超时(180s)，已中止\"}}\n\n"
            return
        except Exception as e:
            yield f"event: partial\ndata: {{\"error\": \"{str(e)[:200]}\"}}\n\n"
            return

        yield f"event: done\ndata: {{\"report\": \"{result.get('summary', '')[:2000]}\"}}\n\n"


    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.exception_handler(Exception)
async def global_error_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled：{exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "internal error", "error": str(exc)[:200]}
    )


