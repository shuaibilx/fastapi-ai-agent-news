from datetime import datetime, timedelta
from unittest import IsolatedAsyncioTestCase

from app.models.users import UserToken
from app.services.users import create_token


class _Result:
    def __init__(self, token_record: UserToken):
        self._token_record = token_record

    def scalar_one_or_none(self) -> UserToken:
        return self._token_record


class _ExistingTokenSession:
    def __init__(self, token_record: UserToken):
        self._token_record = token_record
        self.committed = False

    async def execute(self, _query):
        return _Result(self._token_record)

    async def commit(self):
        self.committed = True


class UserTokenServiceTests(IsolatedAsyncioTestCase):
    async def test_relogin_refreshes_existing_token_expiration(self):
        expired_at = datetime.now() - timedelta(days=1)
        token_record = UserToken(
            user_id=1,
            token="expired-token",
            expires_at=expired_at,
        )
        db = _ExistingTokenSession(token_record)

        new_token = await create_token(db, user_id=1)

        self.assertNotEqual(token_record.token, "expired-token")
        self.assertEqual(token_record.token, new_token)
        self.assertGreater(token_record.expires_at, datetime.now())
        self.assertTrue(db.committed)
