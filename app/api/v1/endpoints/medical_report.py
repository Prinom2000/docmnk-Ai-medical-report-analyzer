from fastapi import APIRouter, HTTPException, File, UploadFile
from app.schemas.report_schema import ReportRequest, MedicalReport
from app.services.medical_report_service import MedicalReportService
from pathlib import Path
import tempfile

router = APIRouter()

@router.post("/generate-report")
def generate_report(request: ReportRequest):
    try:
        service = MedicalReportService()
        report = service.generate_report(request.user_id)
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/analyze-file-for-test")
def analyze_file(file: UploadFile = File(...)):
    """
    Upload a PDF or image file and get a medical report analysis.
    
    Supported formats:
    - PDF (.pdf)
    - Images (.jpg, .jpeg, .png, .gif, .webp)
    """
    try:
        # Validate file type
        file_extension = Path(file.filename).suffix.lower()
        valid_extensions = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.webp'}
        
        if file_extension not in valid_extensions:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid file type. Supported: {', '.join(valid_extensions)}"
            )
        
        # Determine file type
        if file_extension == '.pdf':
            file_type = 'pdf'
        else:
            file_type = 'image'
        
        # Save uploaded file to temp directory
        service = MedicalReportService()
        temp_file_path = service.temp_dir / file.filename
        
        with open(temp_file_path, "wb") as f:
            f.write(file.file.read())
        
        # Analyze the file
        analysis = service.analyze_file_only(temp_file_path, file_type)
        
        response = {
            "filename": file.filename,
            "file_type": file_type,
            "medical_analysis": analysis,
            "generation_timestamp": __import__('datetime').datetime.now().isoformat()
        }
        
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
