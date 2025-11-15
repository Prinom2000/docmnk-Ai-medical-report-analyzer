from pydantic import BaseModel, ConfigDict
from typing import Any, Dict, List, Optional

class ReportRequest(BaseModel):
    user_id: str

class FileInfo(BaseModel):
    url: str
    field: str
    type: str

class MedicalAnalysis(BaseModel):
    """Flexible schema for medical analysis - allows any structure within 8 main sections"""
    patient_info: Optional[Dict[str, Any]] = None
    examination_findings: Optional[Dict[str, Any]] = None
    risk_stratification: Optional[Dict[str, Any]] = None
    key_calculations: Optional[Dict[str, Any]] = None
    individualized_diet_plan: Optional[Dict[str, Any]] = None
    exercise_physiotherapy_plan: Optional[Dict[str, Any]] = None
    management_advice_triggers: Optional[Dict[str, Any]] = None
    red_flags_emergency_return: Optional[Dict[str, Any]] = None
    follow_up_plan: Optional[Dict[str, Any]] = None
    integrated_report_summary: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(extra="allow")

class MedicalReport(BaseModel):
    patient_id: str
    patient_data: Dict[str, Any]
    files_analyzed: List[FileInfo]
    medical_analysis: MedicalAnalysis
    generation_timestamp: str
    
    model_config = ConfigDict(extra="allow")
