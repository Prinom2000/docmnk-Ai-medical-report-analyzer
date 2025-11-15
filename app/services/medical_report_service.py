import os
import json
import requests
import base64
import mimetypes
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from openai import OpenAI
from app.config import settings

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
  from PIL import Image
except Exception:
  Image = None

try:
  import pytesseract
except Exception:
  pytesseract = None

class MedicalReportService:
    def __init__(self):
        self.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.base_url = settings.BASE_URL
        self.temp_dir = Path("temp_medical_files")
        self.temp_dir.mkdir(exist_ok=True)

    def fetch_patient_data(self, user_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/patient-registration/{user_id}"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()

    def extract_cloudinary_urls(self, data: Dict[str, Any]) -> List[Dict[str, str]]:
        """Recursively extract all cloudinary URLs from the patient data structure."""
        urls = []
        def search(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    new_path = f"{path}.{k}" if path else k
                    search(v, new_path)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    search(item, f"{path}[{i}]")
            elif isinstance(obj, str) and "cloudinary.com" in obj:
                # Found a cloudinary URL
                urls.append({
                    "url": obj,
                    "field": path,
                    "type": self._guess_type(obj)
                })
        search(data)
        return urls

    def _guess_type(self, url: str) -> str:
        url = url.lower()
        if any(x in url for x in [".pdf", "/pdf/"]):
            return "pdf"
        elif any(x in url for x in [".jpg", ".jpeg", ".png", ".gif", ".webp", "/image/"]):
            return "image"
        return "unknown"

    def download_file(self, url: str, filename: str) -> Optional[Path]:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        file_path = self.temp_dir / filename
        file_path.write_bytes(response.content)
        return file_path

    def encode_image_to_base64(self, image_path: Path) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract text from PDF using PyPDF2."""
        if PyPDF2 is None:
            return ""
        try:
            text = ""
            with open(pdf_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            return text
        except Exception as e:
            print(f"Error extracting PDF text: {e}")
            return ""

    def extract_text_from_files(self, files: List[Dict[str, Any]]) -> str:
        """Extract text from all downloaded files (images + PDFs)."""
        extracted_texts: List[str] = []
        for f in files:
            try:
                if f.get('type') == 'pdf' and f.get('path'):
                    text = self.extract_text_from_pdf(f['path'])
                    if text and text.strip():
                        extracted_texts.append(f"--- Text from {f['field']} ---\n{text}")
                elif f.get('type') == 'image' and f.get('path'):
                    # Try OCR on images if pytesseract + Pillow are available
                    ocr_text = ""
                    if Image is not None and pytesseract is not None:
                        try:
                            img = Image.open(f['path'])
                            ocr_text = pytesseract.image_to_string(img)
                        except Exception as e:
                            print(f"Image OCR failed for {f['path']}: {e}")

                    if ocr_text and ocr_text.strip():
                        extracted_texts.append(f"--- OCR text from {f['field']} ---\n{ocr_text}")
                    else:
                        # If no OCR available or OCR failed, include placeholder indicating image included
                        extracted_texts.append(f"--- Image file included: {f['field']} (no OCR text) ---")
                else:
                    # Unknown type: skip or include a note
                    if f.get('path'):
                        extracted_texts.append(f"--- File included: {f['field']} (type: {f.get('type')}) ---")
            except Exception as e:
                print(f"Error extracting text from {f.get('field')}: {e}")

        return "\n".join(extracted_texts)

    def analyze_with_openai(self, patient_data: Dict[str, Any], files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Two-stage analysis: extract raw text, then generate structured report."""
        
        # Stage 1: Extract text from files
        extracted_text = self.extract_text_from_files(files)
        
        # Stage 2: First LLM call - extract all relevant data
        extraction_messages = [
            {"role": "system", "content": "You are an expert medical data extraction assistant. Extract all relevant medical information from the provided patient data and documents. Respond with comprehensive JSON containing all extracted medical information."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Extract all medical information from the following:\n\nPatient Registration Data:\n{json.dumps(patient_data, indent=2)}\n\nExtracted Document Text:\n{extracted_text}\n\nRespond with JSON format containing all extracted medical data, vital signs, examination findings, and any measurements."}
                ]
            }
        ]
        
        # Add images to extraction message
        for f in files:
            if f['type'] == 'image' and f['path']:
                base64_img = self.encode_image_to_base64(f['path'])
                mime = mimetypes.guess_type(f['path'])[0] or 'image/jpeg'
                extraction_messages[-1]["content"].append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{base64_img}"}
                })

        resp1 = self.openai_client.chat.completions.create(
            model="gpt-4o",
            messages=extraction_messages,
            temperature=0.3,
            max_tokens=2000
        )
        extracted_data = resp1.choices[0].message.content
        
        # Stage 3: Second LLM call - generate structured report
        report_prompt = f"""Based on the extracted medical data below, generate a comprehensive, clinically detailed medical report in JSON format.
        
Extracted Medical Data:
{extracted_data}

Patient Registration Data:
{json.dumps(patient_data, indent=2)}

Generate a JSON response with EXACTLY these 8 sections (all sections must be present). The structure is fixed, but populate each section with comprehensive, realistic data based on the medical information:

{{
  "patient_info": {{
    "gender": "(extracted from data)",
    "age": (extracted from data),
    "occupation": "(extracted from data)"
  }},
  "examination_findings": {{
    "pulses": {{
      "femoral_pulse": {{"left_limb": "(finding)", "right_limb": "(finding)"}},
      "popliteal_pulse": {{"left_limb": "(finding)", "right_limb": "(finding)"}},
      "dorsalis_pedis_pulse": {{"left_limb": "(finding)", "right_limb": "(finding)"}},
      "posterior_tibial_pulse": {{"left_limb": "(finding)", "right_limb": "(finding)"}},
      "abi": {{"left_limb": (value), "right_limb": (value)}}
    }},
    "vital_signs": {{
      "blood_pressure": "(reading)",
      "heart_rate": (value),
      "heart_rate_unit": "bpm",
      "spo2": (value),
      "spo2_unit": "%",
      "temperature": (value),
      "temperature_unit": "°C"
    }},
    "other_findings": "(any additional physical examination findings)"
  }},
  "risk_stratification": {{
    "components": [
      {{
        "component": "(type of risk: ARTERIAL, VENOUS, DFU, etc.)",
        "risk_group": "(MILD/MODERATE/SEVERE)",
        "rationale": "(clinical reason)"
      }}
    ]
  }},
  "key_calculations": {{
    "bmi": (calculated value),
    "total_tobacco_risk": "(Low/Moderate/High)",
    "bmr_mifflin_st_jeor": {{"value": (calculated), "unit": "kcal/day"}},
    "tdee_sedentary": {{"value": (calculated), "unit": "kcal/day"}},
    "calorie_goal": {{"value": (calculated), "unit": "kcal/day", "purpose": "(for weight management/muscle gain/etc)"}}
  }},
  "individualized_diet_plan": {{
    "target_calories": (value),
    "unit": "kcal/day",
    "type": "(Vegetarian/Non-vegetarian/Vegan/etc)",
    "meals": [
      {{
        "time": "(time)",
        "foods": "(detailed food list)",
        "calories": (value),
        "protein": "(amount)g",
        "carbs": "(amount)g",
        "fat": "(amount)g"
      }}
    ],
    "totals": {{
      "calories": (total),
      "protein": "(total)g",
      "carbs": "(total)g",
      "fat": "(total)g"
    }},
    "notes": ["(dietary recommendations)", "(restrictions if any)", "(special considerations)"]
  }},
  "exercise_physiotherapy_plan": {{
    "recommended_program": [
      {{
        "activity": "(type of exercise)",
        "description": "(detailed description with intensity/duration)"
      }}
    ]
  }},
  "management_advice_triggers": {{
    "condition_name": {{
      "status": "(current status)",
      "action": "(recommended action)"
    }},
    "additional_advice": "(other management recommendations)"
  }},
  "red_flags_emergency_return": {{
    "seek_immediate_medical_attention_if": [
      "(symptom/sign 1)",
      "(symptom/sign 2)",
      "(symptom/sign 3)"
    ]
  }},
  "follow_up_plan": {{
    "specialty_clinic": "(clinic name and frequency)",
    "investigations": "(recommended tests/scans)",
    "medication_review": "(timing and details)",
    "lifestyle_modifications": "(key changes needed)"
  }},
  "integrated_report_summary": {{
    "main_problems": "(primary diagnoses/concerns)",
    "critical_findings": (null if none, or describe critical findings),
    "care_plan_summary": ["(key point 1)", "(key point 2)", "(key point 3)"],
    "advisor": "(clinician name or 'AI Medical Assistant')"
  }}
}}

IMPORTANT INSTRUCTIONS:
1. Keep the 8 section names EXACTLY as specified
2. Populate EVERY section with relevant, realistic data extracted from the medical information
3. Do NOT use placeholder text - use actual extracted data
4. Add additional fields within sections if clinically relevant (e.g., lab values, additional findings)
5. For any section with no available data, use empty arrays/objects, null for numbers, empty strings for text
6. Return ONLY valid JSON, no markdown or extra text"""

        report_messages = [
            {"role": "system", "content": "You are an expert medical report generator. Create comprehensive, structured medical reports based on patient data and clinical findings."},
            {"role": "user", "content": report_prompt}
        ]

        resp2 = self.openai_client.chat.completions.create(
            model="gpt-4o",
            messages=report_messages,
            temperature=0.3,
            max_tokens=4096,
            response_format={"type": "json_object"}
        )
        
        return json.loads(resp2.choices[0].message.content)

    def analyze_file_only(self, file_path: Path, file_type: str) -> Dict[str, Any]:
        """Analyze a single file (PDF or image) without patient registration data."""
        files = [{
            "url": str(file_path),
            "field": file_path.name,
            "type": file_type,
            "path": file_path
        }]
        
        # Extract text from file
        extracted_text = self.extract_text_from_files(files)
        
        # First LLM call - extract medical data from file
        extraction_messages = [
            {"role": "system", "content": "You are an expert medical data extraction assistant. Extract all relevant medical information from the provided document. Respond with comprehensive JSON containing all extracted medical information, measurements, findings, and observations."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Extract all medical information from this document:\n\n{extracted_text}\n\nRespond with JSON format containing all extracted medical data, vital signs, examination findings, measurements, and any clinical observations."}
                ]
            }
        ]
        
        # Add image to extraction message if it's an image file
        if file_type == 'image':
            base64_img = self.encode_image_to_base64(file_path)
            mime = mimetypes.guess_type(str(file_path))[0] or 'image/jpeg'
            extraction_messages[-1]["content"].append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{base64_img}"}
            })

        resp1 = self.openai_client.chat.completions.create(
            model="gpt-4o",
            messages=extraction_messages,
            temperature=0.3,
            max_tokens=2000
        )
        extracted_data = resp1.choices[0].message.content
        
        # Second LLM call - generate structured report
        report_prompt = f"""Based on the extracted medical data below, generate a comprehensive, clinically detailed medical report in JSON format.
        
Extracted Medical Data:
{extracted_data}

Generate a JSON response with EXACTLY these 8 sections (all sections must be present). The structure is fixed, but populate each section with comprehensive, realistic data based on the medical information:

{{
  "patient_info": {{
    "gender": "(extracted from data)",
    "age": (extracted from data),
    "occupation": "(extracted from data)"
  }},
  "examination_findings": {{
    "pulses": {{
      "femoral_pulse": {{"left_limb": "(finding)", "right_limb": "(finding)"}},
      "popliteal_pulse": {{"left_limb": "(finding)", "right_limb": "(finding)"}},
      "dorsalis_pedis_pulse": {{"left_limb": "(finding)", "right_limb": "(finding)"}},
      "posterior_tibial_pulse": {{"left_limb": "(finding)", "right_limb": "(finding)"}},
      "abi": {{"left_limb": (value), "right_limb": (value)}}
    }},
    "vital_signs": {{
      "blood_pressure": "(reading)",
      "heart_rate": (value),
      "heart_rate_unit": "bpm",
      "spo2": (value),
      "spo2_unit": "%",
      "temperature": (value),
      "temperature_unit": "°C"
    }},
    "other_findings": "(any additional physical examination findings)"
  }},
  "risk_stratification": {{
    "components": [
      {{
        "component": "(type of risk: ARTERIAL, VENOUS, DFU, etc.)",
        "risk_group": "(MILD/MODERATE/SEVERE)",
        "rationale": "(clinical reason)"
      }}
    ]
  }},
  "key_calculations": {{
    "bmi": (calculated value),
    "total_tobacco_risk": "(Low/Moderate/High)",
    "bmr_mifflin_st_jeor": {{"value": (calculated), "unit": "kcal/day"}},
    "tdee_sedentary": {{"value": (calculated), "unit": "kcal/day"}},
    "calorie_goal": {{"value": (calculated), "unit": "kcal/day", "purpose": "(for weight management/muscle gain/etc)"}}
  }},
  "individualized_diet_plan": {{
    "target_calories": (value),
    "unit": "kcal/day",
    "type": "(Vegetarian/Non-vegetarian/Vegan/etc)",
    "meals": [
      {{
        "time": "(time)",
        "foods": "(detailed food list)",
        "calories": (value),
        "protein": "(amount)g",
        "carbs": "(amount)g",
        "fat": "(amount)g"
      }}
    ],
    "totals": {{
      "calories": (total),
      "protein": "(total)g",
      "carbs": "(total)g",
      "fat": "(total)g"
    }},
    "notes": ["(dietary recommendations)", "(restrictions if any)", "(special considerations)"]
  }},
  "exercise_physiotherapy_plan": {{
    "recommended_program": [
      {{
        "activity": "(type of exercise)",
        "description": "(detailed description with intensity/duration)"
      }}
    ]
  }},
  "management_advice_triggers": {{
    "condition_name": {{
      "status": "(current status)",
      "action": "(recommended action)"
    }},
    "additional_advice": "(other management recommendations)"
  }},
  "red_flags_emergency_return": {{
    "seek_immediate_medical_attention_if": [
      "(symptom/sign 1)",
      "(symptom/sign 2)",
      "(symptom/sign 3)"
    ]
  }},
  "follow_up_plan": {{
    "specialty_clinic": "(clinic name and frequency)",
    "investigations": "(recommended tests/scans)",
    "medication_review": "(timing and details)",
    "lifestyle_modifications": "(key changes needed)"
  }},
  "integrated_report_summary": {{
    "main_problems": "(primary diagnoses/concerns)",
    "critical_findings": (null if none, or describe critical findings),
    "care_plan_summary": ["(key point 1)", "(key point 2)", "(key point 3)"],
    "advisor": "(clinician name or 'AI Medical Assistant')"
  }}
}}

IMPORTANT INSTRUCTIONS:
1. Keep the 8 section names EXACTLY as specified
2. Populate EVERY section with relevant, realistic data extracted from the medical information
3. Do NOT use placeholder text - use actual extracted data
4. Add additional fields within sections if clinically relevant (e.g., lab values, additional findings)
5. For any section with no available data, use empty arrays/objects, null for numbers, empty strings for text
6. Return ONLY valid JSON, no markdown or extra text"""

        report_messages = [
            {"role": "system", "content": "You are an expert medical report generator. Create comprehensive, structured medical reports based on clinical documents and findings."},
            {"role": "user", "content": report_prompt}
        ]

        resp2 = self.openai_client.chat.completions.create(
            model="gpt-4o",
            messages=report_messages,
            temperature=0.3,
            max_tokens=4096,
            response_format={"type": "json_object"}
        )
        
        return json.loads(resp2.choices[0].message.content)

    def generate_report(self, user_id: str) -> Dict[str, Any]:
        patient = self.fetch_patient_data(user_id)
        urls = self.extract_cloudinary_urls(patient)
        files = []
        for i, u in enumerate(urls):
            filename = f"{u['field'].replace('.', '_')}_{i}.{u['type']}"
            path = self.download_file(u['url'], filename)
            files.append({**u, "path": path})
        analysis = self.analyze_with_openai(patient, files)
        report = {
            "patient_id": user_id,
            # "patient_data": patient,
            # "files_analyzed": [{"field": f['field'], "url": f['url'], "type": f['type']} for f in files],
            "medical_analysis": analysis,
            "generation_timestamp": datetime.now().isoformat()
        }
        return report
