import os

import uvicorn
from fastapi import FastAPI, Request

app = FastAPI()
port = int(os.getenv("PORT", 8000))
server_config = uvicorn.Config(app, host="0.0.0.0", port=port)
server = uvicorn.Server(server_config) 