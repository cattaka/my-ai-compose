from __future__ import annotations
import httpx, asyncio, json, time, datetime
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse, JSONResponse
from app.core.config import settings
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.runnables.config import RunnableConfig

# LangGraph (プロバイダ分岐付き) を利用
from app.db.session import get_async_session
from app.graph.chat_graph import get_chat_graph

router = APIRouter(prefix="/api", tags=["relay"])

@router.get("/tags")
async def relay_tags():
    async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL) as client:
        r = await client.get("/api/tags")
        data = r.json()
        models = data.get("models", [])
        if isinstance(data["models"], list) and settings.OPENAI_API_KEY:
            models.append({"name": "openai:gpt-5-nano", "model": "openai:gpt-5-nano", "modified_at": "2025-08-30T09:30:39.274104826Z", "size": 0, "digest": ""})
            models.append({"name": "openai:gpt-5-mini", "model": "openai:gpt-5-mini", "modified_at": "2025-08-30T09:30:39.274104826Z", "size": 0, "digest": ""})
        content = json.dumps({"models": models}, ensure_ascii=False)
        return Response(content=content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/json"))

@router.get("/version")
async def relay_version():
    async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL) as client:
        r = await client.get("/api/version")
        return Response(content=r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/json"))

@router.get("/ps")
async def relay_ps():
    async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL) as client:
        r = await client.get("/api/ps")
        return Response(content=r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/json"))

def _iso_now() -> str:
    return datetime.datetime.utcnow().isoformat(timespec="milliseconds") + "Z"

@router.post("/chat")
async def relay_chat(request: Request, session: AsyncSession = Depends(get_async_session)):
    payload = await request.json()
    model = payload.get("model")
    messages = payload.get("messages")
    prompt = payload.get("prompt")

    if not messages and prompt:
        messages = [{"role": "user", "content": prompt}]
    if not messages:
        return JSONResponse({"error": "messages or prompt required"}, status_code=400)

    stream = payload.get("stream", True)
    temperature = (payload.get("options") or {}).get("temperature") or payload.get("temperature") or 0.7

    graph = get_chat_graph()

    config = RunnableConfig(session=session)

    if not stream:
        init_state = {
            "model": model,
            "raw_messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        out = await graph.ainvoke(init_state, config=config)
        answer = out.get("answer", "")
        resp = {
            "model": f"{out['provider']}:{out['model']}",
            "created_at": _iso_now(),
            "message": {"role": "assistant", "content": answer},
            "done": True,
            "total_duration": 0,
        }
        return JSONResponse(resp)

    async def gen():
        start = time.perf_counter()
        init_state = {
            "model": model,
            "raw_messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        full = ""
        async for namespace, mode, data in graph.astream(init_state, stream_mode=["custom", "values"], subgraphs=True, config=config):
            if mode == "custom":
                if data.get("event_name") != "token":
                    continue
                delta = data.get("delta")
                if not delta:
                    continue
                full += delta
                # Ollama /api/chat 互換: chunk は message + done:false
                chunk = {
                    "model": f"{data.get('provider')}:{data.get('model')}",
                    "created_at": _iso_now(),
                    "message": {"role": "assistant", "content": delta},
                    "done": False,
                }
                yield (json.dumps(chunk, ensure_ascii=False) + "\n").encode()
            elif mode == "values":
                # 最終スナップショット (answer が state に格納)
                # if "answer" not in data:
                #     continue
                # final_answer = data["answer"]
                # full = final_answer  # 念のため同期
                # final_line = {
                #     "model": f"{data.get('provider')}:{data.get('model')}",
                #     "created_at": _iso_now(),
                #     # 最終行で全文をもう一度 message で流したい場合は以下を有効に:
                #     "message": {"role": "assistant", "content": final_answer},
                #     "done": False,
                #     "total_duration": int((time.perf_counter() - start) * 1e9),
                # }
                # yield (json.dumps(final_line, ensure_ascii=False) + "\n").encode()
                pass

        # 念のため done:true が未送出なら送る (冪等)
        # （上の values ブロックで送れていればこの分はクライアント側で無視される）
        tail = {
            "model": f"{data.get('provider')}:{data.get('model')}",
            "created_at": _iso_now(),
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "total_duration": int((time.perf_counter() - start) * 1e9),
        }
        yield (json.dumps(tail, ensure_ascii=False) + "\n").encode()

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
