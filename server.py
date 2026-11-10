from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

import asyncio
import json

from graph.graph_compile import graph
from observability import trace_config, trace_id, flush
from logger import logger
import usage
import cache
from report_check import check_report, build_corpus

app = FastAPI(title="论文研究报告 Agent")

# 研究 run 串行锁：同一时刻只允许一个研究执行（见 /research 事件流内的临界区）
_run_lock = asyncio.Lock()

class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=100)
    papers: int = Field(5, ge=1, le=20)
    max_retries: int = 2

@app.post("/research")
async def research(req: ResearchRequest):
    async def event_stream():
        start_payload = {"step": "start", "topic": req.topic}
        yield f"event: progress\ndata: {json.dumps(start_payload, ensure_ascii=False)}\n\n"

        # 方案1：复位/执行/汇总在同一临界区内，并发请求排队执行，
        # 避免互相清零统计（usage/cache 命中数只统计当次请求），也避免重复消耗 API 配额
        async with _run_lock:
            try:
                config = trace_config(req.topic)
                usage.reset()
                cache.reset_stats()
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        graph.invoke,
                        {"topic": req.topic, "critique_times": req.max_retries, "keep_papers": req.papers},
                        config,
                    ),
                    timeout=360.0
                )
            except asyncio.TimeoutError:
                flush()
                yield f"event: timeout\ndata: {json.dumps({'message': '研究超时(360s)，已中止'}, ensure_ascii=False)}\n\n"
                return
            except Exception as e:
                flush()
                err_payload = {"error": str(e)[:200]}
                yield f"event: partial\ndata: {json.dumps(err_payload, ensure_ascii=False)}\n\n"
                return

            flush()
            # 方案7：报告数字事后校验（缓存回放的报告同样被检）
            report_warnings = check_report(result.get("summary", ""), build_corpus(result))
            if report_warnings:
                logger.warning(f"报告疑似编造数字（摘要语料中不存在）：{report_warnings}")

            payload = {
                "report": result.get("summary", "")[:2000],
                "trace_id": trace_id(config) or "",
                "usage": usage.summary(),
                "report_warnings": report_warnings,
            }
            yield f"event: done\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


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
