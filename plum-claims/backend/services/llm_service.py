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

class PageAnalysis(BaseModel):
    page_index: int = Field(description="The 0-based index of the page being analyzed.")
    quality: str = Field(description="The quality of this specific page: GOOD, FAIR, POOR, or UNREADABLE")
    patient_name: str | None = Field(description="The patient name extracted from this specific page, or null if not found")
    detected_type: str = Field(description="The exact document type detected on this specific page. Valid options: PRESCRIPTION, HOSPITAL_BILL, LAB_REPORT, DIAGNOSTIC_REPORT, PHARMACY_BILL, DENTAL_REPORT, DISCHARGE_SUMMARY, or UNKNOWN")

class DocumentAnalysisResult(BaseModel):
    pages: list[PageAnalysis] = Field(description="An array containing the analysis for every page provided.")

def encode_file_to_base64_list(file_path: str, max_pages: int = 5) -> list[str]:
    """Read a file and convert it to a list of base64 encoded strings.
    If it's a PDF, render up to max_pages to images.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()
    if ext == ".pdf":
        doc = fitz.open(str(path))
        if len(doc) == 0:
            raise ValueError("PDF is empty")
        
        base64_images = []
        pages_to_process = min(len(doc), max_pages)
        for i in range(pages_to_process):
            page = doc.load_page(i)
            # Render at 150 DPI for decent quality but manageable size
            pix = page.get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72))
            image_bytes = pix.tobytes("png")
            base64_images.append(base64.b64encode(image_bytes).decode('utf-8'))
        doc.close()
        return base64_images
    else:
        # Assume it's an image
        with open(path, "rb") as image_file:
            return [base64.b64encode(image_file.read()).decode('utf-8')]

def analyze_document(file_path: str) -> DocumentAnalysisResult:
    """Analyze all pages of a document for quality and extract patient name and type using a Vision LLM in a single pass."""
    if not os.environ.get("GROQ_API_KEY"):
        print("Warning: GROQ_API_KEY not set. Simulating LLM response.")
        return DocumentAnalysisResult(pages=[PageAnalysis(page_index=0, quality="GOOD", patient_name="Rajesh Kumar", detected_type="UNKNOWN")])

    try:
        base64_images = encode_file_to_base64_list(file_path)
    except Exception as e:
        print(f"Error encoding file: {e}")
        return DocumentAnalysisResult(pages=[PageAnalysis(page_index=0, quality="UNREADABLE", patient_name=None, detected_type="UNKNOWN")])

    llm = get_vision_llm()
    parser = JsonOutputParser(pydantic_object=DocumentAnalysisResult)

    prompt_text = """
    You are an expert document analysis assistant for a health insurance claims system.
    Please analyze the provided document images (which represent sequential pages of a document).
    Output a JSON object with a single 'pages' array. Each item in the array must correspond to one page and include: 'page_index', 'quality', 'patient_name', and 'detected_type'.

    For each page in the document (starting from page_index 0):
    
    1. **Document Quality Evaluation:**
    Carefully assess the legibility and overall quality of the page based on the following criteria:
    - **GOOD**: perfectly clear, well-lit, fully legible.
    - **FAIR**: minor blurriness or glare, but critical information is readable.
    - **POOR**: severe blur, low resolution, bad lighting.
    - **UNREADABLE**: completely illegible.
    Determine the quality and output one of these exact strings: "GOOD", "FAIR", "POOR", "UNREADABLE".

    2. **Patient Name Extraction:**
    Carefully scan the page to locate the name of the patient.
    - Extract ONLY the full name of the patient as it appears on the page.
    - If you cannot find a patient name on this specific page, output null.

    3. **Document Type Classification:**
    Classify the specific page into EXACTLY ONE of the following categories based on its visual contents:
    - "PRESCRIPTION": Doctor's notes prescribing medication, tests, or treatment.
    - "HOSPITAL_BILL": An invoice or bill from a hospital or clinic showing charges.
    - "PHARMACY_BILL": A receipt specifically for purchased medicines.
    - "LAB_REPORT" or "DIAGNOSTIC_REPORT": Results of blood tests, scans, or pathology.
    - "DENTAL_REPORT": Notes or reports specific to dental work.
    - "DISCHARGE_SUMMARY": A detailed summary given when a patient leaves a hospital.
    - "UNKNOWN": If the document is none of the above or cannot be identified.
    Output the exact string matching the classification for this page.

    Provide ONLY the requested JSON output format.
    {format_instructions}
    """

    # Format the prompt
    format_instructions = parser.get_format_instructions()
    
    # Construct the message
    content = [{"type": "text", "text": prompt_text.replace("{format_instructions}", format_instructions)}]
    for i, b64 in enumerate(base64_images):
        content.append({
            "type": "text",
            "text": f"--- Page {i} ---"
        })
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })
        
    msg = HumanMessage(content=content)

    try:
        response = llm.invoke([msg])
        result = parser.invoke(response.content)
        return DocumentAnalysisResult(**result)
    except Exception as e:
        print(f"Error calling Vision LLM: {e}")
        # Graceful fallback if LLM fails
        return DocumentAnalysisResult(pages=[PageAnalysis(page_index=0, quality="POOR", patient_name=None, detected_type="UNKNOWN")])

class DocumentExtractionResult(BaseModel):
    confidence_score: float = Field(description="A confidence score between 0.0 and 1.0 indicating how certain you are of the extracted values.")
    extracted_fields: dict[str, Any] = Field(description="A dictionary containing the extracted fields.")
    document_flags: list[str] = Field(default=[], description="List of flags for document issues (e.g., DOCUMENT_ALTERATION, DUPLICATE_STAMP, MISSING_FIELDS, MULTILINGUAL).")

def extract_document_data(file_path: str, document_type: str) -> DocumentExtractionResult:
    """Extract structured data from a document using a Vision LLM."""
    if not os.environ.get("GROQ_API_KEY"):
        return DocumentExtractionResult(confidence_score=0.9, extracted_fields={}, document_flags=[])

    try:
        base64_images = encode_file_to_base64_list(file_path)
    except Exception as e:
        print(f"Error encoding file: {e}")
        return DocumentExtractionResult(confidence_score=0.0, extracted_fields={}, document_flags=["ENCODING_ERROR"])

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

    Extract the values accurately. If any of the requested fields are not found in the document, omit them from the extracted_fields dictionary, but you MUST add "MISSING_FIELDS" to the document_flags list.
    Provide a 'confidence_score' between 0.0 and 1.0 representing your certainty in the extracted data.

    **Special Instructions for Indian Medical Documents:**
    - **Handwritten Text:** Use best-effort OCR for handwriting. Expect common Indian diagnoses (e.g., Viral Fever, URI, Gastroenteritis, UTI, Dengue, Typhoid, Hypertension/HTN, Type 2 Diabetes/T2DM, Hypothyroidism, Lumbar Spondylosis, Knee Osteoarthritis, Migraine, GERD).
    - **Rubber Stamps:** If rubber stamps obscure text (like registration numbers), do your best to extract the text and lower confidence for that field.
    - **Multilingual Content:** Extract all English fields. If there is regional text (Hindi, Tamil, Telugu, etc.), ignore it but add "MULTILINGUAL" to document_flags.
    - **Corrections/Alterations:** If amounts or text are crossed out and rewritten, extract the final corrected value and add "DOCUMENT_ALTERATION" to document_flags.
    - **Duplicate Stamps:** If there are multiple "ORIGINAL" or "DUPLICATE" stamps, note this by adding "DUPLICATE_STAMP" to document_flags.
    - **Partial Document:** If a page is cut off or folded, extract available fields and add "PARTIAL_DOCUMENT" to document_flags.

    Provide ONLY the requested JSON output format.
    {{format_instructions}}
    """

    format_instructions = parser.get_format_instructions()
    
    content = [{"type": "text", "text": prompt_text.format(format_instructions=format_instructions)}]
    for b64 in base64_images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })
        
    msg = HumanMessage(content=content)

    try:
        response = llm.invoke([msg])
        result = parser.invoke(response.content)
        return DocumentExtractionResult(**result)
    except Exception as e:
        print(f"Error calling Vision LLM for extraction: {e}")
        return DocumentExtractionResult(confidence_score=0.0, extracted_fields={}, document_flags=["LLM_ERROR"])

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
