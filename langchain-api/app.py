import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
from dotenv import load_dotenv

# .env ファイルから環境変数を読み込む（必要なら）
load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

app = FastAPI()

# リレーするOllama APIのエンドポイント一覧
PROXY_ENDPOINTS = [
    "/api/generate",
    "/api/tags",
    "/api/copy",
    "/api/show",
    "/api/push",
    "/api/pull",
    "/api/ps",
    "/api/create",
    "/api/delete",
    "/api/embed",
    "/api/embeddings",
    "/api/version",
]

@app.api_route("/{full_path:path}", methods=["GET", "POST"])
async def relay_request(request: Request, full_path: str):
    path = "/" + full_path
    if any(path.startswith(endpoint) for endpoint in PROXY_ENDPOINTS):
        async with httpx.AsyncClient() as client:
            url = f"{OLLAMA_BASE_URL}{path}"
            try:
                # JSONボディを取得（あれば）
                body = await request.body()
                headers = dict(request.headers)
                method = request.method.lower()

                response = await client.request(
                    method=method,
                    url=url,
                    content=body,
                    headers=headers,
                    timeout=60.0,
                )
                return JSONResponse(
                    status_code=response.status_code,
                    content=response.json()
                )
            except Exception as e:
                return JSONResponse(status_code=500, content={"error": str(e)})
    elif path.startswith("/api/chat"):
        return await proxy_chat(request)
    else:
        return JSONResponse(status_code=404, content={"error": "Not proxied"})


async def proxy_chat(request: Request):
    payload = await request.json()
    stream = payload.get("stream", False)

    if stream:
        async def event_generator():
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST", f"{OLLAMA_BASE_URL}/api/chat",
                    json=payload,
                    headers={"Content-Type": "application/json"}
                ) as upstream:
                    async for line in upstream.aiter_lines():
                        if line.strip():
                            yield f"data: {line}\n\n"
                    yield "data: [DONE]\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    else:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            return JSONResponse(status_code=response.status_code, content=response.json())


# LangChain独自のAPIエンドポイント（例）
@app.get("/api/langchain/hello")
def langchain_hello():
    return {"message": "Hello from LangChain API"}

