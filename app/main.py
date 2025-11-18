from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.endpoints import medical_report

app = FastAPI(
    title="Medical Report Generator API",
    version="1.0.0",
    description="Generates structured medical reports using OpenAI and Cloudinary data."
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(medical_report.router, prefix="/api/v1", tags=["Medical Report"])

@app.get("/")
def read_root():
    return {"message": "Medical Report Generator API is running"}
