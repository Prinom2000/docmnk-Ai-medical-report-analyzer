import os
import json
import base64
import mimetypes
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncio

import aiohttp
from openai import AsyncOpenAI
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
        self.openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.base_url = settings.BASE_URL
        self.temp_dir = Path("temp_medical_files")
        self.temp_dir.mkdir(exist_ok=True)

    async def fetch_patient_data(self, user_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/patient-registration/{user_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                response.raise_for_status()
                return await response.json()

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

    async def download_file(self, url: str, filename: str) -> Optional[Path]:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as response:
                response.raise_for_status()
                file_path = self.temp_dir / filename
                content = await response.read()
                await asyncio.to_thread(file_path.write_bytes, content)
                return file_path

    async def encode_image_to_base64(self, image_path: Path) -> str:
        def _encode():
            with open(image_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        
        return await asyncio.to_thread(_encode)

    async def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract text from PDF using PyPDF2."""
        if PyPDF2 is None:
            return ""
        
        def _extract():
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
        
        return await asyncio.to_thread(_extract)

    async def extract_text_from_files(self, files: List[Dict[str, Any]]) -> str:
        """Extract text from all downloaded files (images + PDFs) using OCR."""
        extracted_texts: List[str] = []
        
        for f in files:
            try:
                if f.get('type') == 'pdf' and f.get('path'):
                    text = await self.extract_text_from_pdf(f['path'])
                    if text and text.strip():
                        extracted_texts.append(f"--- Text from {f['field']} (PDF) ---\n{text}")
                elif f.get('type') == 'image' and f.get('path'):
                    ocr_text = ""
                    if Image is not None and pytesseract is not None:
                        try:
                            ocr_text = await asyncio.to_thread(self._ocr_image, f['path'])
                        except Exception as e:
                            print(f"Image OCR failed for {f['path']}: {e}")

                    if ocr_text and ocr_text.strip():
                        extracted_texts.append(f"--- OCR text from {f['field']} (IMAGE) ---\n{ocr_text}")
                    else:
                        extracted_texts.append(f"--- Image file included: {f['field']} (OCR not available) ---")
                else:
                    if f.get('path'):
                        extracted_texts.append(f"--- File included: {f['field']} (type: {f.get('type')}) ---")
            except Exception as e:
                print(f"Error extracting text from {f.get('field')}: {e}")

        return "\n".join(extracted_texts)

    def _ocr_image(self, image_path: Path) -> str:
        """Helper method for OCR to be run in thread."""
        img = Image.open(image_path)
        return pytesseract.image_to_string(img)

    def get_medical_guidelines_prompt(self) -> str:
        """Return comprehensive medical guidelines for AI analysis."""
        return """
# COMPREHENSIVE MEDICAL ANALYSIS GUIDELINES

## MANDATORY CALCULATIONS (Perform where data exists):

### 1. BMI CALCULATION
Formula: BMI = weight(kg) / [height(m)]²
Classifications:
- WHO: <18.5 Underweight, 18.5-24.9 Normal, 25.0-29.9 Overweight, ≥30.0 Obese
- Indian RSSDI: <18.5 Underweight, 18.5-22.9 Normal, 23.0-24.9 Overweight, 25.0-32.9 Obese, ≥33.0 Severely Obese

### 2. BMR & TDEE (Mifflin-St Jeor)
Men: BMR = (10 × weight_kg) + (6.25 × height_cm) - (5 × age) + 5
Women: BMR = (10 × weight_kg) + (6.25 × height_cm) - (5 × age) - 161
TDEE = BMR × Activity Factor (Sedentary: 1.2, Light: 1.375, Moderate: 1.55, Very: 1.725, Extra: 1.9)

### 3. TOBACCO RISK
Pack-Years = (packs/day) × years OR (bidis/day × years) / 43
Smoking Index = (cigarettes or bidis/day) × years
Chewing Index = (quids/day) × years
Risk: <20/<400 Low, 20-40/400-799 Moderate, >40/≥800 High

### 4. DAILY STEPS
Children: 6,000-12,000, Adults: 7,000-12,000, Seniors: 6,000-10,000
Conversion: Men km = steps × 0.78/1000, Women km = steps × 0.70/1000

### 5. SLEEP ASSESSMENT
Age-based duration (hours): Newborns 14-17, Infants 12-15, Toddlers 11-14, 
Preschool 10-13, School-age 9-11, Teens 8-10, Adults 7-9, Seniors 7-8

### 6. SVS PULSE GRADING
0: Absent, 1+: Weak, 2+: Normal, 3+: Bounding
Sites: Femoral, Popliteal, Anterior Tibial, Posterior Tibial, Dorsalis Pedis

### 7. RUTHERFORD CLASSIFICATION (Arterial Disease)
Class 0: Asymptomatic, 1-3: Claudication, 4: Rest pain, 5: Minor tissue loss, 6: Major tissue loss

### 8. CALORIE DEFICIT
For weight loss: 400-1,000 kcal/day deficit = 0.5-1 kg/week loss
Macros: Protein 1.2-2.0 g/kg, Fat 20-35%, Carbs 45-65%
Fluid: Men 2.5-3.7 L/day, Women 2.0-2.7 L/day
"""

    async def analyze_with_openai(self, patient_data: Dict[str, Any], files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Dynamic analysis with mandatory core sections + flexible lab sections."""
        
        # Extract text from all files with OCR
        extracted_text = await self.extract_text_from_files(files)
        
        # Stage 1: Comprehensive extraction with lab content identification
        extraction_messages = [
            {
                "role": "system", 
                "content": f"""You are an expert medical data extraction assistant with OCR analysis capabilities.

{self.get_medical_guidelines_prompt()}

EXTRACTION PROTOCOL:
1. Extract ALL patient demographics, biometrics, vitals
2. Identify ALL laboratory test categories present (e.g., CBC, LFT, RFT, Lipid Profile, Thyroid, HbA1c, Electrolytes, Hormones, Tumor Markers, etc.)
3. Extract ALL lab values with units and reference ranges
4. Extract ALL physical examination findings
5. Extract ALL medical history and comorbidities
6. Extract ALL substance use history with quantities
7. Extract ALL lifestyle data (occupation, activity, sleep, diet, steps)
8. Extract ALL lower limb vascular findings
9. Extract ALL medications and allergies

IMPORTANT: For lab results, identify the EXACT test categories present in the documents, don't assume standard categories."""
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text", 
                        "text": f"""Extract ALL medical information from these sources:

PATIENT REGISTRATION DATA:
{json.dumps(patient_data, indent=2)}

EXTRACTED TEXT FROM ALL FILES (PDF & OCR):
{extracted_text}

Provide comprehensive extraction with:
1. Complete patient demographics
2. IDENTIFIED LAB TEST CATEGORIES (list exactly what lab sections exist)
3. All lab values organized by their actual categories
4. All vital signs and anthropometric data
5. Complete medical and substance use history
6. Physical examination findings
7. Lifestyle assessment data
8. Current medications and allergies

Return detailed JSON with actual lab categories found."""
                    }
                ]
            }
        ]
        
        # Add all images for visual analysis
        for f in files:
            if f['type'] == 'image' and f['path']:
                base64_img = await self.encode_image_to_base64(f['path'])
                mime = mimetypes.guess_type(f['path'])[0] or 'image/jpeg'
                extraction_messages[-1]["content"].append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{base64_img}"}
                })

        resp1 = await self.openai_client.chat.completions.create(
            model="gpt-4o",
            messages=extraction_messages,
            temperature=0.2,
            max_tokens=4000
        )
        extracted_data = resp1.choices[0].message.content
        
        # Stage 2: Generate structured report with dynamic lab sections
        report_prompt = f"""Generate a COMPREHENSIVE medical report with MANDATORY core sections and DYNAMIC lab sections.

{self.get_medical_guidelines_prompt()}

EXTRACTED DATA:
{extracted_data}

PATIENT REGISTRATION:
{json.dumps(patient_data, indent=2)}

Generate JSON following this EXACT structure:

{{
  "patient_info": {{
    "name": "string",
    "age": number,
    "gender": "Male/Female/Other",
    "occupation": "string",
    "occupation_activity_classification": "Sedentary/Intermediate/Active",
    "address": {{"area": "", "locality": "", "city": "", "state": ""}},
    "contact": "string",
    "dietary_preference": "Vegetarian/Non-vegetarian/Vegan/Eggetarian",
    "allergies": ["list"],
    "presenting_complaints": "free text"
  }},
  
  "vital_signs": {{
    "blood_pressure": {{"systolic": number, "diastolic": number, "unit": "mmHg"}},
    "heart_rate": {{"value": number, "unit": "bpm"}},
    "respiratory_rate": {{"value": number, "unit": "breaths/min"}},
    "spo2": {{"value": number, "unit": "%"}},
    "temperature": {{"value": number, "unit": "°C"}}
  }},
  
  "anthropometric_measurements": {{
    "height": {{"value": number, "unit": "cm"}},
    "weight": {{"value": number, "unit": "kg"}},
    "bmi": {{
      "value": number,
      "who_classification": "Underweight/Normal/Overweight/Obese",
      "indian_rssdi_classification": "string",
      "interpretation": "string"
    }}
  }},
  
  "examination_findings": {{
    "general_appearance": "string",
    "cardiovascular": "string",
    "respiratory": "string",
    "abdominal": "string",
    "neurological": "string",
    "musculoskeletal": {{
      "joint_issues": ["list"],
      "previous_fractures": ["list"],
      "mobility_limitations": ["list"],
      "deformities": ["list"]
    }},
    "lower_limb_vascular_assessment": {{
      "pulse_grading_svs": {{
        "femoral": {{"left": "0/1+/2+/3+", "right": "0/1+/2+/3+", "notes": ""}},
        "popliteal": {{"left": "0/1+/2+/3+", "right": "0/1+/2+/3+", "notes": ""}},
        "anterior_tibial": {{"left": "0/1+/2+/3+", "right": "0/1+/2+/3+", "notes": ""}},
        "posterior_tibial": {{"left": "0/1+/2+/3+", "right": "0/1+/2+/3+", "notes": ""}},
        "dorsalis_pedis": {{"left": "0/1+/2+/3+", "right": "0/1+/2+/3+", "notes": ""}}
      }},
      "arterial_findings": {{
        "intermittent_claudication": boolean,
        "claudication_distance_meters": number,
        "rest_pain": boolean,
        "skin_changes": ["list"],
        "rutherford_classification": "Class 0-6 with rationale"
      }},
      "venous_findings": {{
        "varicose_veins": boolean,
        "edema": "None/Pitting/Brawny",
        "skin_changes": ["list"]
      }},
      "lymphatic_findings": {{
        "lymphedema": boolean,
        "severity": "Mild/Moderate/Severe"
      }},
      "diabetic_foot_assessment": {{
        "neuropathy": boolean,
        "ulcers": ["list with details"],
        "deformities": ["list"],
        "infection_signs": boolean
      }},
      "ulcer_documentation": {{
        "present": boolean,
        "details": [{{
          "site": "", "size": "", "depth": "", "floor": "", 
          "discharge": "", "infection_signs": "", "pain_score": "",
          "exposed_structures": [""], "healing_status": ""
        }}]
      }},
      "skin_assessment": {{
        "color": "normal/pallor/rubor/cyanosis/mottling",
        "temperature": "warm/cool",
        "hair_growth": "normal/reduced/absent",
        "nail_changes": ["list"]
      }}
    }},
    "other_findings": "string"
  }},
  
  "laboratory_results": {{
    "_note": "DYNAMIC SECTION - Include ONLY lab categories found in actual reports",
    "_instructions": "Create subsections for each lab test category identified (e.g., complete_blood_count, liver_function_tests, renal_function_tests, lipid_profile, thyroid_function, hba1c, electrolytes, etc.)",
    "lab_categories_identified": ["list of actual categories found"],
    
    "EXAMPLE_complete_blood_count": {{
      "test_date": "YYYY-MM-DD",
      "hemoglobin": {{"value": number, "unit": "g/dL", "reference_range": "13-17", "status": "normal/high/low"}},
      "total_wbc": {{"value": number, "unit": "cells/μL", "reference_range": "", "status": ""}},
      "platelet_count": {{"value": number, "unit": "lakhs/μL", "reference_range": "", "status": ""}},
      "_add_all_tests_found": "Include every test with value, unit, range, status"
    }},
    
    "EXAMPLE_lipid_profile": {{
      "test_date": "YYYY-MM-DD",
      "total_cholesterol": {{"value": number, "unit": "mg/dL", "reference_range": "", "status": ""}},
      "ldl": {{"value": number, "unit": "mg/dL", "reference_range": "", "status": ""}},
      "hdl": {{"value": number, "unit": "mg/dL", "reference_range": "", "status": ""}},
      "triglycerides": {{"value": number, "unit": "mg/dL", "reference_range": "", "status": ""}}
    }},
    
    "_create_similar_sections": "For ALL lab categories found in the reports",
    
    "abnormal_findings_summary": ["list all abnormal results with clinical significance"],
    "critical_values": ["list any critical/urgent findings"]
  }},
  
  "medical_history_comorbidities": {{
    "diabetes": {{
      "present": boolean,
      "type": "Type 1/Type 2/Gestational/Other",
      "duration_years": number,
      "controlled": boolean,
      "medications": ["list"],
      "last_hba1c": {{"value": number, "date": "YYYY-MM-DD"}},
      "last_fbs_rbs": {{"fbs": number, "rbs": number, "unit": "mg/dL"}},
      "complications": ["Retinopathy/Nephropathy/Neuropathy"]
    }},
    "hypertension": {{
      "present": boolean,
      "duration_years": number,
      "controlled": boolean,
      "medications": ["list"],
      "complications": ["list"]
    }},
    "dyslipidemia": {{"present": boolean, "controlled": boolean, "medications": ["list"]}},
    "cardiovascular_disease": {{
      "ihd": boolean,
      "cad": boolean,
      "type": "string",
      "complications": ["list"]
    }},
    "thyroid_disorders": {{
      "hypothyroidism": {{"present": boolean, "medications": ["list"]}},
      "hyperthyroidism": {{"present": boolean, "medications": ["list"]}}
    }},
    "other_conditions": ["list all other medical conditions"]
  }},
  
  "substance_use_history": {{
    "smoking": {{
      "status": "Never/Former/Current",
      "type": "Cigarette/Beedi",
      "quantity_per_day": number,
      "duration_years": number,
      "pack_years": number,
      "smoking_index": number,
      "risk_category": "Low/Moderate/High",
      "abstinence_months": number
    }},
    "tobacco_chewing": {{
      "status": boolean,
      "quids_per_day": number,
      "duration_years": number,
      "chewing_index": number,
      "risk_category": "Low/Moderate/High"
    }},
    "betel_nut": {{
      "status": boolean,
      "quids_per_day": number,
      "duration_years": number,
      "chewing_index": number,
      "risk_category": "Low/Moderate/High"
    }},
    "alcohol": {{"status": "Never/Former/Current", "details": "string"}},
    "total_tobacco_risk": "Low/Moderate/High with rationale"
  }},
  
  "lifestyle_assessment": {{
    "occupation_activity": {{
      "occupation": "string",
      "classification": "Sedentary/Intermediate/Active",
      "rationale": "string"
    }},
    "physical_activity": {{
      "daily_steps": {{"value": number, "distance_km": number, "classification": "Below/Meeting/Exceeding recommendations"}},
      "exercise_frequency": "string",
      "exercise_type": ["list"]
    }},
    "sleep": {{
      "duration_hours": number,
      "quality": "Good/Fair/Poor",
      "disturbances": ["list"],
      "classification": "Adequate/Insufficient/Excessive for age",
      "recommendations": "string"
    }},
    "diet_habits": {{
      "type": "Vegetarian/Non-vegetarian/Mixed",
      "meal_frequency": number,
      "water_intake_liters": number,
      "concerns": ["list"]
    }}
  }},
  
  "risk_stratification": {{
    "components": [
      {{
        "category": "ARTERIAL/VENOUS/DIABETIC_FOOT/CARDIOVASCULAR/METABOLIC",
        "risk_level": "Low/Mild/Moderate/High/Critical",
        "findings": ["list specific findings"],
        "rationale": "clinical reasoning"
      }}
    ],
    "overall_risk_assessment": "string with comprehensive summary"
  }},
  
  "key_calculations": {{
    "bmi": {{"value": number, "who": "string", "indian": "string"}},
    "bmr_mifflin_st_jeor": {{"value": number, "unit": "kcal/day"}},
    "tdee": {{
      "sedentary": number,
      "current_activity_level": number,
      "activity_level_used": "string"
    }},
    "calorie_deficit_needed": {{
      "current_bmi_category": "string",
      "target_daily_calories": number,
      "deficit_amount": number,
      "expected_weight_loss": "0.5-1 kg/week"
    }},
    "total_tobacco_risk": "Low/Moderate/High",
    "cardiovascular_risk_score": "if applicable"
  }},
  
  "individualized_diet_plan": {{
    "target_calories": number,
    "calorie_goal": number,
    "unit": "kcal/day",
    "type": "Vegetarian/Non-vegetarian",
    "macronutrient_distribution": {{
      "protein": {{"grams": number, "range_gkg": "1.2-2.0", "percentage": "15-20%"}},
      "carbohydrates": {{"grams": number, "percentage": "45-65%"}},
      "fat": {{"grams": number, "percentage": "20-35%"}}
    }},
    "fluid_intake": {{"target_liters": number, "schedule": "string"}},
    "meals": [
      {{
        "meal_name": "Breakfast",
        "time": "7:00 AM",
        "foods": "Detailed food list with portions (e.g., Oats porridge 30g, 1 cup skim milk, 8 almonds, 2 walnuts, 1 apple)",
        "calories": number,
        "protein": "Xg",
        "carbs": "Xg",
        "fat": "Xg"
      }},
      {{
        "meal_name": "Mid-morning",
        "time": "10:00 AM",
        "foods": "Specific foods",
        "calories": number,
        "protein": "Xg",
        "carbs": "Xg",
        "fat": "Xg"
      }},
      {{
        "meal_name": "Lunch",
        "time": "1:00 PM",
        "foods": "Complete meal description",
        "calories": number,
        "protein": "Xg",
        "carbs": "Xg",
        "fat": "Xg"
      }},
      {{
        "meal_name": "Evening Snack",
        "time": "4:00 PM",
        "foods": "Specific foods",
        "calories": number,
        "protein": "Xg",
        "carbs": "Xg",
        "fat": "Xg"
      }},
      {{
        "meal_name": "Dinner",
        "time": "7:00 PM",
        "foods": "Complete meal description",
        "calories": number,
        "protein": "Xg",
        "carbs": "Xg",
        "fat": "Xg"
      }}
    ],
    "daily_totals": {{
      "calories": number,
      "protein": "Xg",
      "carbs": "Xg",
      "fat": "Xg"
    }},
    "notes": [
      "Adjust portion sizes to reach calorie goal of X kcal/day",
      "Consider patient allergies: [list]",
      "Based on vegetarian/non-vegetarian preference",
      "All meals split every 3-4 hours",
      "Local dietary habits incorporated"
    ],
    "weekly_variation": "Rotate proteins, vary vegetables, alternate grains for variety"
  }},
  
  "exercise_physiotherapy_plan": {{
    "considerations": {{
      "mobility_limitations": ["list"],
      "joint_issues": ["list"],
      "previous_fractures": ["list"],
      "contraindications": ["list"],
      "current_fitness_level": "Sedentary/Beginner/Intermediate"
    }},
    "recommended_program": [
      {{
        "activity_type": "Walking Program",
        "description": "Start 15-20 minutes daily, gradually increase to 30-45 minutes",
        "frequency": "5-7 days/week",
        "intensity": "Moderate pace",
        "duration": "15-45 minutes",
        "progression": "Increase by 5 minutes weekly",
        "modifications": "If claudication occurs, rest until pain subsides, then continue"
      }},
      {{
        "activity_type": "Interval Training",
        "description": "Alternate walking speeds if tolerated",
        "frequency": "3 times/week",
        "modifications": "Based on symptoms"
      }},
      {{
        "activity_type": "Resistance Training",
        "description": "Light weights or body weight exercises",
        "exercises": ["Wall push-ups", "Chair squats", "Seated leg raises"],
        "frequency": "2-3 times/week",
        "modifications": "Avoid if severe joint pain"
      }},
      {{
        "activity_type": "Flexibility & Balance",
        "description": "Gentle stretching and balance exercises",
        "exercises": ["Ankle circles", "Calf stretches", "Standing balance"],
        "frequency": "Daily",
        "duration": "10-15 minutes"
      }}
    ],
    "warm_up": "5 minutes gentle stretching/breathing",
    "cool_down": "5 minutes gentle stretching",
    "hydration": "200-300ml water before/after session",
    "sleep_hygiene": "Prioritize 7-8 hours nightly, optimize sleep environment",
    "target_distance": "Progressive increase, monitor symptoms",
    "safety_precautions": [
      "Stop if severe pain, dizziness, or chest discomfort",
      "Wear proper footwear",
      "Exercise in safe, well-lit areas",
      "Monitor blood sugar if diabetic"
    ]
  }},
  
  "management_advice_triggers": {{
    "diabetes": {{
      "status": "Uncontrolled/Controlled/Not present",
      "action": "Immediate endocrinology referral/start treatment" OR "Continue current management"
    }},
    "hypertension": {{
      "status": "string",
      "action": "specific recommendation"
    }},
    "foot_care": {{
      "status": "At risk/Ulcer present/Normal",
      "action": "NO home cutting of nails/calluses, no heat pads, daily inspection required"
    }},
    "tobacco_cessation": {{
      "status": "Active use/Former/Never",
      "action": "Increased vascular risk counseling, cessation support, de-addiction clinic referral"
    }},
    "medication_adherence": {{
      "status": "string",
      "action": "Review all comorbidity medications, ensure regular follow-up"
    }},
    "wound_care": {{
      "present": boolean,
      "action": "Specific care: moisture, moisturization, proper footwear"
    }},
    "lifestyle_modifications": [
      "Graded walking program as tolerated",
      "Immediate specialty review (see referrals)",
      "Strict foot care protocol and self-monitoring"
    ],
    "additional_advice": "All risk/plan details included above, follow international guidelines"
  }},
  
  "red_flags_emergency_return": {{
    "seek_immediate_medical_attention_if": [
      "Sudden severe chest pain or pressure",
      "Difficulty breathing or shortness of breath at rest",
      "Sudden weakness, numbness, or loss of sensation",
      "Rapidly spreading wound infection (increasing redness, warmth, pus)",
      "Uncontrolled bleeding from wound",
      "Signs of gangrene (blackened or cold tissue)",
      "High fever (>101°F) with chills or confusion",
      "Severe rest pain not relieved by position changes",
      "Sudden color change in limb (pale, blue, or mottled)",
      "Loss of consciousness or severe dizziness",
      "New or worsening claudication significantly limiting walking"
    ]
  }},
  
  "follow_up_plan": {{
    "next_appointment": "Timeframe (e.g., 2 weeks, 1 month)",
    "specialty_clinic_referrals": [
      {{"clinic": "Endocrinology", "reason": "Uncontrolled diabetes, medication initiation/adjustment", "urgency": "Immediate/Routine"}},
      {{"clinic": "Dietitian/Nutritionist", "reason": "Personalized meal planning, comorbidity management, weight optimization", "urgency": ""}},
      {{"clinic": "De-addiction/Psychiatry", "reason": "Smoking/tobacco cessation support, substance use counseling", "urgency": ""}},
      {{"clinic": "Vascular Surgery", "reason": "If critical limb ischemia or severe PAD", "urgency": ""}},
      {{"clinic": "Podiatry/Wound Care", "reason": "If diabetic foot ulcers present", "urgency": ""}}
    ],
    "investigations_required": [
      {{"test": "HbA1c", "timing": "Every 3 months", "indication": "Diabetes monitoring"}},
      {{"test": "Lipid profile", "timing": "Every 6 months", "indication": "CVD risk"}},
      {{"test": "ABI (Ankle-Brachial Index)", "timing": "If not done or symptoms worsen", "indication": "PAD assessment"}},
      {{"test": "Doppler ultrasound", "timing": "As per vascular specialist", "indication": "Arterial assessment"}}
    ],
    "medication_review": "Review all comorbidity medications, ensure adherence, adjust as per specialist recommendations",
    "self_monitoring": [
      "Daily foot inspection",
      "Blood pressure monitoring if hypertensive",
      "Blood glucose monitoring if diabetic",
      "Weight tracking weekly",
      "Exercise log maintenance"
    ]
  }},
  
  "integrated_report_summary": {{
    "patient": {{
      "demographics": "Age, gender, occupation details",
      "dietary_preference": "Vegetarian/Non-vegetarian"
    }},
    "main_problems": "Primary diagnoses and key concerns (e.g., Uncontrolled diabetes, PAD, obesity)",
    "critical_findings": "Any urgent/critical findings requiring immediate attention" OR null,
    "care_plan_summary": [
      "Graded walking program as tolerated",
      "Immediate specialty review (endocrinology, dietitian, de-addiction)",
      "Tailored diet: ~X kcal/day, Vegetarian/Non-vegetarian",
      "Strict foot care protocol and self-monitoring",
      "Red flag education provided",
      "Tobacco cessation counseling and support"
    ],
    "advice": "All risk stratifications per ADA, ESC, EASO, WHO, ICMR, MoHFW, and international vascular guidelines. All risk/plan details included above.",
    "advisor": "AI Medical Assistant",
    "supervising_physician": "Report to be reviewed and co-signed by attending physician",
    "data_quality_assessment": "Complete/Partial data available, OCR extraction quality assessment"
  }},
  
  "referrals_suggested": [
    {{
      "specialty": "Endocrinology",
      "reason": "Uncontrolled diabetes, medication initiation/adjustment required",
      "urgency": "Immediate"
    }},
    {{
      "specialty": "Dietitian/Nutritionist",
      "reason": "Personalized meal planning, comorbidity management, weight optimization",
      "urgency": "Routine"
    }},
    {{
      "specialty": "De-addiction Clinic/Psychiatry",
      "reason": "Smoking/tobacco cessation support, substance use counseling",
      "urgency": "Routine"
    }}
  ],
  
  "additional_recommendations": [
    "Regular physical activity as per exercise plan",
    "Stress management techniques",
    "Support group participation for chronic disease management",
    "Family education regarding emergency signs",
    "Regular follow-up adherence critical for outcomes"
  ],
  
  "report_metadata": {{
    "generation_timestamp": "ISO timestamp",
    "files_analyzed": ["list of cloudinary URLs and file types"],
    "extraction_methods": ["OCR", "PDF text extraction", "Image analysis"],
    "lab_categories_present": ["list of actual lab sections found"],
    "calculations_performed": ["BMI", "BMR", "TDEE", "Pack-years", etc.],
    "guidelines_referenced": [
      "WHO BMI Classification",
      "Indian RSSDI 2022 Guidelines",
      "Mifflin-St Jeor Equation",
      "SVS Pulse Grading",
      "Rutherford Classification",
      "ADA Diabetes Guidelines",
      "ESC Cardiovascular Guidelines",
      "International Tobacco Control Guidelines"
    ]
  }}
}}

CRITICAL INSTRUCTIONS:
1. **CALCULATE ALL METRICS** where data exists using exact formulas
2. **DYNAMIC LAB SECTIONS**: Create lab subsections ONLY for categories actually found in reports
3. **COMPLETE DIET PLAN**: Provide specific foods, portions, timing, macros for each meal
4. **DETAILED EXERCISE PLAN**: Include specific exercises, duration, frequency, modifications
5. **USE ACTUAL DATA**: No placeholders - extract from OCR/PDF text
6. **FOLLOW IMAGE EXAMPLES**: Match the format shown in the diet/exercise/summary images
7. **PULSE GRADING**: Use SVS scale (0, 1+, 2+, 3+) for all documented pulses
8. **RISK STRATIFICATION**: Separate arterial, venous, lymphatic, diabetic foot risks
9. **REFERRALS**: List specific specialties with clear reasons
10. **RED FLAGS**: Comprehensive list of emergency signs

Return ONLY valid JSON, no markdown."""

        report_messages = [
            {
                "role": "system", 
                "content": "You are an expert medical report generator with comprehensive knowledge of international clinical guidelines. You excel at creating detailed, evidence-based reports with accurate calculations and practical recommendations. You adapt lab result sections dynamically based on actual test results present."
            },
            {"role": "user", "content": report_prompt}
        ]

        resp2 = await self.openai_client.chat.completions.create(
            model="gpt-4o",
            messages=report_messages,
            temperature=0.2,
            max_tokens=8000,
            response_format={"type": "json_object"}
        )
        
        return json.loads(resp2.choices[0].message.content)

    async def analyze_file_only(self, file_path: Path, file_type: str) -> Dict[str, Any]:
        """Analyze a single file with comprehensive guidelines and dynamic lab sections."""
        files = [{
            "url": str(file_path),
            "field": file_path.name,
            "type": file_type,
            "path": file_path
        }]
        
        extracted_text = await self.extract_text_from_files(files)
        
        # Comprehensive extraction
        extraction_messages = [
            {
                "role": "system", 
                "content": f"""You are an expert medical data extraction assistant with OCR capabilities.

{self.get_medical_guidelines_prompt()}

Extract ALL medical information from this single document, identifying actual lab test categories present."""
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text", 
                        "text": f"""Extract comprehensive medical data from this document:

EXTRACTED TEXT (OCR/PDF):
{extracted_text}

Include:
- Patient demographics if present
- ALL lab test categories identified (exact names)
- All lab values with units and ranges
- Vital signs and measurements
- Clinical findings
- Any diagnoses or recommendations

Return detailed JSON with identified lab categories."""
                    }
                ]
            }
        ]
        
        if file_type == 'image':
            base64_img = await self.encode_image_to_base64(file_path)
            mime = mimetypes.guess_type(str(file_path))[0] or 'image/jpeg'
            extraction_messages[-1]["content"].append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{base64_img}"}
            })

        resp1 = await self.openai_client.chat.completions.create(
            model="gpt-4o",
            messages=extraction_messages,
            temperature=0.2,
            max_tokens=3000
        )
        extracted_data = resp1.choices[0].message.content
        
        # Generate structured report
        report_prompt = f"""Based on this single document, generate a focused medical analysis with dynamic lab sections.

{self.get_medical_guidelines_prompt()}

EXTRACTED DATA:
{extracted_data}

Generate JSON with:
1. **document_info**: Type, date, source
2. **patient_info**: If available from document
3. **laboratory_results**: DYNAMIC - create subsections for each actual lab category found
4. **vital_signs**: If present
5. **clinical_findings**: Any examination findings
6. **calculations**: Perform BMI, etc. if height/weight present
7. **interpretations**: Clinical significance of findings
8. **recommendations**: Based on results
9. **integrated_summary**: Key findings and next steps

IMPORTANT: 
- Create lab subsections dynamically based on actual categories in document
- Use exact formulas for any calculations possible
- Flag abnormal/critical values
- Provide clinical interpretations

Return ONLY valid JSON."""

        report_messages = [
            {
                "role": "system", 
                "content": "You are an expert medical document analyzer. Create focused, dynamically-structured analyses based on document content with accurate calculations."
            },
            {"role": "user", "content": report_prompt}
        ]

        resp2 = await self.openai_client.chat.completions.create(
            model="gpt-4o",
            messages=report_messages,
            temperature=0.2,
            max_tokens=4096,
            response_format={"type": "json_object"}
        )
        
        return json.loads(resp2.choices[0].message.content)

    async def generate_report(self, user_id: str) -> Dict[str, Any]:
        """Generate comprehensive report with mandatory core sections and dynamic lab sections."""
        patient = await self.fetch_patient_data(user_id)
        urls = self.extract_cloudinary_urls(patient)
        files = []
        
        for i, u in enumerate(urls):
            filename = f"{u['field'].replace('.', '_')}_{i}.{u['type']}"
            try:
                path = await self.download_file(u['url'], filename)
                files.append({**u, "path": path})
            except Exception as e:
                print(f"Error downloading file {u['url']}: {e}")
                files.append({**u, "path": None, "error": str(e)})
        
        analysis = await self.analyze_with_openai(patient, files)
        
        report = {
            "patient_id": user_id,
            "medical_analysis": analysis,
            "files_analyzed": [
                {
                    "field": f['field'], 
                    "url": f['url'], 
                    "type": f['type'],
                    "status": "processed" if f.get('path') else "error"
                } for f in files
            ],
            "generation_timestamp": datetime.now().isoformat(),
            "report_type": "comprehensive_medical_analysis",
            "analysis_method": "hybrid_dynamic_structure"
        }
        
        return report