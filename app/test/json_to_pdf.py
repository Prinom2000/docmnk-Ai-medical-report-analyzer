import json
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm

def wrap(text):
    """Convert plain text or dict/list into safe wrapped string."""
    if isinstance(text, (dict, list)):
        text = json.dumps(text, indent=2, ensure_ascii=False)
    return Paragraph(str(text), getSampleStyleSheet()['BodyText'])

def section_to_table(section_dict):
    """Convert sub-JSON (dict) into a PDF table with wrapping."""
    table_data = [["Key", "Value"]]

    for k, v in section_dict.items():
        table_data.append([wrap(k), wrap(v)])

    table = Table(
        table_data,
        colWidths=[60*mm, 100*mm]   # Enough space + wrapping support
    )

    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    
    return table

def json_to_pdf():
    json_file = "data.json"   # must be in same folder
    pdf_file = "output.pdf"

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    doc = SimpleDocTemplate(
        pdf_file,
        pagesize=A4,
        leftMargin=18*mm,
        rightMargin=18*mm,
        topMargin=18*mm,
        bottomMargin=18*mm
    )
    
    styles = getSampleStyleSheet()
    story = []

    # ---- PATIENT ID ----
    if "PATIENT_ID" in data:
        story.append(Paragraph("<b>PATIENT ID</b>", styles["Heading3"]))
        story.append(Paragraph(str(data["PATIENT_ID"]), styles["BodyText"]))
        story.append(Spacer(1, 12))

    # ---- MEDICAL ANALYSIS ----
    medical = data.get("medical_analysis", {})

    story.append(Paragraph("<b>MEDICAL ANALYSIS</b>", styles["Heading2"]))
    story.append(Spacer(1, 12))

    # Loop through each subsection (patient_info, vital_signs...)
    for section_name, section_value in medical.items():

        if isinstance(section_value, dict):
            # Section header
            story.append(Paragraph(f"<b>{section_name.replace('_',' ').title()}</b>", styles["Heading3"]))
            story.append(Spacer(1, 6))

            # Add table for this section
            story.append(section_to_table(section_value))
            story.append(Spacer(1, 14))

        else:
            # If not dict, still print nicely
            story.append(Paragraph(f"<b>{section_name}</b>", styles["Heading3"]))
            story.append(wrap(section_value))
            story.append(Spacer(1, 14))

    doc.build(story)
    print("PDF created:", pdf_file)


if __name__ == "__main__":
    json_to_pdf()
