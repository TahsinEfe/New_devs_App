"""Exercise the running Docker stack using the assignment's client credentials.

Run from the repository root: python3 scripts/smoke_revenue.py
Optional URL: python3 scripts/smoke_revenue.py http://localhost:8000
Requires only Python's standard library and a fresh supplied seed database.
"""
import json
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE = sys.argv[1].rstrip('/') if len(sys.argv) > 1 else 'http://localhost:8000'


def call(path, token=None, data=None, expected_status=200):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(BASE + '/api/v1' + path, headers=headers,
                      data=json.dumps(data).encode() if data is not None else None)
    try:
        with urlopen(request, timeout=15) as response:
            status, body = response.status, response.read()
    except HTTPError as error:
        status, body = error.code, error.read()
    assert status == expected_status, (path, status, body.decode())
    return json.loads(body)


def login(email, password):
    return call('/auth/login', data={'email': email, 'password': password})['access_token']


def summary(token, property_id, total, count, period='&month=3&year=2024'):
    data = call('/dashboard/summary?property_id=' + property_id + period, token)
    assert data['total_revenue'] == total, data
    assert data['reservations_count'] == count, data
    assert data['currency'] == 'USD', data
    return data


def main():
    a = login('sunset@propertyflow.com', 'client_a_2024')
    b = login('ocean@propertyflow.com', 'client_b_2024')
    assert call('/auth/me', a)['tenant_id'] == 'tenant-a'
    assert call('/auth/me', b)['tenant_id'] == 'tenant-b'
    a_properties = call('/dashboard/properties', a)
    b_properties = call('/dashboard/properties', b)
    assert [p['id'] for p in a_properties] == ['prop-001', 'prop-002', 'prop-003']
    assert [p['id'] for p in b_properties] == ['prop-001', 'prop-004', 'prop-005']
    assert a_properties[0]['name'] == 'Beach House Alpha'
    assert b_properties[0]['name'] == 'Mountain Lodge Beta'

    # Warm the cache, then alternate customers with the SAME property ID.
    for token, total, count in [(a, '2250.00', 4), (b, '0.00', 0)] * 3:
        summary(token, 'prop-001', total, count)
    summary(a, 'prop-001', '0.00', 0, '&month=2&year=2024')
    summary(a, 'prop-001', '2250.00', 4, '&year=2024')
    summary(a, 'prop-001', '2250.00', 4, '')
    summary(a, 'prop-002', '4975.50', 4)
    summary(a, 'prop-003', '6100.50', 2)
    summary(b, 'prop-004', '1776.50', 4)
    summary(b, 'prop-005', '3256.00', 3)
    call('/dashboard/summary?property_id=prop-002', b, expected_status=404)
    call('/dashboard/summary?property_id=prop-004', a, expected_status=404)
    call('/dashboard/summary?property_id=prop-001&month=13&year=2024', a, expected_status=422)
    call('/dashboard/summary?property_id=prop-001&month=3', a, expected_status=422)
    call('/dashboard/summary?property_id=prop-001', expected_status=401)
    print('PASS: both logins, tenant property lists, cache isolation, local periods, exact totals, and denied access')


if __name__ == '__main__':
    main()
