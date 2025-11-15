from fastapi import FastAPI
from app.api.v1.endpoints import medical_report

app = FastAPI(
    title="Medical Report Generator API",
    version="1.0.0",
    description="Generates structured medical reports using OpenAI and Cloudinary data."
)

app.include_router(medical_report.router, prefix="/api/v1", tags=["Medical Report"])

@app.get("/")
def read_root():
    return {"message": "Medical Report Generator API is running"}
