import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db import get_db, tenant_tx
from app.auth import hash_password, hash_token
from app.knowledge import process_knowledge_item
from app.embeddings import get_single_embedding
from app.api_v1 import generate_clinic_api_key

def seed_demo_data():
    print("Seeding multi-tenant demonstration data...")
    password_hash = hash_password("***REMOVED***!")

    with get_db() as conn:
        with conn.cursor() as cur:
            # 1. Sunrise Clinic
            cur.execute("""
                INSERT INTO clinics (name, slug, contact_email, webhook_url, webhook_secret)
                VALUES ('Sunrise Clinic', 'sunrise-clinic', 'support@sunriseclinic.com', 'https://example.com/webhook', 'sunrise_***REMOVED***')
                ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
                RETURNING id;
            """)
            clinic_a_id = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO admin_users (clinic_id, email, password_hash, role)
                VALUES (%s, 'admin@sunriseclinic.com', %s, 'owner')
                ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;
            """, (clinic_a_id, password_hash))

            # 2. City Care Clinic
            cur.execute("""
                INSERT INTO clinics (name, slug, contact_email)
                VALUES ('City Care Clinic', 'city-care-clinic', 'info@citycareclinic.com')
                ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
                RETURNING id;
            """)
            clinic_b_id = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO admin_users (clinic_id, email, password_hash, role)
                VALUES (%s, 'admin@citycareclinic.com', %s, 'owner')
                ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;
            """, (clinic_b_id, password_hash))

    print(f"Created/verified clinics: Sunrise Clinic ({clinic_a_id}) and City Care Clinic ({clinic_b_id})")

    # Knowledge for Sunrise Clinic (A)
    with tenant_tx(clinic_a_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO knowledge_items (clinic_id, type, title, body, status)
                VALUES 
                (%s, 'text', 'Sunrise Operating Hours & Location', 
                 'Sunrise Clinic is located at 124 Medical Plaza, Suite 400. Operating hours: Monday to Friday 8:00 AM to 6:00 PM. Saturday 9:00 AM to 1:00 PM. Closed on Sundays. Free patient parking is available at the rear structure.', 'ready'),
                (%s, 'price_list', 'Sunrise Consultation Pricing',
                 'Service | Fee\nGeneral Consultation | $75\nPediatric Checkup | $65\nAnnual Wellness Exam | $120\nFlu Vaccination | $35', 'ready')
                RETURNING id;
            """, (clinic_a_id, clinic_a_id))
            item_a1 = cur.fetchone()[0]

    # Process chunks for Sunrise
    process_knowledge_item(clinic_a_id, str(item_a1))

    # Knowledge for City Care Clinic (B)
    with tenant_tx(clinic_b_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO knowledge_items (clinic_id, type, title, body, status)
                VALUES 
                (%s, 'text', 'City Care Schedule and Services', 
                 'City Care Clinic operates 24/7 for urgent care walk-ins. General practitioner appointments are scheduled Monday through Saturday 9:00 AM to 8:00 PM. Located downtown at 500 Metro Boulevard.', 'ready'),
                (%s, 'price_list', 'City Care Urgent Fees',
                 'Service | Fee\nUrgent Walk-in Triage | $110\nSpecialist Referral Visit | $150\nX-Ray Imaging | $90', 'ready')
                RETURNING id;
            """, (clinic_b_id, clinic_b_id))
            item_b1 = cur.fetchone()[0]

    process_knowledge_item(clinic_b_id, str(item_b1))

    # Seed multi-week ratings and lesson uses for Sunrise Clinic to show learning curve
    now = datetime.now(timezone.utc)
    with tenant_tx(clinic_a_id) as conn:
        with conn.cursor() as cur:
            # Create a lesson for Sunrise
            q_text = "What is the parking situation at Sunrise Clinic?"
            lesson_emb = get_single_embedding(q_text)
            cur.execute("""
                INSERT INTO lessons (clinic_id, question_text, bad_answer, correct_answer, comment, embedding, enabled, times_used)
                VALUES (%s, %s, 'No parking mentioned.', 'Free patient parking is available directly behind the building in structure B.', 'Verified by receptionist', %s, true, 18)
                RETURNING id;
            """, (clinic_a_id, q_text, lesson_emb))
            lesson_id = cur.fetchone()[0]

            # Simulate 4 past weeks of ratings where Good percentage rises
            # Week -3: 4 good, 8 bad (33% good)
            # Week -2: 9 good, 5 bad (64% good)
            # Week -1: 15 good, 3 bad (83% good)
            # Week 0:  22 good, 2 bad (91% good)
            weekly_plan = [
                (-3, 4, 8, 2),
                (-2, 9, 5, 5),
                (-1, 15, 3, 11),
                (0, 22, 2, 18),
            ]

            for week_offset, good_count, bad_count, lessons_count in weekly_plan:
                base_time = now + timedelta(weeks=week_offset)
                for _ in range(good_count):
                    cur.execute("""
                        INSERT INTO questions (clinic_id, text, status, asked_at)
                        VALUES (%s, 'What are your hours?', 'answered', %s)
                        RETURNING id;
                    """, (clinic_a_id, base_time))
                    qid = cur.fetchone()[0]
                    cur.execute("""
                        INSERT INTO answers (clinic_id, question_id, text, kind, source_title, created_at)
                        VALUES (%s, %s, 'Sunrise Clinic is open Monday to Friday 8am to 6pm.', 'ai', 'Sunrise Operating Hours & Location', %s)
                        RETURNING id;
                    """, (clinic_a_id, qid, base_time))
                    aid = cur.fetchone()[0]
                    cur.execute("""
                        INSERT INTO ratings (clinic_id, answer_id, value, rated_at)
                        VALUES (%s, %s, 'good', %s)
                        ON CONFLICT (answer_id) DO NOTHING;
                    """, (clinic_a_id, aid, base_time))

                for _ in range(bad_count):
                    cur.execute("""
                        INSERT INTO questions (clinic_id, text, status, asked_at)
                        VALUES (%s, 'Where can I park?', 'answered', %s)
                        RETURNING id;
                    """, (clinic_a_id, base_time))
                    qid = cur.fetchone()[0]
                    cur.execute("""
                        INSERT INTO answers (clinic_id, question_id, text, kind, created_at)
                        VALUES (%s, %s, 'I do not have parking details.', 'ai', %s)
                        RETURNING id;
                    """, (clinic_a_id, qid, base_time))
                    aid = cur.fetchone()[0]
                    cur.execute("""
                        INSERT INTO ratings (clinic_id, answer_id, value, comment, rated_at)
                        VALUES (%s, %s, 'bad', 'Please provide parking location', %s)
                        ON CONFLICT (answer_id) DO NOTHING;
                    """, (clinic_a_id, aid, base_time))

                for _ in range(lessons_count):
                    cur.execute("""
                        INSERT INTO questions (clinic_id, text, status, asked_at)
                        VALUES (%s, 'What is parking like?', 'answered', %s)
                        RETURNING id;
                    """, (clinic_a_id, base_time))
                    qid = cur.fetchone()[0]
                    cur.execute("""
                        INSERT INTO answers (clinic_id, question_id, text, kind, lesson_id, source_title, created_at)
                        VALUES (%s, %s, 'Free patient parking is available directly behind the building.', 'lesson', %s, 'Verified Clinic Lesson', %s)
                        RETURNING id;
                    """, (clinic_a_id, qid, lesson_id, base_time))
                    aid = cur.fetchone()[0]
                    cur.execute("""
                        INSERT INTO lesson_uses (clinic_id, lesson_id, answer_id, similarity, used_at)
                        VALUES (%s, %s, %s, 0.92, %s);
                    """, (clinic_a_id, lesson_id, aid, base_time))

    # Generate an API key for Sunrise Clinic
    raw_key, prefix = generate_clinic_api_key(clinic_a_id, "Sunrise Mobile App Key")
    print(f"Generated demo API key for Sunrise Clinic: {raw_key}")
    print("Seeding completed successfully.")

if __name__ == "__main__":
    seed_demo_data()
