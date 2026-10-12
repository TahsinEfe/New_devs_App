"""Regression tests for tenant isolation, local periods, and exact money.

Run: python -m unittest discover -s tests -v (from backend).
Database/Redis I/O is mocked here; the HTTP smoke script exercises Docker services.
"""
import json
import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from fastapi.security import HTTPAuthorizationCredentials
from redis.exceptions import ConnectionError as RedisConnectionError

from app.config import settings
from app.core import auth
from app.core.database_pool import DatabasePool
from app.services import cache, reservations
from app.api.v1 import dashboard, login


class PeriodTests(unittest.TestCase):
    def test_paris_march_includes_february_utc_booking_and_respects_dst(self):
        start, end = reservations.revenue_bounds(2024, 3, "Europe/Paris")
        self.assertEqual(start, datetime(2024, 2, 29, 23, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2024, 3, 31, 22, tzinfo=timezone.utc))
        booking = datetime(2024, 2, 29, 23, 30, tzinfo=timezone.utc)
        self.assertTrue(start <= booking < end)

    def test_new_york_march_and_exclusive_end(self):
        start, end = reservations.revenue_bounds(2024, 3, "America/New_York")
        self.assertEqual(start, datetime(2024, 3, 1, 5, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2024, 4, 1, 4, tzinfo=timezone.utc))
        self.assertFalse(start <= end < end)

    def test_december_and_annual_rollover(self):
        start, end = reservations.revenue_bounds(2024, 12, "UTC")
        self.assertEqual(end, datetime(2025, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(start.month, 12)
        start, end = reservations.revenue_bounds(2024, None, "Europe/Paris")
        self.assertEqual(start, datetime(2023, 12, 31, 23, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2024, 12, 31, 23, tzinfo=timezone.utc))

    def test_invalid_period_rejected(self):
        for year, month in [(2024, 0), (2024, 13), (0, 3), (9999, 12)]:
            with self.assertRaises(ValueError):
                reservations.revenue_bounds(year, month, "UTC")


def fake_session(amount=Decimal("2250.000"), count=4, currency="USD"):
    prop = SimpleNamespace(timezone="Europe/Paris")
    row = SimpleNamespace(total_revenue=amount, reservation_count=count, currency=currency)
    session = SimpleNamespace(execute=AsyncMock(side_effect=[
        SimpleNamespace(fetchone=lambda: prop),
        SimpleNamespace(fetchall=lambda: [row]),
    ]))
    return session


class CalculationTests(unittest.IsolatedAsyncioTestCase):
    async def test_seed_property_month_and_tenant_scoped_sql(self):
        session = fake_session()
        result = await reservations.calculate_total_revenue(
            "prop-001", "tenant-a", month=3, year=2024, db_session=session
        )
        self.assertEqual(result["total"], "2250.00")
        self.assertEqual(result["count"], 4)
        for call in session.execute.call_args_list:
            self.assertIn("tenant_id = :tenant_id", str(call.args[0]))
            self.assertEqual(call.args[1]["tenant_id"], "tenant-a")
        query, params = session.execute.call_args_list[1].args
        self.assertIn("check_in_date < :end_date", str(query))
        self.assertEqual(params["start_date"], datetime(2024, 2, 29, 23, tzinfo=timezone.utc))

    async def test_subcent_aggregate_not_rounded_per_booking(self):
        amount = sum([Decimal("333.333"), Decimal("333.333"), Decimal("333.334")])
        result = await reservations.calculate_total_revenue(
            "prop-001", "tenant-a", db_session=fake_session(amount, 3)
        )
        self.assertEqual(result["total"], "1000.00")

    async def test_half_cent_rounded_half_up(self):
        result = await reservations.calculate_total_revenue(
            "prop-001", "tenant-a", db_session=fake_session(Decimal("1.005"))
        )
        self.assertEqual(result["total"], "1.01")

    async def test_currency_preserved_and_mixed_currency_rejected(self):
        result = await reservations.calculate_total_revenue(
            "prop-001", "tenant-a", db_session=fake_session(currency="EUR")
        )
        self.assertEqual(result["currency"], "EUR")
        session = fake_session()
        session.execute = AsyncMock(side_effect=[
            SimpleNamespace(fetchone=lambda: SimpleNamespace(timezone="UTC")),
            SimpleNamespace(fetchall=lambda: [SimpleNamespace(currency="USD"), SimpleNamespace(currency="EUR")]),
        ])
        with self.assertRaises(ValueError):
            await reservations.calculate_total_revenue("prop-001", "tenant-a", db_session=session)

    async def test_empty_property_zero_and_unowned_property_not_found(self):
        session = fake_session()
        session.execute = AsyncMock(side_effect=[
            SimpleNamespace(fetchone=lambda: SimpleNamespace(timezone="UTC")),
            SimpleNamespace(fetchall=lambda: []),
        ])
        result = await reservations.calculate_total_revenue("prop-001", "tenant-b", db_session=session)
        self.assertEqual(result["total"], "0.00")
        self.assertEqual(result["count"], 0)
        session.execute = AsyncMock(return_value=SimpleNamespace(fetchone=lambda: None))
        with self.assertRaises(LookupError):
            await reservations.calculate_total_revenue("prop-002", "tenant-b", db_session=session)

    async def test_database_failure_never_returns_mock_money(self):
        session = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("DB down")))
        with self.assertRaises(RuntimeError):
            await reservations.calculate_total_revenue("prop-001", "tenant-a", db_session=session)

    async def test_pool_uses_configured_url_and_sync_context_manager(self):
        pool = DatabasePool()
        with patch("app.core.database_pool.create_async_engine") as create:
            await pool.initialize()
            self.assertIn("postgresql+asyncpg://", create.call_args.args[0])
            self.assertNotIn("poolclass", create.call_args.kwargs)
            await pool.initialize()
            self.assertEqual(create.call_count, 1)
            self.assertTrue(hasattr(pool.get_session(), "__aenter__"))


class CacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_tenants_and_periods_do_not_share_cache_even_when_ids_match(self):
        values = {"revenue:prop-001": json.dumps({"tenant_id": "tenant-a", "total": "9999"})}
        async def get(key):
            return values.get(key)
        async def setex(key, ttl, value):
            values[key] = value
        async def calculate(property_id, tenant_id, **kwargs):
            return {"tenant_id": tenant_id, "property_id": property_id,
                    "total": "2250.00" if tenant_id == "tenant-a" else "0.00", "currency": "USD", "count": 0}
        with patch.object(cache, "redis_client", SimpleNamespace(get=get, setex=setex)), patch.object(reservations, "calculate_total_revenue", AsyncMock(side_effect=calculate)) as calc:
            for tenant in ["tenant-a", "tenant-b", "tenant-b", "tenant-a"]:
                result = await cache.get_revenue_summary("prop-001", tenant, 3, 2024)
                self.assertEqual(result["tenant_id"], tenant)
            self.assertEqual(calc.call_count, 2)
            await cache.get_revenue_summary("prop-001", "tenant-a", 2, 2024)
            await cache.get_revenue_summary("prop-001", "tenant-a", None, 2024)
            self.assertEqual(calc.call_count, 4)

    async def test_redis_outage_falls_back_to_real_database(self):
        redis = SimpleNamespace(get=AsyncMock(side_effect=RedisConnectionError()), setex=AsyncMock(side_effect=RedisConnectionError()))
        expected = {"tenant_id": "tenant-a", "property_id": "prop-001", "total": "2250.00"}
        with patch.object(cache, "redis_client", redis), patch.object(reservations, "calculate_total_revenue", AsyncMock(return_value=expected)):
            self.assertEqual(await cache.get_revenue_summary("prop-001", "tenant-a"), expected)


class AuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        auth.clear_auth_cache()

    async def test_forged_and_expired_local_tokens_rejected(self):
        for secret, expiry in [("wrong-secret", timedelta(hours=1)), (settings.secret_key, timedelta(seconds=-1))]:
            token = jwt.encode({"id": "user-sunset", "email": "sunset@propertyflow.com", "aud": "authenticated", "exp": datetime.now(timezone.utc) + expiry}, secret, algorithm="HS256")
            with self.assertRaises(HTTPException) as error:
                await auth.authenticate_request(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
            self.assertEqual(error.exception.status_code, 401)

    async def test_signed_token_missing_tenant_fails_closed(self):
        token = jwt.encode({"id": "unknown", "email": "unknown@example.com", "aud": "authenticated", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, settings.secret_key, algorithm="HS256")
        with self.assertRaises(HTTPException) as error:
            await auth.authenticate_request(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
        self.assertEqual(error.exception.status_code, 403)


class HttpTests(unittest.TestCase):
    def setUp(self):
        auth.clear_auth_cache()
        app = FastAPI()
        app.include_router(login.router, prefix="/api/v1")
        app.include_router(dashboard.router, prefix="/api/v1")
        self.client = TestClient(app)

    def token(self, email, password):
        response = self.client.post("/api/v1/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200)
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    def test_both_client_credentials_and_decimal_api_contract(self):
        async def summary(property_id, tenant_id, **kwargs):
            return {"property_id": property_id, "tenant_id": tenant_id,
                    "total": "2250.00" if tenant_id == "tenant-a" else "0.00", "currency": "USD", "count": 4 if tenant_id == "tenant-a" else 0}
        with patch.object(dashboard, "get_revenue_summary", AsyncMock(side_effect=summary)) as calc:
            for email, password, expected in [("sunset@propertyflow.com", "client_a_2024", "2250.00"), ("ocean@propertyflow.com", "client_b_2024", "0.00")]:
                response = self.client.get("/api/v1/dashboard/summary?property_id=prop-001&month=3&year=2024", headers=self.token(email, password))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["total_revenue"], expected)
            self.assertEqual(calc.call_args_list[0].args[1], "tenant-a")
            self.assertEqual(calc.call_args_list[1].args[1], "tenant-b")

    def test_unauthenticated_invalid_period_and_db_failure(self):
        self.assertEqual(self.client.get("/api/v1/dashboard/summary?property_id=prop-001").status_code, 401)
        headers = self.token("sunset@propertyflow.com", "client_a_2024")
        for query in ["month=13&year=2024", "month=3", "year=0"]:
            self.assertEqual(self.client.get("/api/v1/dashboard/summary?property_id=prop-001&" + query, headers=headers).status_code, 422)
        with patch.object(dashboard, "get_revenue_summary", AsyncMock(side_effect=RuntimeError("DB down"))):
            response = self.client.get("/api/v1/dashboard/summary?property_id=prop-001", headers=headers)
            self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
