import os
import base64
import json
from pathlib import Path
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
        model="llama-3.2-90b-vision-preview",
        temperature=0.1,  # Low temperature for deterministic extraction
        max_tokens=500,
    )

class DocumentAnalysisResult(BaseModel):
    quality: str = Field(description="The quality of the document: GOOD, FAIR, POOR, or UNREADABLE")
    patient_name: str | None = Field(description="The patient name extracted from the document, or null if not found")

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
        return DocumentAnalysisResult(quality="GOOD", patient_name="Rajesh Kumar")

    try:
        base64_image = encode_file_to_base64(file_path)
    except Exception as e:
        print(f"Error encoding file: {e}")
        return DocumentAnalysisResult(quality="UNREADABLE", patient_name=None)

    llm = get_vision_llm()
    parser = JsonOutputParser(pydantic_object=DocumentAnalysisResult)

    prompt_text = """
    You are an expert document verification assistant for a health insurance claims processing system.
    Please analyze the provided document image and output a JSON object with two fields: 'quality' and 'patient_name'.

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
        return DocumentAnalysisResult(quality="POOR", patient_name=None)
