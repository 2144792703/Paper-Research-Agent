from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

from config import (
    KEEP_MAX, KEEP_MIN, SEARCH_MIN, SEARCH_MAX, SERVER_TIMEOUT, RECURSION_LIMIT,
    clamp_keep_papers, clamp_search_count, validate_config,
)
from graph.graph_compile import graph
from observability import trace_config, trace_id, flush
from security import sanitize_topic, flag_injection, MAX_TOPIC_LEN
from logger import logger
import cache
import usage
from report_check import check_report, build_corpus

validate_config()

app = FastAPI(title="论文研究报告 Agent")

# 研究 run 串行锁：同一时刻只允许一个研究执行（见 /research 事件流内的临界区）
# 注意：asyncio.Lock 只在单进程内有效，部署时必须保持单 worker。
_run_lock = asyncio.Lock()
# 独立单线程执行器：超时后任务不会被取消，但锁要等它真正结束才释放，避免并发跑第二个 run
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="research")


class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=100)
    papers: int = Field(5, ge=KEEP_MIN, le=KEEP_MAX)
    max_retries: int = Field(2, ge=1, le=5)
    search_count: int | None = Field(None, ge=SEARCH_MIN, le=SEARCH_MAX)


@app.post("/research")
async def research(req: ResearchRequest):
    # 控制字符清理 + 空值/长度校验（Pydantic 的 max_length 为第一道兜底，这里再显式校验）
    topic_sanitized = sanitize_topic(req.topic)
    if not topic_sanitized:
        raise HTTPException(status_code=400, detail="topic 清理后为空")
    if len(topic_sanitized) > MAX_TOPIC_LEN:
        raise HTTPException(status_code=400, detail=f"topic 超长，上限 {MAX_TOPIC_LEN} 字符")

    # 危险标记（不硬拦截；命中仅打 warning 供人工复核）
    for flag in flag_injection(topic_sanitized):
        logger.warning(f"[sec] topic 含注入可疑短语 '{flag}'，正常处理但请人工核对后续报告")

    async def event_stream():
        start_payload = {"step": "start", "topic": topic_sanitized}
        yield f"event: progress\ndata: {json.dumps(start_payload, ensure_ascii=False)}\n\n"

        # 复位/执行/汇总在同一临界区内，并发请求排队执行，
        # 避免互相清零统计（usage/cache 命中数只统计当次请求），也避免重复消耗 API 配额
        loop = asyncio.get_running_loop()
        await _run_lock.acquire()
        release_in_finally = True
        try:
            try:
                langfuse_config = trace_config(topic_sanitized)
                langfuse_config["recursion_limit"] = RECURSION_LIMIT
                usage.reset()
                cache.reset_stats()
                run_input = {
                    "topic": topic_sanitized,
                    "critique_times": req.max_retries,
                    "keep_papers": clamp_keep_papers(req.papers),
                }
                if req.search_count is not None:
                    run_input["search_max_results"] = clamp_search_count(req.search_count)
                future = _executor.submit(graph.invoke, run_input, langfuse_config)
                result = await asyncio.wait_for(
                    asyncio.wrap_future(future), timeout=SERVER_TIMEOUT
                )
            except asyncio.TimeoutError:
                # 线程池任务无法强制取消：锁保持到任务真正结束再释放，避免第二个 run 并发启动
                release_in_finally = False

                def _release_later(_future):
                    try:
                        loop.call_soon_threadsafe(_run_lock.release)
                    except RuntimeError:
                        pass

                future.add_done_callback(_release_later)
                flush()
                msg = f"研究超时({SERVER_TIMEOUT:.0f}s)，已中止"
                yield f"event: timeout\ndata: {json.dumps({'message': msg}, ensure_ascii=False)}\n\n"
                return
            except Exception as e:
                flush()
                # 异常详情只进服务端日志（类型名），不回传前端，避免内部信息泄露
                logger.error(f"研究流程异常：{type(e).__name__}")
                err_payload = {"error": "研究过程中出现内部错误，详情见服务端日志"}
                yield f"event: partial\ndata: {json.dumps(err_payload, ensure_ascii=False)}\n\n"
                return

            flush()
            result = result or {}
            report = result.get("summary", "") or ""
            # 报告数字事后校验（缓存回放的报告同样被检）
            report_warnings = check_report(report, build_corpus(result))
            if report_warnings:
                logger.warning(f"报告疑似编造数字（摘要语料中不存在）：{report_warnings}")

            payload = {
                "report": report[:2000],
                "truncated": len(report) > 2000,
                "status": "aborted" if (result.get("next") == "end" and not report.strip()) else "ok",
                "trace_id": trace_id(langfuse_config) or "",
                "usage": usage.summary(),
                "report_warnings": report_warnings,
            }
        finally:
            if release_in_finally:
                _run_lock.release()

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
