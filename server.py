from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

import asyncio
import json

from config import KEEP_MAX, KEEP_MIN, clamp_keep_papers
from graph.graph_compile import graph
from observability import trace_config, trace_id, flush
from security import sanitize_topic, flag_injection, MAX_TOPIC_LEN
from logger import logger
import cache
import usage
from report_check import check_report, build_corpus

app = FastAPI(title="论文研究报告 Agent")

# 研究 run 串行锁：同一时刻只允许一个研究执行（见 /research 事件流内的临界区）
_run_lock = asyncio.Lock()


class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=100)
    papers: int = Field(5, ge=KEEP_MIN, le=KEEP_MAX)
    max_retries: int = 2


@app.post("/research")
async def research(req: ResearchRequest):
    # 步骤3：控制字符清理 + 空值/长度校验（Pydantic 的 max_length 为第一道兜底，这里再显式校验）
    topic_sanitized = sanitize_topic(req.topic)
    if not topic_sanitized:
        raise HTTPException(status_code=400, detail="topic 清理后为空")
    if len(topic_sanitized) > MAX_TOPIC_LEN:
        raise HTTPException(status_code=400, detail=f"topic 超长，上限 {MAX_TOPIC_LEN} 字符")

    # 步骤3：危险标记（不硬拦截；命中仅打 warning 供人工复核）
    for flag in flag_injection(topic_sanitized):
        logger.warning(f"[sec] topic 含注入可疑短语 '{flag}'，正常处理但请人工核对后续报告")

    async def event_stream():
        start_payload = {"step": "start", "topic": topic_sanitized}
        yield f"event: progress\ndata: {json.dumps(start_payload, ensure_ascii=False)}\n\n"

        # 方案1：复位/执行/汇总在同一临界区内，并发请求排队执行，
        # 避免互相清零统计（usage/cache 命中数只统计当次请求），也避免重复消耗 API 配额
        async with _run_lock:
            try:
                config = trace_config(topic_sanitized)
                usage.reset()
                cache.reset_stats()
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        graph.invoke,
                        {"topic": topic_sanitized, "critique_times": req.max_retries, "keep_papers": clamp_keep_papers(req.papers)},
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
                # 异常详情只进服务端日志（类型名），不回传前端，避免内部信息泄露
                logger.error(f"研究流程异常：{type(e).__name__}")
                err_payload = {"error": "研究过程中出现内部错误，详情见服务端日志"}
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
    # 日志只记异常类型名；响应体不携带任何异常详情/内部路径
    logger.error(f"Unhandled：{type(exc).__name__}")
    return JSONResponse(
        status_code=500,
        content={"detail": "internal error"}
    )
