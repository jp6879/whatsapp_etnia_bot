import redis
import json
from app.config import redis_settings

r = redis.from_url(redis_settings.REDIS_DB_URL, decode_responses=True)


class RedisSession:
    SESSION_PREFIX = "wa_session:"

    def __init__(self, from_number: str):
        self.from_number = from_number
        self.state = "waiting"
        self.session = None

    def get_session_key(self) -> str:
        return self.SESSION_PREFIX + self.from_number

    def load_session(self) -> bool:
        """Load session from Redis. Returns True if a session was loaded, False otherwise.

        When loaded, sets `self.session` to the dict and `self.state` to session['state'] if present.
        """
        key = self.get_session_key()
        raw = r.get(key)
        if raw:
            try:
                self.session = json.loads(raw)
                self.state = self.session.get("state", "waiting")
            except Exception:
                self.session = None
                self.state = "waiting"
                r.delete(key)
                return False
            return True
        return False

    def save_session(self, session: dict):
        key = self.get_session_key()
        self.session = session
        self.state = session.get("state", self.state)
        r.set(key, json.dumps(session))

    def clear_session(self):
        r.delete(self.SESSION_PREFIX + self.from_number)
