# Medical Report Service
## LIVE👉 https://ai.medixcamp.com/docs

An AI-powered medical report generation system that analyzes patient data and medical documents (PDFs, images) to create comprehensive, structured clinical reports using OpenAI's GPT-4o model.

## Features

- **Patient Data Integration**: Fetches patient registration data from REST API endpoints
- **Multi-format Document Analysis**: Supports PDF and image files (JPEG, PNG, etc.)
- **OCR Capabilities**: Extracts text from scanned documents and images using Tesseract
- **AI-Powered Analysis**: Two-stage LLM processing for accurate data extraction and report generation
- **Structured Medical Reports**: Generates standardized reports with 8 comprehensive sections
- **Cloudinary Integration**: Automatically discovers and processes medical files from Cloudinary URLs

## Report Sections

Generated reports include:

1. **Patient Information** - Demographics and basic info
2. **Examination Findings** - Vital signs, pulses, physical examination
3. **Risk Stratification** - Clinical risk assessment components
4. **Key Calculations** - BMI, BMR, TDEE, calorie goals, tobacco risk
5. **Individualized Diet Plan** - Meal plans with macronutrient breakdown
6. **Exercise/Physiotherapy Plan** - Recommended activities and programs
7. **Management Advice & Triggers** - Condition-specific guidance
8. **Red Flags & Emergency Returns** - Critical warning signs
9. **Follow-up Plan** - Clinic visits, investigations, medication reviews
10. **Integrated Report Summary** - Overview with key findings and care plan

## Prerequisites

### Required Dependencies

```bash
pip install openai requests PyPDF2 Pillow pytesseract
```

### System Requirements

- Python 3.8+
- OpenAI API key with GPT-4o access
- Tesseract OCR (for image text extraction)

#### Installing Tesseract

**Ubuntu/Debian:**
```bash
sudo apt-get install tesseract-ocr
```

**macOS:**
```bash
brew install tesseract
```

**Windows:**
Download installer from [GitHub Tesseract Releases](https://github.com/UB-Mannheim/tesseract/wiki)

## Configuration

Create a configuration file with the following settings:

```python
# app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    OPENAI_API_KEY: str
    BASE_URL: str  # Base URL for patient data API
    
    class Config:
        env_file = ".env"

settings = Settings()
```

Create a `.env` file:

```env
OPENAI_API_KEY=your_openai_api_key_here
BASE_URL=https://api.yourdomain.com
```

## Usage

### Basic Usage - Generate Report from Patient ID

```python
from app.medical_report_service import MedicalReportService

# Initialize service
service = MedicalReportService()

# Generate comprehensive medical report
report = service.generate_report(user_id="patient_123")

# Access report sections
print(report['medical_analysis']['patient_info'])
print(report['medical_analysis']['examination_findings'])
```

### Analyze Single File

```python
from pathlib import Path

# Analyze a standalone medical document
file_path = Path("path/to/medical_report.pdf")
analysis = service.analyze_file_only(file_path, file_type="pdf")

# Or analyze an image
image_path = Path("path/to/xray.jpg")
analysis = service.analyze_file_only(image_path, file_type="image")
```

## API Integration

The service expects a REST API endpoint that returns patient data:

**Endpoint:** `GET /patient-registration/{user_id}`

**Expected Response Structure:**
```json
{
  "patient_id": "123",
  "name": "John Doe",
  "age": 45,
  "gender": "Male",
  "medical_history": {...},
  "documents": {
    "lab_reports": "https://res.cloudinary.com/.../report.pdf",
    "xray_images": ["https://res.cloudinary.com/.../xray1.jpg"]
  }
}
```

The service automatically:
1. Fetches patient data from the API
2. Discovers all Cloudinary URLs recursively in the JSON structure
3. Downloads and processes all medical files
4. Generates comprehensive report

## File Processing

### Supported File Types

- **PDFs**: Text extraction using PyPDF2
- **Images**: JPG, PNG, GIF, WebP with OCR support
- **Automatic Detection**: File types inferred from URLs

### Processing Pipeline

1. **URL Discovery**: Recursively searches patient data for Cloudinary URLs
2. **File Download**: Downloads files to temporary directory
3. **Text Extraction**: 
   - PDFs: Direct text extraction
   - Images: OCR via Tesseract
4. **AI Analysis**: Two-stage LLM processing
   - Stage 1: Extract raw medical data
   - Stage 2: Generate structured report

## Output Format

### Complete Report Structure

```json
{
  "patient_id": "123",
  "medical_analysis": {
    "patient_info": {...},
    "examination_findings": {...},
    "risk_stratification": {...},
    "key_calculations": {...},
    "individualized_diet_plan": {...},
    "exercise_physiotherapy_plan": {...},
    "management_advice_triggers": {...},
    "red_flags_emergency_return": {...},
    "follow_up_plan": {...},
    "integrated_report_summary": {...}
  },
  "generation_timestamp": "2025-11-15T10:30:00"
}
```

## Error Handling

The service includes robust error handling:

- API request failures with timeout (30s for data, 60s for files)
- PDF extraction errors (graceful fallback)
- OCR failures (continues with placeholder text)
- Missing dependencies (optional features disabled)

## Deployment
- **AWS(EC2)**

## Performance Considerations

- **Token Usage**: ~6000-8000 tokens per complete report generation
- **Processing Time**: 10-30 seconds depending on file count and size
- **Temporary Files**: Stored in `temp_medical_files/` directory
- **Rate Limits**: Subject to OpenAI API rate limits


## Disclaimer

⚠️ **Medical Disclaimer**: This tool is for assisting healthcare professionals. All generated reports should be reviewed and validated by qualified medical personnel before clinical use. Not intended for direct patient diagnosis or treatment decisions.

## Support

For issues and questions:
- Create an issue in the repository
- Contact: prinommojumder@gmail.com

---

**Version:** 1.0.0  
**Last Updated:** November 2025