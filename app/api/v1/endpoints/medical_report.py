from fastapi import APIRouter, HTTPException, File, UploadFile
from app.schemas.report_schema import ReportRequest, MedicalReport
from app.services.medical_report_service import MedicalReportService
from pathlib import Path
import tempfile

router = APIRouter()

@router.post("/generate-report")
async def generate_report(request: ReportRequest):
    try:
        service = MedicalReportService()
        report = await service.generate_report(request.user_id)
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

