import json

from psycopg2.pool import ThreadedConnectionPool

from post_processor.config import get_database_url, pp_logger

_db_pool: ThreadedConnectionPool | None = None


def get_db_pool() -> ThreadedConnectionPool:
    global _db_pool
    if _db_pool is None:
        _db_pool = ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=get_database_url(),
        )
        pp_logger.info("Postgres connection pool initialized for post-processor")
    return _db_pool


def shutdown_db_pool() -> None:
    global _db_pool
    if _db_pool is not None:
        _db_pool.closeall()
        _db_pool = None
        pp_logger.info("Post-processor Postgres pool closed")


def find_caller(cur, phone: str) -> str | None:
    if not phone:
        return None
    for candidate in (phone, f"91{phone}"):
        cur.execute(
            "SELECT id::text FROM callers WHERE phone_number = %s LIMIT 1",
            (candidate,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
    return None


def create_caller(cur, name: str, phone: str) -> str:
    phone_db = f"91{phone}" if phone else None
    cur.execute(
        """
        INSERT INTO callers (name, email, phone_number)
        VALUES (%s, NULL, %s)
        RETURNING id::text
        """,
        (name, phone_db or phone or None),
    )
    caller_id = cur.fetchone()[0]
    pp_logger.info(f"Created caller id={caller_id} name={name!r} phone={phone_db or phone}")
    return caller_id


def upsert_analytics(
    cur,
    caller_id: str,
    course_interest: str,
    city: str,
    budget: str,
    intent_level: str,
) -> None:
    cur.execute(
        """
        INSERT INTO caller_analytics (
            caller_id, course_interest, city, budget, hostel_needed, intent_level
        ) VALUES (%s, %s, %s, %s, FALSE, %s)
        ON CONFLICT (caller_id) DO UPDATE SET
            course_interest = EXCLUDED.course_interest,
            city = EXCLUDED.city,
            budget = EXCLUDED.budget,
            hostel_needed = FALSE,
            intent_level = EXCLUDED.intent_level
        """,
        (caller_id, course_interest or None, city or None, budget or None, intent_level),
    )


def insert_conversation(
    cur,
    caller_id: str,
    conversation: str,
    languages: list[str],
    bulk_offers: list[str],
) -> str:
    cur.execute(
        """
        INSERT INTO conversation_history (
            caller_id, conversation, languages_used, scholarships
        ) VALUES (%s, %s, %s, %s)
        RETURNING id::text
        """,
        (
            caller_id,
            conversation,
            json.dumps(languages),
            json.dumps(bulk_offers) if bulk_offers else None,
        ),
    )
    return cur.fetchone()[0]


def persist_call_record(
    *,
    name: str,
    phone: str,
    course_interest: str,
    city: str,
    budget: str,
    intent_level: str,
    conversation: str,
    languages: list[str],
    bulk_offers: list[str],
) -> tuple[str, str]:
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            caller_id = find_caller(cur, phone)
            if not caller_id:
                caller_id = create_caller(cur, name, phone)
            upsert_analytics(cur, caller_id, course_interest, city, budget, intent_level)
            conv_id = insert_conversation(cur, caller_id, conversation, languages, bulk_offers)
        conn.commit()
        return caller_id, conv_id
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)
