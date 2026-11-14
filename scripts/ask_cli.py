import sys
import json
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.tenancy import resolve_clinic_by_slug
from app.rag import answer_question

def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/ask_cli.py <clinic_slug> \"<question>\"")
        sys.exit(1)

    slug = sys.argv[1]
    question = sys.argv[2]

    try:
        clinic = resolve_clinic_by_slug(slug)
    except Exception as e:
        print(f"Error: Clinic slug '{slug}' not found: {e}")
        sys.exit(1)

    clinic_id = clinic["id"]
    print(f"=== Clinic FAQ Query CLI ===")
    print(f"Clinic: {clinic['name']} (ID: {clinic_id})")
    print(f"Question: \"{question}\"")
    print("-" * 50)

    result = answer_question(clinic_id, question)

    print(f"Answer: {result['answer']}")
    print(f"Kind: {result['kind']}")
    print(f"Source: {result['source_title']}")
    print(f"Confidence / Similarity: {result.get('confidence', 0.0):.4f}")
    if result.get("lesson_id"):
        print(f"Lesson ID: {result['lesson_id']} (Approved lesson applied)")
    print("-" * 50)

if __name__ == "__main__":
    main()
