import os
import base64
import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

import fitz  # PyMuPDF
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

# Load environment variables
load_dotenv()

# Initialize the Groq Chat model with a Vision-capable model
# Using llama-3.2-90b-vision-preview as it is specifically designed for image reasoning
def get_vision_llm():
    return ChatGroq(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        temperature=0.1,  # Low temperature for deterministic extraction
        max_tokens=500,
    )

def get_text_llm():
    return ChatGroq(
        model="openai/gpt-oss-120b",
        temperature=0.1,
    )

class DocumentAnalysisResult(BaseModel):
    quality: str = Field(description="The quality of the document: GOOD, FAIR, POOR, or UNREADABLE")
    patient_name: str | None = Field(description="The patient name extracted from the document, or null if not found")
    detected_type: str = Field(description="The exact document type detected, must be one of: PRESCRIPTION, HOSPITAL_BILL, LAB_REPORT, DIAGNOSTIC_REPORT, PHARMACY_BILL, DENTAL_REPORT, DISCHARGE_SUMMARY, or UNKNOWN")

def encode_file_to_base64(file_path: str) -> str:
    """Read a file and convert it to a base64 encoded string.
    If it's a PDF, render the first page to an image.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()
    if ext == ".pdf":
        # Convert first page of PDF to image
        doc = fitz.open(str(path))
        if len(doc) == 0:
            raise ValueError("PDF is empty")
        page = doc.load_page(0)
        # Render at 150 DPI for decent quality but manageable size
        pix = page.get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72))
        image_bytes = pix.tobytes("png")
        doc.close()
        return base64.b64encode(image_bytes).decode('utf-8')
    else:
        # Assume it's an image
        with open(path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

def analyze_document(file_path: str) -> DocumentAnalysisResult:
    """Analyze a document for quality and extract the patient name using a Vision LLM."""
    if not os.environ.get("GROQ_API_KEY"):
        print("Warning: GROQ_API_KEY not set. Simulating LLM response.")
        return DocumentAnalysisResult(quality="GOOD", patient_name="Rajesh Kumar", detected_type="UNKNOWN")

    try:
        base64_image = encode_file_to_base64(file_path)
    except Exception as e:
        print(f"Error encoding file: {e}")
        return DocumentAnalysisResult(quality="UNREADABLE", patient_name=None, detected_type="UNKNOWN")

    llm = get_vision_llm()
    parser = JsonOutputParser(pydantic_object=DocumentAnalysisResult)

    prompt_text = f"""
    You are an expert document analysis assistant for a health insurance claims system.
    Please analyze the provided document image and output a JSON object with three fields: 'quality', 'patient_name', and 'detected_type'.

    1. **Document Quality Evaluation:**
    Carefully assess the legibility and overall quality of the document based on the following criteria:
    - **GOOD**: The document is perfectly clear, well-lit, fully legible, and all text is easily readable without any effort. No parts are obscured or blurred.
    - **FAIR**: The document has minor issues like slight blurriness, slight shadows, or minor glare, but all critical information (names, dates, amounts, medical terms) can still be read and understood.
    - **POOR**: The document has significant issues such as severe blur, low resolution, very bad lighting, or parts of the document being cut off. Reading critical information requires significant effort and guessing.
    - **UNREADABLE**: The document is completely illegible, extremely blurry, too dark/bright, or is not a document at all. No text can be confidently extracted.

    Determine the quality and output one of these exact strings: "GOOD", "FAIR", "POOR", "UNREADABLE".

    2. **Patient Name Extraction:**
    Carefully scan the document to locate the name of the patient.
    - Look for explicit labels such as "Patient Name:", "Name:", "Pt Name", or "Issued to:".
    - In prescriptions or lab reports, the patient's name is usually at the top, often near the age/gender or date.
    - In hospital bills, look for the "Billed To" section.
    - Be careful not to confuse the patient's name with the Doctor's name, the Hospital's name, or the person who signed the document.
    - Extract ONLY the full name of the patient as it appears on the document.
    - If you cannot find a patient name, output null.

    3. **Document Type Classification:**
    Classify the document into exactly one of the following categories based on its visual contents and layout:
    - "PRESCRIPTION": Doctor's notes prescribing medication, tests, or treatment.
    - "HOSPITAL_BILL": An invoice or bill from a hospital or clinic showing charges.
    - "PHARMACY_BILL": A receipt specifically for purchased medicines.
    - "LAB_REPORT" or "DIAGNOSTIC_REPORT": Results of blood tests, scans, or pathology.
    - "DENTAL_REPORT": Notes or reports specific to dental work.
    - "DISCHARGE_SUMMARY": A detailed summary given when a patient leaves a hospital.
    - "UNKNOWN": If the document is none of the above or cannot be identified.
    Output the exact string matching the classification.

    Provide ONLY the requested JSON output format.
    {format_instructions}
    """

    # Format the prompt
    format_instructions = parser.get_format_instructions()
    
    # Construct the message
    msg = HumanMessage(
        content=[
            {"type": "text", "text": prompt_text.replace("{format_instructions}", format_instructions)},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{base64_image}"},
            },
        ]
    )

    try:
        response = llm.invoke([msg])
        result = parser.invoke(response.content)
        return DocumentAnalysisResult(**result)
    except Exception as e:
        print(f"Error calling Vision LLM: {e}")
        # Graceful fallback if LLM fails (e.g. rate limit, parsing error)
        return DocumentAnalysisResult(quality="POOR", patient_name=None, detected_type="UNKNOWN")

class DocumentExtractionResult(BaseModel):
    confidence_score: float = Field(description="A confidence score between 0.0 and 1.0 indicating how certain you are of the extracted values.")
    extracted_fields: dict[str, Any] = Field(description="A dictionary containing the extracted fields.")

def extract_document_data(file_path: str, document_type: str) -> DocumentExtractionResult:
    """Extract structured data from a document using a Vision LLM."""
    if not os.environ.get("GROQ_API_KEY"):
        return DocumentExtractionResult(confidence_score=0.9, extracted_fields={})

    try:
        base64_image = encode_file_to_base64(file_path)
    except Exception as e:
        print(f"Error encoding file: {e}")
        return DocumentExtractionResult(confidence_score=0.0, extracted_fields={})

    llm = get_vision_llm()
    parser = JsonOutputParser(pydantic_object=DocumentExtractionResult)

    fields_to_extract = ""
    if document_type == "PRESCRIPTION":
        fields_to_extract = "- doctor_name (string), registration_number (string), specialization (string)\n    - patient_name (string), age (int), gender (string), date (string)\n    - diagnosis (string)\n    - medicines (list of dicts with 'name', 'dosage', 'duration')\n    - tests_ordered (list of strings)\n    - clinic_name (string), clinic_address (string)"
    elif document_type in ["HOSPITAL_BILL", "PHARMACY_BILL"]:
        fields_to_extract = "- hospital_name (string), hospital_address (string), gstin (string)\n    - bill_number (string), date (string)\n    - patient_name (string), age (int), gender (string)\n    - line_items (list of dicts with 'description', 'amount')\n    - gst_amount (float), total_amount (float)"
    elif document_type in ["LAB_REPORT", "DIAGNOSTIC_REPORT", "DENTAL_REPORT"]:
        fields_to_extract = "- lab_name (string), nabl_status (string)\n    - patient_name (string), age (int), gender (string)\n    - referring_doctor (string)\n    - sample_date (string), report_date (string)\n    - tests (list of dicts with 'test_name', 'result', 'unit', 'normal_range')\n    - pathologist_name (string), pathologist_registration (string)\n    - remarks (string)"
    else:
        fields_to_extract = "- patient_name (string), date (string)\n    - hospital_name (string)\n    - diagnosis (string)\n    - treatment (string)"

    prompt_text = f"""
    You are an expert medical document extraction assistant for a health insurance claims processing system.
    Your task is to extract structured information from the provided {document_type} image.

    Extract the following fields (if present):
    {fields_to_extract}

    Extract the values accurately. If a field is not found, omit it from the extracted_fields dictionary.
    Provide a 'confidence_score' between 0.0 and 1.0 representing your certainty in the extracted data.

    Provide ONLY the requested JSON output format.
    {{format_instructions}}
    """

    format_instructions = parser.get_format_instructions()
    msg = HumanMessage(
        content=[
            {"type": "text", "text": prompt_text.format(format_instructions=format_instructions)},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{base64_image}"},
            },
        ]
    )

    try:
        response = llm.invoke([msg])
        result = parser.invoke(response.content)
        return DocumentExtractionResult(**result)
    except Exception as e:
        print(f"Error calling Vision LLM for extraction: {e}")
        return DocumentExtractionResult(confidence_score=0.0, extracted_fields={})

class ConfidenceEvaluationResult(BaseModel):
    confidence_score: float = Field(description="The overall confidence score between 0.0 and 1.0 for the claim decision.")

def evaluate_decision_confidence(
    decision: str, 
    reasons: list[str], 
    avg_extraction_conf: float, 
    fraud_score: float, 
    component_failures: list[str]
) -> float:
    """Evaluate the overall confidence of the pipeline's claim decision using an LLM."""
    if not os.environ.get("GROQ_API_KEY"):
        return 0.95
        
    llm = get_text_llm()
    parser = JsonOutputParser(pydantic_object=ConfidenceEvaluationResult)
    
    prompt_text = """
    You are an AI auditor for a health insurance claims processing system.
    The automated pipeline has reached a decision on a claim. You need to assign an overall confidence score (0.0 to 1.0) to this decision based on the following context.
    
    Pipeline Context:
    - Final Decision: {decision}
    - Reasons/Flags: {reasons}
    - Average Data Extraction Confidence: {avg_extraction_conf}
    - Fraud Score: {fraud_score}
    - Component Failures: {component_failures}
    
    Instructions:
    1. If there are component failures, the confidence should be significantly lower (e.g., < 0.6).
    2. If the fraud score is high (> 0.5), the confidence in an automated approval should be lower, but confidence in a MANUAL_REVIEW decision might still be high because it was correctly flagged.
    3. If extraction confidence is low, the overall confidence should be similarly low.
    4. If the decision is REJECTED due to clear policy violations with high extraction confidence and no failures, the confidence should be high (> 0.9).
    5. Provide a realistic confidence score reflecting how trustworthy the system's output is given the context.
    
    Provide ONLY the requested JSON output format.
    {format_instructions}
    """
    
    msg = HumanMessage(
        content=[
            {"type": "text", "text": prompt_text.format(
                decision=decision,
                reasons=reasons,
                avg_extraction_conf=avg_extraction_conf,
                fraud_score=fraud_score,
                component_failures=component_failures,
                format_instructions=parser.get_format_instructions()
            )}
        ]
    )
    
    try:
        response = llm.invoke([msg])
        result = parser.invoke(response.content)
        return float(result.get("confidence_score", 0.85))
    except Exception as e:
        print(f"Error calling LLM for confidence evaluation: {e}")
        return 0.85
